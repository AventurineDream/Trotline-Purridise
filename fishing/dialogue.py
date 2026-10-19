"""Contextual hailing and traversal of the validated authored dialogue graph."""

from dataclasses import dataclass
import math

from .narrative import RIPPLE_BY_QUEST

HAIL_RANGE_M = 20.0
# Boat speed is metres/second; one knot is exactly 1852 metres/hour.
HAIL_SPEED_MPS = 3.0 * 1852 / 3600


def nearby_npc(state):
    if abs(state.speed) >= HAIL_SPEED_MPS:
        return None
    eligible = [(math.hypot(state.x - n.anchor.x, state.z - n.anchor.z), n.id, n)
                for n in state.npcs if n.anchor.lake_id == state.lake_id]
    eligible = [row for row in eligible if row[0] <= HAIL_RANGE_M]
    return min(eligible, default=(0, '', None))[-1]


def _turn_in_reward(state, content, quest_id: str, npc_id: str) -> bool:
    """Pay one contract-supported reward to its present giver, at most once."""
    quest = content.quests.get(quest_id)
    giver = content.npcs.get(npc_id)
    progress = state.narrative.quests.get(quest_id)
    if (quest is None or giver is None or progress is None
            or quest.get('giver_id') != npc_id
            or giver.get('quest_id') != quest_id
            or progress.status != 'ready'):
        return False

    current = nearby_npc(state)
    if current is None or current.id != npc_id:
        state.toast(f"Come back to {giver['name']} when nearby to turn in.")
        return False

    reward_id = quest.get('reward_id')
    reward = content.rewards.get(reward_id)
    ripple_id = RIPPLE_BY_QUEST.get(quest_id)
    if (not isinstance(reward, dict)
            or set(reward) != {'id', 'cash', 'ripple_id'}
            or reward.get('id') != reward_id
            or type(reward.get('cash')) is not int
            or reward['cash'] <= 0
            or reward.get('ripple_id') != ripple_id):
        # Content validation rejects unsupported reward payloads before play.
        return False

    if not state.narrative.record_reward_claim(quest_id):
        return False
    # Quest cash adds to the purse, but is not fish-sale income (which drives
    # the first-sale tutorial). The livewell is intentionally left untouched.
    state.money = round(state.money + reward['cash'], 2)
    if ripple_id is not None and ripple_id not in state.narrative.ripples:
        state.narrative.ripples.append(ripple_id)
    return True


@dataclass
class Conversation:
    npc_id: str
    quest_id: str
    node_id: str
    selected: int = 0

    @classmethod
    def start(cls, npc, state, content):
        status = state.narrative.quests[npc.quest_id].status
        node = content.quests[npc.quest_id]['dialogue'][status]
        return cls(npc.id, npc.quest_id, node)

    def advance(self, state, content):
        node = content.dialogue[self.node_id]
        if 'choices' in node:
            choice = node['choices'][self.selected % len(node['choices'])]
            progress = state.narrative.quests[self.quest_id]
            action = choice['action']
            if action == 'accept' and progress.status == 'available':
                progress.status = 'active'
                progress.accepted_game_minute = state.game_minutes
                progress.declined = False
            elif action == 'decline' and progress.status == 'available':
                progress.declined = True
            elif action == 'turn_in':
                if not _turn_in_reward(state, content, self.quest_id, self.npc_id):
                    return False
            target = choice['target']
        else:
            target = node['next']
        if target is None:
            return False
        self.node_id = target
        self.selected = 0
        return True
