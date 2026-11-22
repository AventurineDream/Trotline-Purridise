"""Persistent deckhand identity, earned shells, purchases and the collar arc.

Story rewards call the explicit grant/advance helpers. Loading reconciles known
completed chapters without replaying dialogue, charging money or choosing a knot.
Shell models/chimes and individual tool effects live in their own game layers.
"""
from __future__ import annotations

import hashlib
import re
from copy import deepcopy

from .data import (BOT_COLLAR_STAGES, BOT_KNOTS, BOT_PREFIXES, BOT_SHELLS,
                   BOT_SUFFIX_MAX, BOT_SUFFIX_MIN, BOT_TOOLS)


def generated_name(schedule_seed):
    """Two private RNG draws; never advance fishing or NPC scheduling."""
    from .sim import RNG
    seed = schedule_seed if type(schedule_seed) is int else 0
    digest = hashlib.sha256(f'bot-name:v1:{seed}'.encode()).digest()
    rng = RNG(int.from_bytes(digest[:8], 'big'))
    prefix = BOT_PREFIXES[int(rng.u01() * len(BOT_PREFIXES))]
    number = BOT_SUFFIX_MIN + int(rng.u01() * (BOT_SUFFIX_MAX - BOT_SUFFIX_MIN + 1))
    return f'{prefix}-{number:03d}'


def _valid_name(value):
    # Retain an already assigned name, including a future prefix; the generator
    # alone owns the current twelve-prefix roster. Repair the old Copper-000.
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9]*-[0-9]{3}', value):
        return False
    return BOT_SUFFIX_MIN <= int(value.rsplit('-', 1)[1]) <= BOT_SUFFIX_MAX


def default_profile(schedule_seed=0):
    return {'bot_name': generated_name(schedule_seed), 'shell': 'tin', 'shells': ['tin'],
            'tools': [], 'collar': {'stage': 'none', 'knot': None, 'visible': True}}


def _ids(value):
    return list(dict.fromkeys(x for x in value if isinstance(x, str) and x)) if isinstance(value, list) else []


def completed_chapters(story):
    if not isinstance(story, dict):
        return set()
    raw = story.get('completed_chapters', [])
    done = {x for x in raw if type(x) is int and 1 <= x <= 5} if isinstance(raw, list) else set()
    # Existing kitchen/story convention: chapter N means earlier chapters ended.
    chapter = story.get('chapter', 0)
    if type(chapter) is int and chapter > 0:
        done.update(range(1, min(chapter, 6)))
    return done


def _advance_collar(collar, stage):
    stages = tuple(BOT_COLLAR_STAGES)
    current = collar.get('stage', 'none')
    if current in stages and stages.index(stage) > stages.index(current):
        collar['stage'] = stage
        return True
    return False


def _scene_seen(story, *ids):
    if not isinstance(story, dict):
        return False
    scenes, states = story.get('scenes_seen', []), story.get('scene_states', {})
    return (isinstance(scenes, list) and any(key in scenes for key in ids)
            or isinstance(states, dict) and any(states.get(key) in ('done', 'skipped') for key in ids))


def normalize_profile(v2, schedule_seed=0):
    """Repair known fields, keeping future IDs/fields and all valid progress."""
    profile = v2.get('profile')
    if not isinstance(profile, dict):
        profile = v2['profile'] = default_profile(schedule_seed)
    if not _valid_name(profile.get('bot_name')):
        profile['bot_name'] = generated_name(schedule_seed)
    profile['shells'] = _ids(profile.get('shells'))
    if 'tin' not in profile['shells']:
        profile['shells'].insert(0, 'tin')
    profile['tools'] = _ids(profile.get('tools'))
    shell = profile.get('shell')
    if not isinstance(shell, str) or not shell or (shell in BOT_SHELLS and shell not in profile['shells']):
        profile['shell'] = 'tin'
    collar = profile.get('collar')
    if not isinstance(collar, dict):
        collar = profile['collar'] = {'stage': 'none', 'knot': None, 'visible': True}
    if not isinstance(collar.get('stage'), str) or not collar['stage']:
        collar['stage'] = 'none'
    knot = collar.get('knot')
    if knot is not None and (not isinstance(knot, str) or not knot):
        collar['knot'] = None
    else:
        collar.setdefault('knot', None)
    if type(collar.get('visible')) is not bool:
        collar['visible'] = True
    if collar['knot'] is not None:
        _advance_collar(collar, 'retied')
    done = completed_chapters(v2.get('story'))
    for row in BOT_SHELLS.values():
        if row.chapter in done and row.id not in profile['shells']:
            profile['shells'].append(row.id)
    if 1 in done:
        _advance_collar(collar, 'received')
    if 3 in done:
        _advance_collar(collar, 'loose')
    story = v2.get('story', {})
    if _scene_seen(story, 'ending', 'end_03') and collar.get('knot') is not None:
        _advance_collar(collar, 'favorite')
    return profile


def profile(state):
    value = state.v2.get('profile', {})
    return value if isinstance(value, dict) else {}


def sync_story_rewards(state):
    """Call after a live chapter reward; loading also uses this reconciliation."""
    before = deepcopy(profile(state))
    normalize_profile(state.v2, state.narrative.schedule_seed)
    return profile(state) != before


def book_credit(state):
    story = state.v2.get('story', {})
    ending = _scene_seen(story, 'ending', 'end_02', 'end_03')
    return 'the Skipper' + (' & ' if ending else ' · with ') + name(state)


def name(state):
    value = profile(state).get('bot_name')
    return value if _valid_name(value) else generated_name(state.narrative.schedule_seed)


def format_text(text, state):
    """Only known literal placeholders; braces in ordinary text stay literal.

    `{Skipper}` is the player's chosen name (skipperlook), "Skipper" until they pick one.
    """
    from .skipperlook import name as skipper_name
    return str(text).replace('{BotName}', name(state)).replace('{Skipper}', skipper_name(state))


def grant_shell(state, shell_id):
    """Story reward hook. Never auto-equip or replace notes, collar or tools."""
    if not isinstance(shell_id, str) or shell_id not in BOT_SHELLS:
        return False
    owned = profile(state)['shells']
    if shell_id in owned:
        return False
    owned.append(shell_id)
    return True


def grant_tool(state, tool_id):
    """Explicit free story reward (e.g. chapter-one Reed Anchor), without a sale."""
    if not isinstance(tool_id, str) or tool_id not in BOT_TOOLS or tool_id in profile(state)['tools']:
        return False
    profile(state)['tools'].append(tool_id)
    return True


def advance_collar(state, stage):
    """Story hook for receiving the wool, mountain wind and the ending."""
    collar = profile(state)['collar']
    if stage == 'received' and collar.get('stage') == 'none':
        return _advance_collar(collar, stage)
    if stage == 'loose' and collar.get('stage') == 'received':
        return _advance_collar(collar, stage)
    if stage == 'favorite' and collar.get('stage') == 'retied' and collar.get('knot'):
        return _advance_collar(collar, stage)
    return False


def knot_available(state):
    story = state.v2.get('story', {})
    chapter = story.get('chapter', 0) if isinstance(story, dict) else 0
    states = story.get('scene_states', {}) if isinstance(story, dict) else {}
    scene = states.get('story_c4_knot') if isinstance(states, dict) else None
    # The marker scene is pending while it plays (V1-34); older builds wrote ready/active.
    ready = ((type(chapter) is int and chapter >= 4) or 4 in completed_chapters(story)) and scene in (
        'pending', 'ready', 'active', 'done', 'skipped')
    return ready and profile(state)['collar'].get('stage') == 'loose'


def choose_knot(state, knot_id, *, toast=True):
    """Shared by the landing menu and the authored marker scene, which says its own line."""
    if not isinstance(knot_id, str) or knot_id not in BOT_KNOTS:
        return 'Choose a known collar knot.'
    collar = profile(state)['collar']
    if collar.get('knot') == knot_id:
        return None
    if not knot_available(state) or collar.get('knot') is not None:
        return 'Bot chooses his adjustable knot during chapter 4.'
    collar['knot'], collar['stage'] = knot_id, 'retied'
    if toast:
        state.toast(name(state) + ': This one. It adjusts.')
    return None


def at_landing(state, world):
    return state.lake_id == world.id and state.slip_status(world) == 'docked' and abs(state.speed) < .45


def swap_shell(state, world, shell_id):
    if not at_landing(state, world):
        return 'Swap shells at a landing while stopped.'
    if not isinstance(shell_id, str) or shell_id not in BOT_SHELLS or shell_id not in profile(state)['shells']:
        return 'Earn that shell by finishing its chapter first.'
    # Returning him to the bow during an excursion would lose scouting progress.
    # The shell is cosmetic: leave position, target, report and reaction latches alone.
    profile(state)['shell'] = shell_id
    return None


def tool_error(state, world, tool_id):
    tool = BOT_TOOLS.get(tool_id) if isinstance(tool_id, str) else None
    if tool is None:
        return 'Choose a known Bot tool.'
    if not at_landing(state, world):
        return 'Buy Bot tools at a landing while stopped.'
    if tool_id in profile(state)['tools']:
        return 'That tool is already aboard.'
    shell = next(row for row in BOT_SHELLS.values() if row.tool_id == tool_id)
    if shell.id not in profile(state)['shells']:
        return 'Earn ' + shell.name + ' first.'
    if tool.requires_finder and not state.finder:
        return 'Sonar Grid needs the Depth Finder from Gear.'
    if state.money < tool.price:
        return 'Not enough cash.'
    return None


def buy_tool(state, world, tool_id):
    error = tool_error(state, world, tool_id)
    if error:
        return error
    state._spend(BOT_TOOLS[tool_id].price)
    profile(state)['tools'].append(tool_id)
    return None


def rows(state, world):
    """Read-only landing menu; all mutations happen through explicit actions."""
    from .kitchen import MenuRow
    result = []
    saved = profile(state)
    landing = at_landing(state, world)
    for shell in BOT_SHELLS.values():
        earned = shell.id in saved['shells']
        wearing = saved.get('shell') == shell.id
        right = 'Wearing' if wearing else 'Swap free' if earned else f'Chapter {shell.chapter}'
        result.append(MenuRow(shell.name, right, 'Changing shells keeps his name, notes, collar, tools and scouting progress.',
                              landing and earned and not wearing, 'bot_shell', shell.id))
    for tool in BOT_TOOLS.values():
        owned = tool.id in saved['tools']
        error = tool_error(state, world, tool.id)
        result.append(MenuRow(tool.name, 'Owned' if owned else f'${tool.price}',
                              error or 'Owned tools stay with Bot in every shell.', error is None, 'bot_tool', tool.id))
    collar = saved['collar']
    for knot_id, label in BOT_KNOTS.items():
        chosen = collar.get('knot') == knot_id
        result.append(MenuRow(label, 'Chosen' if chosen else 'Knot',
                              'A cosmetic choice, saved with his collar. Bot chooses during chapter 4.',
                              landing and knot_available(state), 'bot_knot', knot_id))
    return result
