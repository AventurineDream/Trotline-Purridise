"""Active-lake NPC presence from the contract's saved, game-time schedule."""

from dataclasses import dataclass

from .anchors import Anchor
from .data import hour_of_day
from .narrative import DAY_NPCS

HOSTS = {"briar": "grandmother_whiskers", "cedar": "doc_barnaby"}


@dataclass(frozen=True)
class NPC:
    id: str
    name: str
    quest_id: str
    anchor: Anchor
    permanent: bool


def schedule_key(state, world):
    day = max(0, int(state.game_minutes // 1440))
    hour = hour_of_day(state.game_minutes)
    night = world.id == "briar" and (hour >= 20 or hour < 4)
    return world.id, state.narrative.schedule_seed, day, night


def active_npcs(state, world, content):
    """Select only the loaded lake; never consume RNG or evaluate quest progress.

    Persist the daytime selection even during Cinder's night shift. Skipped
    intervals are computed directly on return, without replaying offscreen days.
    """
    lake, seed, day, night = schedule_key(state, world)
    pool = DAY_NPCS[lake]
    ledger = state.narrative
    selected = pool[(seed + day) % len(pool)]
    # Repair missing/stale choices from the deterministic saved seed and day.
    ledger.day_npc_by_lake[lake] = selected
    ledger.schedule_day_by_lake[lake] = day
    rotating = "master_cinder" if night else selected
    actors = []
    for npc_id in (HOSTS[lake], rotating):
        row = content.npcs[npc_id]
        actors.append(NPC(npc_id, row['name'], row['quest_id'],
                          world.anchors[row['anchor_id']], npc_id == HOSTS[lake]))
    return tuple(actors)
