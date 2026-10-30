"""Contextual hailing and traversal of the validated authored dialogue graph.

V1-31 adds each cat's quest chain (quest A, then quest B the game day after A is
turned in), friendship greetings, turn-ins at the lake's host, every reward kind
through the one claim ledger, and friends' letters carried by Postmaster Pounce.
"""

from dataclasses import dataclass, field
import hashlib
import math

from .narrative import RIPPLE_BY_QUEST

HAIL_RANGE_M = 20.0
# Boat speed is metres/second; one knot is exactly 1852 metres/hour.
HAIL_SPEED_MPS = 3.0 * 1852 / 3600
TALK_DAYS_KEPT = 8
HOST_TURN_IN_LINE = "Finished something for a neighbor? I'll see that they hear about it."
HOST_HANDED_IN_LINE = "Lovely work. They left this with me for you."
LETTER_LINE = "Letter for you, {Skipper}! From {name}."


def nearby_npc(state):
    if abs(state.speed) >= HAIL_SPEED_MPS:
        return None
    eligible = [(math.hypot(state.x - n.anchor.x, state.z - n.anchor.z), n.id, n)
                for n in state.npcs if n.anchor.lake_id == state.lake_id]
    eligible = [row for row in eligible if row[0] <= HAIL_RANGE_M]
    return min(eligible, default=(0, '', None))[-1]


def _v3_reward(content, quest_id: str):
    """A V3 quest's reward, re-checked against the contract before any payout."""
    quest = content.quests.get(quest_id)
    reward_id = quest.get('reward_id') if quest else None
    reward = content.rewards.get(reward_id)
    if (not isinstance(reward, dict)
            or set(reward) != {'id', 'cash', 'ripple_id'}
            or reward.get('id') != reward_id
            or type(reward.get('cash')) is not int
            or reward['cash'] <= 0
            or reward.get('ripple_id') != RIPPLE_BY_QUEST.get(quest_id)):
        # Content validation rejects unsupported reward payloads before play.
        return None
    return reward


def _claim_and_pay(state, content, quest_id: str) -> bool:
    """Latch the claim, then credit every reward kind in the same save (06 §3.3)."""
    from .quests import apply_reward, claim_story_step
    definition = content.quests[quest_id]
    if definition.get('kind') == 'story':
        # A story step is not a side quest: no friend's letter, and the chapter may finish (V1-34).
        return claim_story_step(state, content, quest_id)
    if 'kind' not in definition:
        reward = _v3_reward(content, quest_id)
        if reward is None or not state.narrative.record_reward_claim(quest_id, state.game_minutes):
            return False
        # Quest cash adds to the purse, but is not fish-sale income (which drives
        # the first-sale tutorial). The livewell is intentionally left untouched.
        state.money = round(state.money + reward['cash'], 2)
        ripple_id = reward['ripple_id']
        if ripple_id is not None and ripple_id not in state.narrative.ripples:
            state.narrative.ripples.append(ripple_id)
        note = "Bot: He gives a small approving brass click."
        if state.narrative.record_bot_reaction(f"quest:{quest_id}", note):
            state.toast(note)
    else:
        if not state.narrative.record_reward_claim(quest_id, state.game_minutes):
            return False
        apply_reward(state, definition['reward'])
    queue_letter(state, content, definition['giver_id'])
    return True


def _turn_in_reward(state, content, quest_id: str, npc_id: str) -> bool:
    """Pay one ready quest to its present giver, at most once."""
    quest = content.quests.get(quest_id)
    progress = state.narrative.quests.get(quest_id)
    if quest is None or progress is None or quest.get('giver_id') != npc_id or progress.status != 'ready':
        return False
    if 'kind' not in quest:
        giver = content.npcs.get(npc_id)
        if giver is None or giver.get('quest_id') != quest_id:
            return False
    current = nearby_npc(state)
    if current is None or current.id != npc_id:
        state.toast(f"Come back to {content.name(npc_id)} when nearby to turn in.")
        return False
    return _claim_and_pay(state, content, quest_id)


def host_turn_ins(state, content, host_id: str) -> list[str]:
    """Ready side quests of the host's lake that another cat gave (02 §12.2 rule 3)."""
    host = content.cats.get(host_id)
    if host is None or host['role'] != 'host':
        return []
    ready = []
    for quest_id, quest in content.quests.items():
        progress = state.narrative.quests.get(quest_id)
        if (progress is not None and progress.status == 'ready' and quest.get('kind') != 'story'
                and quest.get('lake_id') == host['lake_id'] and quest.get('giver_id') != host_id):
            ready.append(quest_id)
    return ready


def turn_in_at_host(state, content, quest_id: str, host_id: str) -> bool:
    """The host takes the turn-in; the giver acknowledges it when next met."""
    if quest_id not in host_turn_ins(state, content, host_id):
        return False
    current = nearby_npc(state)
    if current is None or current.id != host_id:
        return False
    if 'kind' not in content.quests[quest_id] and _v3_reward(content, quest_id) is None:
        return False
    progress = state.narrative.quests[quest_id]
    if not _claim_and_pay(state, content, quest_id):
        return False
    progress.turned_in_by, progress.acknowledged = host_id, False
    return True


def _rank(*parts) -> int:
    digest = hashlib.sha256(":".join(str(part) for part in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def _letters(state) -> list:
    npcs = state.v2.setdefault('npcs', {})
    letters = npcs.get('letters')
    if not isinstance(letters, list):
        letters = npcs['letters'] = []
    return letters


def queue_letter(state, content, npc_id: str) -> bool:
    """A friend writes once their quests are all done; Pounce carries it (05 §9)."""
    from .quests import game_day, quest_status
    cat = content.cats.get(npc_id)
    if cat is None or not cat['letters'] or not cat['quests']:
        return False
    if any(quest_status(state, qid) != 'completed' for qid in cat['quests']):
        return False
    letters = _letters(state)
    if any(isinstance(row, dict) and row.get('from') == npc_id for row in letters):
        return False
    letters.append({'from': npc_id, 'variant': _rank('letter', state.narrative.schedule_seed, npc_id)
                    % len(cat['letters']), 'sent_day': game_day(state.game_minutes), 'delivered_day': None})
    return True


def next_letter(state, content) -> dict | None:
    """The oldest letter sent before today, if none has been delivered today."""
    from .quests import game_day
    today = game_day(state.game_minutes)
    waiting = []
    for row in _letters(state):
        if not isinstance(row, dict):
            continue
        if row.get('delivered_day') == today:
            return None
        cat = content.cats.get(row.get('from'))
        variant = row.get('variant')
        if (row.get('delivered_day') is None and cat is not None and type(variant) is int
                and 0 <= variant < len(cat['letters']) and type(row.get('sent_day')) is int
                and row['sent_day'] < today):
            waiting.append(row)
    return min(waiting, key=lambda row: (row['sent_day'], row['from']), default=None)


def greeting(state, content, npc_id: str, *, first: bool = False, world=None) -> str | list | None:
    """The most specific true greeting state the cat has a line for (05 §4).

    A first meeting is the most specific state. A state may list alternatives, one
    chosen per game day, and an alternative may be several bubbles (a list)."""
    from . import calendar
    from .fleet import chapter_finished
    from .quests import friendship, game_day
    cat = content.cats.get(npc_id)
    lines = cat['greetings'] if cat else {}
    if not lines:
        return None
    states = ['first'] if first else []
    if calendar.cookout_active(state.game_minutes) and cat['lake_id'] == state.lake_id:
        states.append('cookout')
    states += [f"after_ch{n}" for n in range(5, 0, -1) if chapter_finished(state, n)]
    states.append(f"weather:{calendar.weather_at(state)}")
    standing = friendship(state, content, npc_id)
    if standing:
        states.append(standing)
    states.append('day')
    for key in states:
        if key in lines:
            value = lines[key]
            options = value if isinstance(value, list) else [value]
            return options[_rank('greeting', state.narrative.schedule_seed, npc_id,
                                 game_day(state.game_minutes)) % len(options)]
    return None


def record_hail(state, world, npc) -> bool:
    """Note the meeting and emit the hail event before dialogue starts.

    Returns whether this is the first meeting. A `talk_to` step completes here, so
    the conversation can open on the quest's ready node.
    """
    from . import calendar
    from .kitchen import at_landing
    from .npcs import cast
    from .quests import game_day
    npcs = state.v2.setdefault('npcs', {})
    talk = npcs.get('talk_days')
    if not isinstance(talk, dict):
        talk = npcs['talk_days'] = {}
    days = talk.get(npc.id)
    days = [day for day in days if type(day) is int] if isinstance(days, list) else []
    first = not days
    day = game_day(state.game_minutes)
    if day not in days:
        days.append(day)
    talk[npc.id] = days[-TALK_DAYS_KEPT:]
    state.emit_quest_event({
        'type': 'npc.hail', 'npc_id': npc.id, 'lake_id': world.id, 'game_minute': state.game_minutes,
        'host_of': world.id if cast().hosts.get(world.id) == npc.id else None,
        'event': 'cookout' if calendar.cookout_active(state.game_minutes) else None,
        'at_landing': at_landing(state, world),
    })
    return first


def _node(node_id, npc_id, text, *, quest_id=None, next_id=None, choices=None):
    node = {'id': node_id, 'quest_id': quest_id, 'speaker_id': npc_id, 'text': text}
    if choices is not None:
        node['choices'] = choices
    else:
        node['next'] = next_id
    return node


def _bubble_nodes(nodes, base_id, npc_id, text, *, quest_id=None, next_id=None) -> str:
    """Lay a line's bubbles out as chained nodes; returns the first node's id."""
    bubbles = text if isinstance(text, list) else [text]
    ids = [base_id] + [f'{base_id}:{i}' for i in range(2, len(bubbles) + 1)]
    for i, (node_id, bubble) in enumerate(zip(ids, bubbles)):
        nodes[node_id] = _node(node_id, npc_id, bubble, quest_id=quest_id,
                               next_id=ids[i + 1] if i + 1 < len(ids) else next_id)
    return ids[0]


def _greeting_nodes(nodes, npc_id, text, *, quest_id=None, next_id=None) -> str:
    return _bubble_nodes(nodes, f'{npc_id}:greeting', npc_id, text, quest_id=quest_id, next_id=next_id)


def story_heard(state, npc_id: str) -> int:
    """How many parts of a cat's story the Skipper has heard (V1-33)."""
    stories = state.v2.get('npcs', {}).get('stories')
    row = stories.get(npc_id) if isinstance(stories, dict) else None
    heard = row.get('heard') if isinstance(row, dict) else None
    return heard if type(heard) is int and heard > 0 else 0


def _tell_story(nodes, state, content, npc_id, *, quest_id=None, next_id=None) -> str | None:
    """The next part of a cat's story, one a game day until it is all told (05 §4.3).

    The part counts as heard only when its node is shown (`_hear_story`), so closing the
    conversation on the greeting keeps it for the next hail.
    """
    from .quests import game_day
    parts = content.cats.get(npc_id, {}).get('story') or []
    heard = story_heard(state, npc_id)
    stories = state.v2.get('npcs', {}).get('stories')
    row = stories.get(npc_id) if isinstance(stories, dict) else None
    if heard >= len(parts) or (isinstance(row, dict) and row.get('day') == game_day(state.game_minutes)):
        return None
    first = _bubble_nodes(nodes, f'{npc_id}:story', npc_id, parts[heard], quest_id=quest_id, next_id=next_id)
    nodes[first]['story'] = [npc_id, heard]
    return first


def enter_node(state, node) -> None:
    """A node is on screen: a story part counts as heard, and a scene begins (pending)."""
    _hear_story(state, node)
    if isinstance(node, dict) and node.get('scene_start'):
        from .story import start_scene
        start_scene(state, node['scene_start'])


def _hear_story(state, node) -> None:
    """Record a story part once its first bubble is on screen."""
    from .quests import game_day
    mark = node.get('story') if isinstance(node, dict) else None
    if not mark or story_heard(state, mark[0]) != mark[1]:
        return
    npcs = state.v2.setdefault('npcs', {})
    if not isinstance(npcs.get('stories'), dict):
        npcs['stories'] = {}
    npcs['stories'][mark[0]] = {'heard': mark[1] + 1, 'day': game_day(state.game_minutes)}


def open_conversation(npc, state, content, *, first: bool = False, world=None):
    """What hailing this cat opens, or None when they only wave (V1-31).

    In order: a story scene of theirs (V1-34); Pounce's letter; a host's offer to take
    other cats' finished quests; a giver acknowledging a turn-in their host took; then
    the cat's current quest. A story step comes first, except that the cat's own
    finished errand is handed in before the story's progress line.
    A greeting (05 §4) opens a first meeting before anything else and comes before a
    V1.0 offer. Once the cat's quests are all done, the return line answers the last
    turn-in for the rest of that game day, and the greeting takes over from the next.
    A cat with a story tells its next part after the greeting, one part a game day.
    """
    from .quests import chain as quest_chain, current_quest, game_day, quest_status, story_focus
    from .story import hail_scene, scene_conversation
    scene_id = hail_scene(state, content, npc.id)
    if scene_id is not None:
        return scene_conversation(state, content, scene_id)
    if npc.id == 'pounce':
        letter = next_letter(state, content)
        if letter is None:
            return None
        from .quests import game_day
        letter['delivered_day'] = game_day(state.game_minutes)
        sender = content.cats[letter['from']]
        nodes = {'pounce:letter': _node('pounce:letter', 'pounce', LETTER_LINE.replace('{name}', sender['name']),
                                        next_id='pounce:letter:text'),
                 'pounce:letter:text': _node('pounce:letter:text', 'pounce',
                                             sender['letters'][letter['variant']])}
        return Conversation('pounce', None, 'pounce:letter', nodes=nodes)
    nodes = {}
    chain = content.cats.get(npc.id, {}).get('quests', [])
    # A turn-in the host took is acknowledged at the next meeting with the giver.
    for quest_id in chain:
        progress = state.narrative.quests.get(quest_id)
        quest = content.quests.get(quest_id)
        if (progress is not None and quest is not None and 'dialogue' in quest
                and progress.turned_in_by is not None and not progress.acknowledged):
            progress.acknowledged = True
            return Conversation(npc.id, quest_id, quest['dialogue']['completed'])
    quest_id = story_focus(state, content, npc.id, progress_lines=False)
    if quest_id is None:
        own = current_quest(state, content, npc.id)
        if own is not None and quest_status(state, own) == 'ready':
            quest_id = own  # their own finished errand before the story's reminder (V1-34)
        else:
            quest_id = story_focus(state, content, npc.id) or own
    if quest_id is None and npc.quest_id in content.quests:
        quest_id = npc.quest_id  # a V3 cat outside the roster, as in older tests
    entry = None
    text = greeting(state, content, npc.id, first=first, world=world)
    first_line = first and 'first' in content.cats.get(npc.id, {}).get('greetings', {})
    if quest_id is not None:
        quest = content.quests[quest_id]
        status = quest_status(state, quest_id)
        entry = quest['dialogue'][status]
        progress = state.narrative.quests.get(quest_id)
        finished = progress.completed_game_minute if progress is not None else None
        done = (status == 'completed' and quest_chain(content, npc.id)[-1:] == [quest_id]
                and (finished is None or game_day(finished) < game_day(state.game_minutes)))
        replaced = text is not None and done  # the greeting stands in for the return line
        if quest.get('kind') == 'story' and status == 'ready':
            pass  # a story beat is told whole; the cat's own story waits for the next hail (V1-34)
        else:
            entry = _tell_story(nodes, state, content, npc.id, quest_id=quest_id,
                                next_id=None if replaced else entry) or (None if replaced else entry)
        if text is not None and (first_line or replaced or ('kind' in quest and status == 'available')):
            entry = _greeting_nodes(nodes, npc.id, text, quest_id=quest_id, next_id=entry)
    else:
        entry = _tell_story(nodes, state, content, npc.id)
        if text is not None:
            entry = _greeting_nodes(nodes, npc.id, text, next_id=entry)
    ready = host_turn_ins(state, content, npc.id)
    if ready:
        choices = [{'id': f'{npc.id}:hand_in:{qid}', 'quest_id': qid, 'action': 'turn_in_at_host',
                    'text': f"Hand in {content.quests[qid]['title']}.", 'target': f'{npc.id}:handed_in'}
                   for qid in ready]
        choices.append({'id': f'{npc.id}:hand_in:later', 'action': 'close', 'text': "Not today.",
                        'target': entry})
        nodes[f'{npc.id}:hand_in'] = _node(f'{npc.id}:hand_in', npc.id, HOST_TURN_IN_LINE, choices=choices)
        nodes[f'{npc.id}:handed_in'] = _node(f'{npc.id}:handed_in', npc.id, HOST_HANDED_IN_LINE, next_id=entry)
        return Conversation(npc.id, quest_id, f'{npc.id}:hand_in', nodes=nodes)
    if entry is None:
        return None
    _hear_story(state, nodes.get(entry))
    return Conversation(npc.id, quest_id, entry, nodes=nodes)


@dataclass
class Conversation:
    npc_id: str
    quest_id: str | None
    node_id: str
    selected: int = 0
    # Runtime nodes (greetings, host turn-ins, letters, scenes) laid over the authored graph.
    nodes: dict = field(default_factory=dict)
    # Set when a story scene is done, so the session saves its effects at once (06 §3.3).
    finished_scene: bool = False

    def in_scene(self, content) -> bool:
        """A story scene is on screen; it can't be left half-read (V1-34)."""
        return bool(self.node(content).get('scene'))

    @classmethod
    def start(cls, npc, state, content):
        status = state.narrative.quests[npc.quest_id].status
        node = content.quests[npc.quest_id]['dialogue'][status]
        return cls(npc.id, npc.quest_id, node)

    def node(self, content) -> dict:
        return self.nodes.get(self.node_id) or content.dialogue[self.node_id]

    def advance(self, state, content):
        from .quests import accept_quest, count_todays_hail
        node = self.node(content)
        if 'choices' in node:
            choice = node['choices'][self.selected % len(node['choices'])]
            action = choice['action']
            if action == 'accept':
                if accept_quest(state, content, self.quest_id):
                    count_todays_hail(state, content, self.quest_id, self.npc_id)
            elif action == 'decline':
                progress = state.narrative.quest(self.quest_id) if self.quest_id else None
                if progress is not None and progress.status == 'available':
                    progress.declined = True
            elif action == 'turn_in':
                if not _turn_in_reward(state, content, self.quest_id, self.npc_id):
                    return False
            elif action == 'turn_in_at_host':
                if not turn_in_at_host(state, content, choice['quest_id'], self.npc_id):
                    return False
            elif action == 'scene' and choice.get('knot'):
                from .botidentity import choose_knot
                choose_knot(state, choice['knot'], toast=False)  # the scene says it (05 §2.4)
            target = choice['target']
        else:
            target = node['next']
        if node.get('scene_end'):
            from .story import finish_scene
            if finish_scene(state, content, node['scene_end']):
                self.finished_scene = True
        if target is None:
            return False
        self.node_id = target
        entered = self.node(content)
        self.quest_id = entered.get('quest_id') or self.quest_id
        if entered.get('scene'):
            self.npc_id = entered['speaker_id']  # a chained scene speaks in its own voice (V1-34)
        self.selected = 0
        enter_node(state, entered)
        return True
