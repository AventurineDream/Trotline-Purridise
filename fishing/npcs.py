"""Active-lake NPC presence from the saved, game-time schedule (02 §11.3, V1-30).

Hosts stay at their landing. Each game day (06:00 to 06:00) a lake shows three
*day* encounters, 06:00–20:00, and one *night* encounter, 20:00–04:00. They are
read from a seeded permutation of the lake's encounters walked round-robin, so
every encounter appears at least once in any three consecutive days.

Presence is a pure function of the save seed, the lake and the day, and of the
quests that pin a cat. It never consumes RNG or evaluates quest progress, and it
doesn't depend on the computer clock or on which lake is loaded.

Postmaster Pounce visits one unlocked lake a day, 08:00–16:00. Tinker Thistle
moors at the player's lake every Saturday, 10:00–18:00. The Sunday cookout
gathers a lake's whole cast on its landing piers.
"""

from dataclasses import dataclass
from functools import lru_cache
import hashlib
from types import MappingProxyType

from .anchors import Anchor
from .data import hour_of_day
from . import calendar
from .narrative import DAY_NPCS

DAY_ENCOUNTERS = 3
DAY_HOURS = (6.0, 20.0)
NIGHT_HOURS = (20.0, 4.0)
POUNCE_HOURS = (8.0, 16.0)
THISTLE_HOURS = (10.0, 18.0)
SATURDAY = 5  # day 0 is Monday (02 §5)
TRAVELER_MOORINGS = {"pounce": "mail_mooring", "thistle": "tinker_mooring"}


@dataclass(frozen=True)
class NPC:
    id: str
    name: str
    quest_id: str | None  # the V3 quest this cat gives in dialogue, if any
    anchor: Anchor
    permanent: bool


@dataclass(frozen=True)
class Cast:
    """The roster's schedule: names, hosts, and each lake's day and night pools."""
    names: MappingProxyType
    anchors: MappingProxyType
    hosts: MappingProxyType   # lake -> host id
    day: MappingProxyType     # lake -> day encounter ids, in roster order
    night: MappingProxyType   # lake -> night encounter ids
    lakes: tuple              # lakes with a cast, in roster order


@lru_cache(maxsize=1)
def cast() -> Cast:
    from .content import load_content_v2
    hosts, day, night, names, anchors = {}, {}, {}, {}, {}
    for npc_id, row in load_content_v2().roster.items():
        names[npc_id] = row["name"]
        anchors[npc_id] = row["anchor"]
        if row["role"] == "host":
            hosts[row["lake"]] = npc_id
        elif row["role"] == "water":
            (day if row["slot"] == "day" else night).setdefault(row["lake"], []).append(npc_id)
    freeze = lambda pools: MappingProxyType({lake: tuple(ids) for lake, ids in pools.items()})
    return Cast(MappingProxyType(names), MappingProxyType(anchors), MappingProxyType(hosts), freeze(day),
                freeze(night), tuple(hosts))


def _rank(*parts) -> int:
    """A domain-separated, platform-independent draw from the schedule seed."""
    digest = hashlib.sha256(":".join(str(part) for part in parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


@lru_cache(maxsize=64)
def _permutation(seed, lake, slot, pool):
    return tuple(sorted(pool, key=lambda npc_id: (_rank("schedule", seed, lake, slot, npc_id), npc_id)))


def day_encounters(seed: int, lake: str, day: int) -> tuple:
    """The three day encounters: the next three in the lake's seeded round-robin."""
    pool = _permutation(seed, lake, "day", cast().day.get(lake, ()))
    if len(pool) <= DAY_ENCOUNTERS:
        return pool
    return tuple(pool[(DAY_ENCOUNTERS * day + k) % len(pool)] for k in range(DAY_ENCOUNTERS))


def night_encounter(seed: int, lake: str, day: int) -> str | None:
    """The night's encounter. Briar's pool is Master Cinder alone (the V3 night rule)."""
    pool = _permutation(seed, lake, "night", cast().night.get(lake, ()))
    return pool[day % len(pool)] if pool else None


def pounce_lake(state, day: int) -> str | None:
    """The one unlocked lake Postmaster Pounce visits that day."""
    from .lakes import travel_unlocked
    lakes = [lake for lake in cast().lakes if travel_unlocked(state, lake)]
    return lakes[_rank("pounce", state.narrative.schedule_seed, day) % len(lakes)] if lakes else None


def pinned(state, content) -> frozenset:
    """Cats an accepted quest needs present.

    These are a `talk_to` cat in an active quest's objective or steps, and the giver
    of a quest waiting to be turned in, which needs its giver present.
    The story's chapter steps arrive later and add their `talk_to` cats here.
    """
    pins = set()
    for quest_id, progress in state.narrative.quests.items():
        quest = content.quests.get(quest_id)
        if quest is None:
            continue
        if progress.status == "ready":
            pins.add(quest.get("giver_id"))
        elif progress.status == "active":
            objective = quest.get("objective")
            steps = objective if isinstance(objective, list) else [objective]
            if "kind" in quest:
                # A V1.0 quest's steps run in order; only the current one needs its cat.
                index = progress.progress.get("step", 0)
                steps = steps[index:index + 1] if type(index) is int and index >= 0 else []
            for step in steps:
                if isinstance(step, dict) and step.get("type") == "talk_to":
                    pins.add(step.get("npc_id"))
    return frozenset(pin for pin in pins if isinstance(pin, str) and pin in cast().names)


def legacy_day_cat(state, lake: str, day: int) -> str | None:
    """A V3 save's chosen day cat, kept for the rest of the day it was saved on."""
    ledger = state.narrative
    if ledger.schedule_day_by_lake.get(lake) == day:
        npc_id = ledger.day_npc_by_lake.get(lake)
        if npc_id in DAY_NPCS.get(lake, ()):
            return npc_id
    return None


def _band(hour: float, hours) -> bool:
    return calendar.in_hours(hour, *hours)


def schedule_key(state, world, content=None):
    """Everything presence depends on: when it changes, the cast is rebuilt."""
    day = max(0, int(state.game_minutes // 1440))
    hour = hour_of_day(state.game_minutes)
    pins = pinned(state, content) if content is not None else frozenset()
    return (world.id, state.narrative.schedule_seed, day, _band(hour, DAY_HOURS), _band(hour, NIGHT_HOURS),
            calendar.cookout_active(state.game_minutes), pins, legacy_day_cat(state, world.id, day),
            _band(hour, POUNCE_HOURS) and pounce_lake(state, day) == world.id,
            calendar.weekday(state.game_minutes) == SATURDAY and _band(hour, THISTLE_HOURS))


def present_ids(state, world, content) -> tuple:
    """Who is on the loaded lake now, host first, then encounters, pins and travelers."""
    lake = world.id
    roster = cast()
    if lake not in roster.hosts or not world.anchors:
        # A flat placeholder map has no charted anchors. Never borrow another lake's cast.
        return ()
    _lake, seed, day, daytime, nighttime, cookout, pins, legacy, pounce, thistle = schedule_key(state, world,
                                                                                               content)
    host = roster.hosts[lake]
    if cookout:
        return (host, *roster.day.get(lake, ()), *roster.night.get(lake, ()))
    ids = [host]
    if daytime:
        ids += day_encounters(seed, lake, day)
        extra = [legacy] if legacy else []
        extra += sorted(pin for pin in pins if pin in roster.day.get(lake, ()))
    elif nighttime:
        tonight = night_encounter(seed, lake, day)
        ids += [tonight] if tonight else []
        extra = sorted(pin for pin in pins if pin in roster.night.get(lake, ()))
    else:
        extra = []
    # A pinned cat takes an extra slot only when the day hasn't already brought them.
    ids += [npc_id for npc_id in extra if npc_id not in ids]
    if pounce:
        ids.append("pounce")
    if thistle:
        ids.append("thistle")
    return tuple(ids)


def _cookout_anchor(world, host_anchor, npc_id, index):
    """Cookout guests along the landing's two piers, alternating sides, nearest first."""
    from dataclasses import replace
    slip = world.slip
    side = 1 if index % 2 else -1
    along = 0.5 + 2.2 * (index // 2)
    x, z = slip.world(along, side * (slip.half_w + 0.85))
    return replace(host_anchor, id=world.id + ":cookout:" + npc_id, x=float(x), z=float(z), kind="dock",
                   approach=None)


def active_npcs(state, world, content):
    """The loaded lake's present cats as NPCs; `content` is the narrative content."""
    roster = cast()
    ids = present_ids(state, world, content)
    cookout = calendar.cookout_active(state.game_minutes)
    actors = []
    for index, npc_id in enumerate(ids):
        if npc_id in TRAVELER_MOORINGS:
            anchor = world.anchors[world.id + ":" + TRAVELER_MOORINGS[npc_id]]
        else:
            anchor = world.anchors[roster.anchors[npc_id]]
        if cookout:
            # Dock actors have no watercraft collider; each guest stands on a pier at the landing.
            anchor = _cookout_anchor(world, world.anchors[roster.anchors[roster.hosts[world.id]]], npc_id, index)
        row = content.npcs.get(npc_id)
        actors.append(NPC(npc_id, roster.names[npc_id], row["quest_id"] if row else None, anchor,
                          npc_id == roster.hosts[world.id]))
    return tuple(actors)


def next_appearance(state, content, npc_id: str) -> str:
    """When the schedule next guarantees this cat is out, for the journal (02 §12.2 rule 4)."""
    from .lakes import LAKES
    roster = cast()
    lake = next((lake for lake, host in roster.hosts.items() if host == npc_id), None)
    name = roster.names.get(npc_id, npc_id)
    if lake is not None:
        return f"{name} is always at {LAKES[lake]['landing']}."
    today = max(0, int(state.game_minutes // 1440))
    hour = hour_of_day(state.game_minutes)
    if npc_id in TRAVELER_MOORINGS:
        # Travelers are never pinned: Pounce visits one lake a day and Thistle comes on Saturdays.
        here = state.lake_id
        for ahead in range(15):
            day = today + ahead
            when = "today" if ahead == 0 else "tomorrow" if ahead == 1 else f"in {ahead} days"
            if npc_id == "pounce" and pounce_lake(state, day) == here and (ahead or _band(hour, (6.0, 16.0))):
                return f"{name} visits {LAKES[here]['name']} {when}, 08:00–16:00."
            if (npc_id == "thistle" and calendar.weekday(day * 1440) == SATURDAY
                    and (ahead or _band(hour, (6.0, 18.0)))):
                return f"{name} moors at your lake {when}, 10:00–18:00."
        return f"{name} travels; watch for their boat."
    lake = next((lake for lake, pool in roster.day.items() if npc_id in pool), None)
    night_lake = next((lake for lake, pool in roster.night.items() if npc_id in pool), None)
    if npc_id in pinned(state, content):
        return f"{name} waits on {LAKES[lake or night_lake]['name']} every day until then."
    seed = state.narrative.schedule_seed
    for ahead in range(len(roster.day.get(lake, ())) + len(roster.night.get(night_lake, ())) + 2):
        day = today + ahead
        when = "today" if ahead == 0 else "tomorrow" if ahead == 1 else f"in {ahead} days"
        # Today's band counts only while it is still to come or under way.
        if (lake is not None and npc_id in day_encounters(seed, lake, day)
                and (ahead or _band(hour, DAY_HOURS))):
            return f"{name} is out on {LAKES[lake]['name']} {when}, 06:00–20:00."
        if (night_lake is not None and night_encounter(seed, night_lake, day) == npc_id
                and (ahead or not 4.0 <= hour < 6.0)):
            return f"{name} is out on {LAKES[night_lake]['name']} {when}, 20:00–04:00."
    return f"{name} will be out again soon."
