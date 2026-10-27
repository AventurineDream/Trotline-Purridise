"""Active-lake NPC presence from the contract's saved, game-time schedule."""

from dataclasses import dataclass, replace

from .anchors import Anchor
from .data import hour_of_day
from . import calendar
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
    return world.id, state.narrative.schedule_seed, day, night, calendar.cookout_active(state.game_minutes)


def active_npcs(state, world, content):
    """Select only the loaded lake; never consume RNG or evaluate quest progress.

    Persist the daytime selection even during Cinder's night shift. Skipped
    intervals are computed directly on return, without replaying offscreen days.
    """
    lake, seed, day, night, cookout = schedule_key(state, world)
    if lake not in DAY_NPCS or lake not in HOSTS:
        # Flat systems maps have no authored cast yet. Do not borrow Briar's.
        return ()
    pool = DAY_NPCS[lake]
    ledger = state.narrative
    selected = pool[(seed + day) % len(pool)]
    # Repair missing/stale choices from the deterministic saved seed and day.
    ledger.day_npc_by_lake[lake] = selected
    ledger.schedule_day_by_lake[lake] = day
    rotating = "master_cinder" if night else selected
    actors = []
    ids = tuple(row["id"] for row in calendar.cookout_friends(content, lake)) if cookout else (HOSTS[lake], rotating)
    landing = world.anchors[content.npcs[HOSTS[lake]]["anchor_id"]]
    for index, npc_id in enumerate(ids):
        row = content.npcs[npc_id]
        anchor = world.anchors[row['anchor_id']]
        if cookout:
            # Dock actors have no watercraft collider; spread friends along the landing.
            anchor = replace(landing, id=lake + ':cookout:' + npc_id,
                             x=landing.x + world.slip.sx * (index - (len(ids)-1)/2) * 2.0,
                             z=landing.z + world.slip.sz * (index - (len(ids)-1)/2) * 2.0,
                             kind='dock')
        actors.append(NPC(npc_id, row['name'], row['quest_id'], anchor, npc_id == HOSTS[lake]))
    return tuple(actors)
