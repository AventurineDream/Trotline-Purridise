"""Boat, trotlines, bites, and the bait-shop ledger.

Time: one real second is one game minute at 1x, and a new game starts at dawn.
Lines keep fishing while the game is closed, for up to 72 real hours in Cozy and 36
in Old Salt (the loaded save's mode; `comfort.offline_soak_seconds`). That cap only
ends the replay. Spoilage is its own rule: a hooked fish gets away after
`SPOIL_HOURS` game hours, and a hook only holds one fish, so a long absence is one
soak rather than a jackpot.
"""

from __future__ import annotations

import json
import math
import time
from copy import deepcopy
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, ClassVar
from uuid import uuid4

from .reading import READ_MAX_SECONDS, reading_seconds
from .data import (
    BAIT_BY_ID,
    BOX_PRICE,
    BOXES,
    DOZEN,
    FINDER_PRICE,
    LIGHT_PRICE,
    LINE_TIERS,
    MOTORS,
    PAINT,
    SPECIES,
    SPECIES_BY_ID,
    LAKE_RATE_MULTIPLIERS,
    SPOIL_HOURS,
    WELL_PRICE,
    WELLS,
    band_of,
    clock_string,
    dollars,
    fish_value,
    hour_of_day,
    line_length,
    piece_price,
    quality_of,
    bait_mult,
    zone_mult,
    time_mult,
    weather_mult,
    depth_mult,
)
from .world import World
from .boat import (
    BOATS, COAST_RATE, FUEL_PRICE, THROTTLE_RATE, REVERSE_LIMIT, sailing_speed,
    ROWBOAT_ROW_SPEED, ROWBOAT_ELECTRIC_SPEED, ROWBOAT_MOTOR_POWER_KW,
    ROWBOAT_BATTERY_KWH, ROWBOAT_MOTOR_PRICE, ELECTRICITY_PRICE,
    BATTERY_CHARGE_KWH,
)
from .weather import wind_at
from . import calendar
from .calendar import weather_at
from .lakes import LAKES, place_contains, waypoints as lake_waypoints
from .data import weight_string
from .narrative import NarrativeState, deployment_id
from .book import (LEGENDARY_IDS, SHINY_VALUE_MULTIPLIER, confirm_shiny, lose_shiny,
                   promote_title,
                   record_legendary_catch, record_observation,
                   refresh_collection_title, roll_shiny, set_shiny_target,
                   shiny_tracker, stage_up_events)
from .savepaths import (UnsupportedSaveVersionError, V2_REWARD_KINDS,
                        merge_v2_defaults)
# bot.py imports sim only inside its functions. Keep it that way: a top-level sim import
# there would break `import fishing.sim` on a partly loaded module.
from . import bot
from . import comfort
from . import bottools
from . import fleet

MASK = (1 << 64) - 1
SAVE_VERSION = 2
# Dense reed beds (`reeds` zones) slow every boat to a crawl. Lines still need
# the Reed Anchor there; see State.try_set.
REEDS_CRAWL_SPEED = 0.6  # m/s
# Issue #155: Bot gameplay toasts hold this much longer than other notices.
BOT_TOAST_BONUS = 3.0
# Issue #153: ignited idle burn, as a fraction of full-throttle fuel_burn.
IDLE_FUEL_FRACTION = 0.04
# Flathead snow-mist chop slows every hull except an ice_hull (02 §9).
SNOW_MIST_CHOP = 0.8
# The reed dugout may set lines in reeds without the Reed Anchor (03 §6).
REED_LINE_BOATS = frozenset({"reed_dugout"})

_SAVE_FIELDS = frozenset({
    "version", "lake_id", "boat_id", "owned_boats", "fuel_tanks",
    "rowboat_trolling_motor", "rowboat_battery_kwh",
    "rowboat_charge_kwh_this_visit", "seed", "game_minutes", "money",
    "earned", "spent", "bait", "held", "lines", "well", "x", "z",
    "yaw", "anchored", "engine_on", "motor", "well_tier", "box_tier", "finder",
    "light", "owned", "look", "journal", "narrative_v1", "tutorial",
    "traveled", "time_scale", "muted", "preferred_bait", "hooked_total",
    "stamp", "bot", "v2",
})
_BOT_FIELDS = frozenset({"phase", "x", "z", "yaw", "tx", "tz",
                         "target_line_id"})


class RNG:
    def __init__(self, seed: int):
        self.s = int(seed) & MASK or 0x9E3779B97F4A7C15

    def u01(self) -> float:
        self.s = (self.s + 0x9E3779B97F4A7C15) & MASK
        z = self.s
        z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9 & MASK
        z = (z ^ (z >> 27)) * 0x94D049BB133111EB & MASK
        z = z ^ (z >> 31)
        return (z & ((1 << 53) - 1)) / float(1 << 53)

    def chance(self, p: float) -> bool:
        return self.u01() < p

    def pick(self, weights: dict[str, float]) -> str:
        total = sum(weights.values())
        r = self.u01() * total
        acc = 0.0
        last = ""
        for key, w in weights.items():
            last = key
            acc += w
            if r <= acc:
                return key
        return last


@dataclass
class Catch:
    species: str
    weight: float
    quality: float
    age: float
    zone: str
    bait: str
    hour: float
    lake_id: str = "briar"
    noted_tired: bool = False
    catch_game_minute: float | None = None
    extra_fields: dict = field(default_factory=dict, repr=False)
    shiny: bool = False
    treasured: bool | None = None
    legendary: bool = False
    disposition: str = "pending"
    haul_seen: bool = False
    depth_m: float | None = None
    shiny_since_before: int | None = None
    shiny_observation: int | None = None

    def __post_init__(self):
        if self.legendary or self.species in LEGENDARY_IDS:
            self.shiny = False
        if self.treasured is None:
            self.treasured = bool(self.shiny)
        else:
            self.treasured = bool(self.treasured)
        if (not isinstance(self.disposition, str)
                or self.disposition not in {"pending", "keep", "release", "kept", "released"}):
            self.disposition = "pending"

    def value(self) -> float:
        normal = fish_value(self.species, self.weight, self.quality)
        return round(normal * (SHINY_VALUE_MULTIPLIER if self.shiny else 1), 2)

    def to_json(self) -> dict:
        result = deepcopy(self.extra_fields)
        result.update({
            "species": self.species,
            "weight": round(self.weight, 3),
            "quality": round(self.quality, 3),
            "age": round(self.age, 3),
            "zone": self.zone,
            "bait": self.bait,
            "hour": round(self.hour, 3),
            "lake_id":self.lake_id,
            "noted_tired": self.noted_tired,
            "catch_game_minute": (None if self.catch_game_minute is None
                                  else round(self.catch_game_minute, 3)),
        })
        if self.haul_seen:
            result["haul_seen"] = True
        if self.depth_m is not None:
            result["depth_m"] = round(self.depth_m, 3)
        if self.shiny_since_before is not None:
            result["shiny_since_before"] = self.shiny_since_before
        if self.shiny_observation is not None:
            result["shiny_observation"] = self.shiny_observation
        if self.shiny:
            result["shiny"] = True
        if self.treasured:
            result["treasured"] = True
        elif self.shiny:
            result["treasured"] = False
        if self.legendary:
            result["legendary"] = True
        if self.disposition in {"keep", "release"}:
            result["disposition"] = self.disposition
        return result

    @classmethod
    def from_json(cls, raw: dict) -> "Catch":
        catch_minute = raw.get("catch_game_minute")
        try:
            catch_minute_valid = (type(catch_minute) in (int, float)
                                  and math.isfinite(catch_minute))
        except OverflowError:
            catch_minute_valid = False
        if not catch_minute_valid:
            catch_minute = None
        depth = raw.get("depth_m")
        try:
            if type(depth) not in (int, float) or not math.isfinite(depth) or depth < 0:
                depth = None
        except OverflowError:
            depth = None
        before, observation = (raw.get("shiny_since_before"), raw.get("shiny_observation"))
        if type(before) is not int or before < 0:
            before = None
        if type(observation) is not int or observation < 0:
            observation = None
        known = {"species", "weight", "quality", "age", "zone", "bait", "hour",
                 "lake_id", "noted_tired", "catch_game_minute", "shiny",
                 "shiny_since_before", "shiny_observation",
                 "treasured", "legendary", "disposition", "haul_seen", "depth_m"}
        return cls(
            raw["species"], float(raw["weight"]), float(raw["quality"]),
            float(raw["age"]), raw["zone"], raw["bait"], float(raw["hour"]),raw.get("lake_id","briar"),
            bool(raw.get("noted_tired", False)),
            float(catch_minute) if catch_minute is not None else None,
            {key: deepcopy(value) for key, value in raw.items() if key not in known},
            shiny=bool(raw.get("shiny", False)),
            treasured=(bool(raw["treasured"]) if "treasured" in raw else None),
            legendary=bool(raw.get("legendary", False)),
            disposition=raw.get("disposition", "pending"),
            haul_seen=bool(raw.get("haul_seen", False)),
            depth_m=depth,
            shiny_since_before=before,
            shiny_observation=observation,
        )


@dataclass
class Hook:
    baited: bool
    catch: Catch | None = None
    extra_fields: dict = field(default_factory=dict, repr=False)

    def to_json(self) -> dict:
        result = deepcopy(self.extra_fields)
        result.update({"baited": self.baited,
                       "catch": None if self.catch is None else self.catch.to_json()})
        return result

    @classmethod
    def from_json(cls, raw: dict) -> "Hook":
        catch = None if raw.get("catch") is None else Catch.from_json(raw["catch"])
        return cls(bool(raw["baited"]), catch,
                   {key: deepcopy(value) for key, value in raw.items()
                    if key not in {"baited", "catch"}})


@dataclass
class HeldLine:
    tier: str

    @property
    def hooks(self) -> int:
        return LINE_TIERS[self.tier]["hooks"]


@dataclass
class SetLine:
    tier: str
    bait_sections: list[str] | str
    x0: float
    z0: float
    x1: float
    z1: float
    zone: str
    hooks: list[Hook]
    snag_minute: float = -999.0
    line_id: str = field(default_factory=lambda: str(uuid4()))
    extra_fields: dict = field(default_factory=dict, repr=False)
    chime_until: float = -999.0  # game minute the Wave Chime stops ringing on this line
    # Endpoints when the line was set; currents may drift it up to DRIFT_CAP_M away.
    drift_origin: tuple[float, float, float, float] | None = None

    def __post_init__(self):
        if isinstance(self.bait_sections, str):
            sections = [self.bait_sections]
        elif isinstance(self.bait_sections, (list, tuple)):
            sections = list(self.bait_sections)
        else:
            raise ValueError("bait_sections must contain one to three bait IDs")
        if not 1 <= len(sections) <= 3 or any(not isinstance(bait, str) for bait in sections):
            raise ValueError("bait_sections must contain one to three bait IDs")
        self.bait_sections = sections

    @property
    def bait(self) -> str:
        """Compatibility alias for old callers; mixed lines use section one."""
        return self.bait_sections[0]

    def section_for_hook(self, index: int) -> int:
        """Map hook i to one of the equally-sized bait sections."""
        if not self.hooks:
            return 0
        index = max(0, min(len(self.hooks) - 1, int(index)))
        return min(len(self.bait_sections) - 1,
                   index * len(self.bait_sections) // len(self.hooks))

    def bait_for_hook(self, index: int) -> str:
        return self.bait_sections[self.section_for_hook(index)]

    def section_hook_count(self, section: int) -> int:
        return sum(1 for index in range(len(self.hooks))
                   if self.section_for_hook(index) == section)

    def fish_on(self) -> int:
        return sum(1 for h in self.hooks if h.catch is not None)

    def bare_hooks(self) -> int:
        return sum(1 for h in self.hooks if h.catch is None and not h.baited)

    def point_at(self, i: int) -> tuple[float, float]:
        n = max(1, len(self.hooks))
        t = (i + 0.5) / n
        return self.x0 + (self.x1 - self.x0) * t, self.z0 + (self.z1 - self.z0) * t

    def buoys(self) -> list[tuple[float, float]]:
        pts = [(self.x0, self.z0), (self.x1, self.z1)]
        if len(self.hooks) >= 18:
            pts.append(((self.x0 + self.x1) * 0.5, (self.z0 + self.z1) * 0.5))
        return pts

    def to_json(self) -> dict:
        result = deepcopy(self.extra_fields)
        result.update({
            "tier": self.tier, "bait": self.bait,
            "bait_sections": list(self.bait_sections),
            "x0": round(self.x0, 2), "z0": round(self.z0, 2),
            "x1": round(self.x1, 2), "z1": round(self.z1, 2),
            "zone": self.zone,
            "hooks": [h.to_json() for h in self.hooks],
            "snag_minute": self.snag_minute,
            "line_id": self.line_id,
        })
        # Written only once a bot tool has touched the line, so older saves keep their shape.
        if self.chime_until > -999.0:
            result["chime_until"] = self.chime_until
        if self.drift_origin is not None:
            result["drift_origin"] = list(self.drift_origin)
        return result

    @classmethod
    def from_json(cls, raw: dict) -> "SetLine":
        known = {"tier", "bait", "bait_sections", "x0", "z0", "x1", "z1", "zone", "hooks",
                 "snag_minute", "line_id", "chime_until", "drift_origin"}
        sections = raw.get("bait_sections")
        if (not isinstance(sections, list) or not 1 <= len(sections) <= 3
                or any(not isinstance(bait, str) for bait in sections)):
            legacy_bait = raw.get("bait", "worm")
            sections = [legacy_bait if isinstance(legacy_bait, str) else "worm"]
        origin = raw.get("drift_origin")
        if (not isinstance(origin, list) or len(origin) != 4
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in origin)):
            origin = None
        chime_until = raw.get("chime_until", -999)
        if type(chime_until) not in (int, float) or not math.isfinite(chime_until):
            chime_until = -999.0
        return cls(
            raw["tier"], sections, float(raw["x0"]), float(raw["z0"]),
            float(raw["x1"]), float(raw["z1"]), raw["zone"],
            [Hook.from_json(h) for h in raw["hooks"]],
            float(raw.get("snag_minute", -999)),
            deployment_id(raw.get("line_id")) or str(uuid4()),
            {key: deepcopy(value) for key, value in raw.items() if key not in known},
            float(chime_until),
            tuple(float(v) for v in origin) if origin else None,
        )


def _point_seg(px, pz, ax, az, bx, bz) -> float:
    abx, abz = bx - ax, bz - az
    apx, apz = px - ax, pz - az
    ab2 = abx * abx + abz * abz
    if ab2 < 1e-6:
        return math.hypot(px - ax, pz - az)
    t = max(0.0, min(1.0, (apx * abx + apz * abz) / ab2))
    return math.hypot(px - (ax + abx * t), pz - (az + abz * t))


def _seg_gap(a: SetLine, b: SetLine) -> float:
    best = 1e9
    for i in range(8):
        t = i / 7
        px = a.x0 + (a.x1 - a.x0) * t
        pz = a.z0 + (a.z1 - a.z0) * t
        best = min(best, _point_seg(px, pz, b.x0, b.z0, b.x1, b.z1))
    return best


def _zone_path_segments(world: World, x0: float, z0: float,
                        x1: float, z1: float) -> list[tuple[str, float]]:
    """Split one accepted short boat substep at live zone boundaries."""
    total = math.hypot(x1 - x0, z1 - z0)
    if total <= 1e-9:
        return []
    out: list[tuple[str, float]] = []

    def append(zone: str, distance: float) -> None:
        if distance <= 1e-9:
            return
        if out and out[-1][0] == zone:
            out[-1] = (zone, out[-1][1] + distance)
        else:
            out.append((zone, distance))

    def split(t0: float, t1: float, start_zone: str, end_zone: str, depth: int) -> None:
        tm = (t0 + t1) * 0.5
        middle_zone = world.zone_at(x0 + (x1 - x0) * tm, z0 + (z1 - z0) * tm)
        if start_zone == middle_zone == end_zone:
            append(middle_zone, total * (t1 - t0))
            return
        if depth >= 18 or total * (t1 - t0) <= 0.001:
            append(middle_zone, total * (t1 - t0))
            return
        split(t0, tm, start_zone, middle_zone, depth + 1)
        split(tm, t1, middle_zone, end_zone, depth + 1)

    # State.drive already bounds movement substeps to 10 cm. Midpoint checks
    # and recursive splitting preserve the world's boundary precedence.
    split(0.0, 1.0, world.zone_at(x0, z0), world.zone_at(x1, z1), 0)
    return out


FIRST_BITE_BOOST = 8.0  # bite pace in a new game's prologue, until its first fish (first_bite_nudge)


def species_rates(zone: str, bait: str, hour: float, weather: str, depth: float, lake_id="briar", *, game_minutes=None, tool: bottools.ToolState | None = None) -> dict[str, float]:
    """Each species' bite rate at one hook, in bites per game hour, keyed in SPECIES order.

    A rate multiplies the species' base rate by its bait, zone, time-band, weather, depth,
    lake and Bot-tool factors, in that order; given `game_minutes`, an active Lake Day's boost
    follows (`calendar.rate_multiplier`). A species the lake does not hold has lake factor 0,
    so its rate is 0.0 whatever the other factors, and only the lake's own species are
    multiplied out. #140 kept the factor order, so every rate stays bit-identical.

    Pure in its arguments and the content tables. `game_minutes` reaches the rates only
    through the Lake Day row `calendar.active_lake_day` picks for it, which is why
    `_BulkMemo` can key a total by that row instead of the minute.

    Hot path: `State._one_span` asks `State._hook_rates` once per baited hook per span. A
    span without a memo (each live game minute, and the minutes left over after a bulk
    advance's whole hours) calls this every time. The whole-hour spans of one
    `State._advance_hours` (offline catch-up, tows, catnaps, a frame owing over 180 game
    minutes) share a `_BulkMemo` that keeps only each key's total: this runs when a key is
    first asked or asked again after its map started over, and again, unmemoized, when a hook
    bites on a remembered total, to pick the species.

    Args:
        zone: Zone id at the hook.
        bait: Bait id on the hook.
        hour: Hour of day, 0-24.
        weather: Weather id.
        depth: Water depth at the hook, metres.
        lake_id: Lake id.
        game_minutes: Game clock in minutes, for Lake Days; None leaves them out.
        tool: Bot tools in effect (cold layer, chime, winch, silent hull), or None.

    Returns:
        Every species id mapped to its rate (>= 0); the keys' order drives `RNG.pick`.
    """
    out = {}
    lake_rates = LAKE_RATE_MULTIPLIERS.get(lake_id, {})
    special = (None if game_minutes is None
               else calendar.active_lake_day(lake_id, game_minutes, zone))
    for sp in SPECIES:
        lake_rate = lake_rates.get(sp.id, 0.0)
        if not lake_rate:
            out[sp.id] = 0.0
            continue
        rate = (
            sp.rate
            * bait_mult(bait, sp.id)
            * zone_mult(zone, sp.id)
            * time_mult(sp.pref_time, hour)
            * weather_mult(sp.id, weather)
            * depth_mult(sp, depth)
            * lake_rate
            * bottools.species_factor(sp.tags, depth, tool)
        )
        if special is not None and calendar.boosts(special, sp.id):
            rate *= special.multiplier
        out[sp.id] = rate
    return out


@dataclass
class _BulkMemo:
    """Answers one bulk advance asks again and again, each pure in its key (#140).

    One lives for one `State._advance_hours` call and is dropped when it returns, so the
    world, lake, owned tools and hull it was filled under cannot change beneath it.

    `ground` maps a hook point (x, z), the exact floats `SetLine.point_at` returns, to the
    world's (zone, depth in metres) there. It is keyed by position, never by line or hook,
    so a line a Nebula current carries asks again at each new point.

    `totals` maps a baited hook's bite inputs to `sum(species_rates(...).values())`, its
    total bites per game hour before FIRST_BITE_BOOST, which `_one_span` applies after the
    lookup. The key (`State._hook_rates`) holds every input `species_rates` reads: zone,
    bait, hour, weather, depth, lake, the Lake Day row in effect (the only way the game
    minute reaches the rates) and all four `bottools.ToolState` fields. Within one advance
    the zone, bait, hour, weather, depth, Lake Day and chime change; the lake, winch and hull
    do not, and the cold layer follows from lake, hour and weather. Those are keyed anyway,
    so no key relies on them holding still. Only the total is kept: a hook that bites asks
    again without the memo for its species rates.

    Keys and values are immutable and neither map draws from the RNG, so a hit, a miss or a
    map starting over leaves every draw, bite and catch as it would be without a memo.

    MAX_ENTRIES bounds what one call holds: `remember` empties a full map before storing.
    tracemalloc on CPython 3.12, with maps shaped like these and every float its own object
    (so an upper estimate), puts an entry near 224 bytes in `ground` and 264 in `totals`:
    about 15 and 17 MB at the cap, some 32 MB together, freed when the advance returns. The
    heaviest soak measured for #140, a full boat's 192 hooks on grub through the 72-hour
    Cozy cap as eight drifting Nebula current lines, peaked at 25,771 `totals` entries
    (`ground` 14,471) with no map started over: about 40% of the cap. Drifting hook points
    are what add keys there; the earlier full-boat soaks on low-rate bait stayed under
    22,000. Those are measured soaks, not a bound, so the cap stays the guarantee.
    Starting over costs only re-reading answers; it never changes an outcome.
    """

    MAX_ENTRIES: ClassVar[int] = 65_536
    ground: dict = field(default_factory=dict)
    totals: dict = field(default_factory=dict)

    @classmethod
    def remember(cls, table: dict, key, value):
        """Store `value` under `key` in `table`, one of a memo's maps, and return `value`.

        A map already holding MAX_ENTRIES is emptied first, so it never holds more.
        """
        if len(table) >= cls.MAX_ENTRIES:
            table.clear()
        table[key] = value
        return value


def fishing_hint(state, world) -> str | None:
    """What the depth finder would bait here. Read-only. None while moving."""
    if not state.finder or abs(state.speed) > 0.55:
        return None
    zone = world.zone_at(state.x, state.z)
    if zone == "landing":
        return None
    depth = float(world.depth(state.x, state.z))
    hour = hour_of_day(state.game_minutes)
    weather = weather_at(state)
    best_bait, best_sp, best = "worm", "bluegill", -1.0
    for bait in BAIT_BY_ID:
        rates = species_rates(zone, bait, hour, weather, depth, state.lake_id, game_minutes=state.game_minutes)
        sp = max(rates, key=rates.get)
        if rates[sp] > best:
            best, best_bait, best_sp = rates[sp], bait, sp
    if best < 0.004:
        return "Quiet water"
    bait = BAIT_BY_ID[best_bait].name
    fish = SPECIES_BY_ID[best_sp].name
    return f"{bait} for {fish}"


def _buyer_line(catches) -> str:
    """One remark from the dock buyer. Prices stay on the ledger."""
    if not catches:
        return ""
    species = [c.species for c in catches]
    if max(c.weight for c in catches) >= 15.0:
        return "The buyer whistles. That one goes on the board."
    if any(s in {"channel", "blue", "flathead", "bullhead"} for s in species):
        return "He sets the cats aside. Friday fish."
    bass = {"largemouth", "smallmouth", "spotted_bass", "white_bass", "yellow_bass",
            "striped_bass", "hybrid_striper"}
    if any(s in bass for s in species):
        return "He holds a bass up to the light."
    if any("gar" in s or s == "bowfin" for s in species):
        return "The gar gets a look, then he pays anyway."
    return "Panfish money. He counts it out on the rail."


@dataclass
class State:
    SAVE_VERSION: ClassVar[int] = SAVE_VERSION
    rng: RNG
    lake_id: str = "briar"
    boat_id: str = "jon"
    unknown_boat_id: str | None = field(default=None, repr=False)
    owned_boats: list[str] = field(default_factory=lambda:["jon"])
    fuel_tanks: dict[str,float] = field(default_factory=lambda:{"jon":12.0})
    unknown_owned_boats: list = field(default_factory=list, repr=False)
    unknown_fuel_tanks: dict = field(default_factory=dict, repr=False)
    rowboat_trolling_motor: bool = False
    rowboat_battery_kwh: float = 0.0
    rowboat_charge_kwh_this_visit: float = 0.0
    sail_raised: bool = False
    # Manual ignition (issue #153): fuelled boats make no thrust and burn no
    # idle fuel while off. Persisted; defaults on so old saves keep working.
    engine_on: bool = True
    game_minutes: float = 0.0
    minute_acc: float = 0.0
    anim: float = 0.0
    money: float = 46.0
    earned: float = 0.0
    spent: float = 0.0
    bait: dict[str, int] = field(default_factory=lambda: {b: 0 for b in BAIT_BY_ID})
    held: list[HeldLine] = field(default_factory=list)
    lines: list[SetLine] = field(default_factory=list)
    well: list[Catch] = field(default_factory=list)
    x: float = 0.0
    z: float = 0.0
    yaw: float = 0.0
    speed: float = 0.0
    throttle: float = 0.0
    throttle_setting: float = 0.0
    steer: float = 0.0
    look: float = 0.0
    anchored: bool = False
    motor: int = 0
    well_tier: int = 0
    box_tier: int = 0
    finder: bool = False
    light: bool = False
    owned: dict = field(default_factory=dict)
    look_paint: dict = field(default_factory=dict)
    journal: dict = field(default_factory=dict)
    narrative: NarrativeState = field(default_factory=NarrativeState)
    v2: dict = field(default_factory=dict)
    unknown_save_fields: dict = field(default_factory=dict, repr=False)
    unknown_bot_fields: dict = field(default_factory=dict, repr=False)
    # Runtime actors for the loaded lake only; definitions are never serialized.
    npcs: tuple = field(default_factory=tuple, repr=False)
    tutorial: int = 0
    traveled: float = 0.0
    time_scale: int = 1
    muted: bool = False
    toasts: list = field(default_factory=list)
    book_events: list = field(default_factory=list, repr=False, compare=False)
    preferred_bait: str = "worm"
    hooked_total: int = 0
    stamp: float = 0.0
    bot_phase: str = "home"
    bot_x: float = 0.0
    bot_z: float = 0.0
    bot_yaw: float = 0.0
    bot_tx: float = 0.0
    bot_tz: float = 0.0
    bot_hooks: int = -1
    bot_target_line_id: str | None = None
    # A momentary rise where the last fish took. Not saved. Age is real time.
    splash_x: float = 0.0
    splash_z: float = 0.0
    splash_anim: float = -100.0
    # The Skipper's paws pull the line while the haul screen is up. Not saved.
    hauling: bool = field(default=False, repr=False, compare=False)
    # A story scene's staged light (V1-35): {"mist": 0..1, "hour": h}. Not saved.
    stage_light: dict | None = field(default=None, repr=False, compare=False)
    # A legendary's scene stills the lake under the haul (V1-37), 0..1. Not saved.
    encounter_still: float = field(default=0.0, repr=False, compare=False)
    # Seconds of hard decel left after dropping anchor at speed (issue #151 jerk).
    # Runtime only; not saved.
    _anchor_settle: float = field(default=0.0, repr=False, compare=False)
    # Brief visual only; guardian_seen is the persisted encounter latch.
    guardian_sighting_pending: bool = field(default=False, repr=False, compare=False)
    guardian_sighting_started_at: float | None = field(default=None, repr=False, compare=False)
    guardian_sighting_last_anim: float | None = field(default=None, repr=False, compare=False)
    _tired: list = field(default_factory=list)
    _records: list = field(default_factory=list)
    _quest_event_handler: Callable | None = field(default=None, repr=False, compare=False)

    @classmethod
    def new(cls, world: World, seed: int | None = None) -> "State":
        if seed is None:
            seed = time.time_ns() & MASK
        st = cls(rng=RNG(seed))
        st.bait["worm"] = 24
        st.held.append(HeldLine("std"))
        st.owned = {"hull": ["aluminum"], "deck": ["aluminum"], "buoy": ["orange"], "motor": ["black"]}
        st.look_paint = {"hull": "aluminum", "deck": "aluminum", "buoy": "orange", "motor": "black"}
        st.journal = {sp.id: {"count": 0, "best": 0.0, "zone": "", "bait": "", "band": ""} for sp in SPECIES}
        st.v2 = merge_v2_defaults(st, {})
        st._park(world)
        st.bind(world)
        st.stamp = time.time()
        st.toast(f"Dawn on {world.name}. The landing is behind the stern.")
        return st

    def _park(self, world: World):
        slip = world.slip
        # Near the mouth, so the first look is the lake and E still opens the shop.
        self.x, self.z = slip.world(4.0, 0.0)
        fx, fz = -slip.ix, -slip.iz
        self.yaw = math.atan2(fx, fz)
        self.speed = 0.0
        self.throttle = 0.0
        self.throttle_setting = 0.0
        self.anchored = True
        self.sail_raised = False

    def toast(self, text: str, seconds: float = 4.8):
        # Never gone before it can be read at a young reader's pace (V1-43).
        # Bot's short gameplay notes hold a few seconds longer than other
        # notices (issue #155); the reading cap still bounds them.
        duration = reading_seconds(text, seconds)
        if str(text).startswith("Bot:"):
            duration = min(READ_MAX_SECONDS, duration + BOT_TOAST_BONUS)
        self.toasts.append([text, duration])
        if len(self.toasts) > 4:
            self.toasts = self.toasts[-4:]

    def tick_toasts(self, dt: float):
        for item in self.toasts:
            item[1] -= dt
        self.toasts = [t for t in self.toasts if t[1] > 0]

    # --- capacity -------------------------------------------------------

    def well_cap(self) -> float:
        return self.boat.well_cap(self.well_tier)

    def well_load(self) -> float:
        return sum(c.weight for c in self.well)

    def box_cap(self) -> int:
        return BOXES[self.box_tier]

    def bait_count(self) -> int:
        return sum(self.bait.values())

    def max_speed(self) -> float:
        power = self.boat.power
        if power=="sail":
            base = 1.8  # small auxiliary; powered-boat upgrades stay available
        elif self.boat_id=="rowboat":
            base = (ROWBOAT_ELECTRIC_SPEED if self.rowboat_trolling_motor
                    and self.rowboat_battery_kwh > 0.0 else ROWBOAT_ROW_SPEED)
        elif power=="tiller":
            base = MOTORS[self.motor]["speed"] * self.boat.speed_factor
        else:
            base = self.boat.top_speed  # paddle, oars, console, inboard, starlight
        if (self.lake_id=="flathead" and "ice_hull" not in self.boat.traits
                and weather_at(self)=="snow_mist"):
            base *= SNOW_MIST_CHOP
        return base * comfort.speed_factor(self.v2)

    @property
    def boat(self):
        return BOATS[self.boat_id]

    @property
    def fuel(self):
        return self.fuel_tanks.get(self.boat_id,0.0)

    @fuel.setter
    def fuel(self,value):
        self.fuel_tanks[self.boat_id] = max(0.0,min(self.boat.tank,float(value)))

    def _auto_anchor(self) -> bool:
        """Whether throttle/sail may lift the anchor without the anchor key.

        Manual anchoring is the default (issue #151); the persisted
        ``settings.auto_anchor`` flag restores the old convenience lift.
        """
        settings = self.v2.get("settings") if isinstance(self.v2, dict) else None
        return bool(settings.get("auto_anchor")) if isinstance(settings, dict) else False

    def set_anchored(self, value: bool) -> None:
        """Weigh or lift the anchor, preserving propulsion state.

        Dropping at speed kicks off ``_anchor_settle`` so ``drive`` applies a
        short hard decel (the readable jerk) before the usual crawl decay.
        Throttle setting and sail are left untouched: the engine is not
        idled or shut off, and propulsion resumes when the anchor comes up.
        """
        if value == self.anchored:
            return
        self.anchored = value
        if value:
            if abs(self.speed) > 0.4:
                self.speed *= 0.55
                self._anchor_settle = 1.4
            self.toast("Anchor down.")
        else:
            self._anchor_settle = 0.0
            self.toast("Anchor up.")

    def toggle_sail(self) -> str | None:
        if not self.boat.sail_speed:
            return "This boat has no sail."
        self.sail_raised = not self.sail_raised
        if self.sail_raised and self._auto_anchor():
            self.anchored = False
        self.toast("Sail raised. A/D steers; Q lowers it." if self.sail_raised else "Sail lowered.")
        return None

    def toggle_engine(self) -> str | None:
        """Start or stop the engine. Unfuelled hulls have nothing to ignite.

        Returns an error message, or None after toasting the new state.
        Throttle setting is left alone so the lever resumes on restart.
        """
        if not self.boat.fuelled:
            return "This boat has no engine."
        self.engine_on = not self.engine_on
        self.toast("Engine on. V stops it." if self.engine_on else "Engine off.")
        return None


    def sail_drive(self):
        if not self.sail_raised or self.anchored:
            return 0.0
        heading,speed = wind_at(self.game_minutes+self.minute_acc, self)
        return sailing_speed(self.yaw,heading,speed,self.boat.sail_speed)

    def buy_boat(self,boat_id,world) -> str | None:
        model = BOATS[boat_id]
        if self.slip_status(world)!="docked" or abs(self.speed)>=0.45:
            return "Idle at the landing to change boats."
        if self.well_load()>model.well_cap(self.well_tier):
            return "Sell some fish before switching to the smaller livewell."
        if boat_id not in self.owned_boats:
            locked = fleet.shop_error(self, world.id, boat_id)
            if locked:
                return locked
            if not self._spend(model.price):
                return f"Need {dollars(model.price)}."
            self.owned_boats.append(boat_id)
            self.fuel_tanks[boat_id] = model.tank
        self.unknown_boat_id = None
        self.boat_id = boat_id
        self._park(world)
        self.toast(f"Aboard the {model.name}.")
        return None

    def refuel(self) -> str | None:
        missing = self.boat.tank-self.fuel
        amount = min(5.0,missing,max(0.0,self.money)/FUEL_PRICE)
        if missing<0.001:
            return "The tank is full."
        if amount<0.1:
            return "Need some cash for fuel."
        cost = round(amount*FUEL_PRICE,2)
        if not self._spend(cost):
            return f"Need {dollars(cost)}."
        self.fuel += amount
        self.toast(f"Added {amount:.1f} L of fuel for {dollars(cost)}.")
        return None

    def buy_rowboat_trolling_motor(self) -> str | None:
        if "rowboat" not in self.owned_boats:
            return "Buy the rowboat first."
        if self.slip_status(self._world) != "docked" or abs(self.speed) >= 0.45:
            return "Idle at the landing to fit the trolling motor."
        if self.rowboat_trolling_motor:
            return "The trolling motor is already installed."
        if not self._spend(ROWBOAT_MOTOR_PRICE):
            return f"Need {dollars(ROWBOAT_MOTOR_PRICE)}."
        self.rowboat_trolling_motor = True
        self.rowboat_battery_kwh = ROWBOAT_BATTERY_KWH
        self.toast("Installed the 9.9 hp electric trolling motor.")
        return None

    def charge_rowboat_battery(self) -> str | None:
        if not self.rowboat_trolling_motor:
            return "Fit the trolling motor first."
        if self.boat_id != "rowboat":
            return "Aboard the rowboat to charge its battery."
        world = getattr(self, "_world", None)
        if (world is None or self.slip_status(world) != "docked"
                or abs(self.speed) >= 0.45):
            return "Idle at the landing to charge the battery."
        missing = ROWBOAT_BATTERY_KWH - self.rowboat_battery_kwh
        if missing < 0.001:
            return "The battery is full."
        visit_remaining = self.battery_charge_available_this_visit()
        if visit_remaining < 0.1:
            return "The 5 kWh charge limit is used for this landing visit. Leave and return to recharge."
        amount = min(visit_remaining, missing,
                     max(0.0, self.money) / ELECTRICITY_PRICE)
        if amount < 0.1:
            return "Need some cash to charge the battery."
        cost = round(amount * ELECTRICITY_PRICE, 2)
        if not self._spend(cost):
            return f"Need {dollars(cost)}."
        self.rowboat_battery_kwh = min(ROWBOAT_BATTERY_KWH,
                                       self.rowboat_battery_kwh + amount)
        self.rowboat_charge_kwh_this_visit = min(
            BATTERY_CHARGE_KWH, self.rowboat_charge_kwh_this_visit + amount)
        self.toast(f"Added {amount:.1f} kWh for {dollars(cost)}.")
        return None

    def battery_charge_available_this_visit(self) -> float:
        used = min(BATTERY_CHARGE_KWH, max(0.0, self.rowboat_charge_kwh_this_visit))
        return BATTERY_CHARGE_KWH - used

    # --- time -----------------------------------------------------------

    def fast_ok(self) -> bool:
        return self.anchored or (abs(self.speed)<0.25 and abs(self.throttle)<0.08
                                and abs(self.throttle_setting)<0.02 and not self.sail_raised)

    def tow_to_landing(self,world) -> str | None:
        if self.sail_raised or abs(self.speed)>0.5 or abs(self.throttle_setting)>0.02:
            return "Lower the sail and idle before calling the tow boat."
        fee = comfort.tow_fee(self.v2, self.money, self.boat.price)
        self._spend(fee)
        self._park(world)
        if self.fuel<0.75:
            self.fuel = 0.75
        self.advance_bulk(60)
        self.toast(f"Tow to {world.landing}: {dollars(fee)}. Lines kept soaking.")
        return None

    def catnap(self, world, *, forced=False) -> str | None:
        if forced:
            if not comfort.doze_due(self.v2):
                return "No doze is due in the current mode."
        elif not (self.anchored or self.slip_status(world) == "docked"
                  or ("hammock" in self.boat.traits and abs(self.speed) < .25
                      and abs(self.throttle) <= .01 and abs(self.throttle_setting) <= .01
                      and not self.sail_raised)):
            return "Anchor or return to the landing for a catnap."
        eligible = not comfort.rested(self.v2, self.narrative.active_play_game_minutes)
        if forced:
            self.anchored = True
        self.speed = self.throttle = self.throttle_setting = 0.0
        self.sail_raised = False
        self.advance_bulk(comfort.NAP_MINUTES)
        clue = comfort.finish_nap(self, world, eligible)
        self.emit_quest_event({"type": "catnap.complete", "lake_id": world.id,
                               "zone_id": f"{world.id}:{world.zone_at(self.x, self.z)}",
                               "game_minute": self.game_minutes})
        self.toast("A two-hour catnap. Rested, with room for a dream." if eligible
                   else "A two-hour catnap. The lines kept soaking.")
        if clue:
            self.toast("Bot's dream left a habitat lead in your book.")
        return None

    def advance_bulk(self, game_minutes: int) -> tuple[int, int]:
        """Advance an exact amount of online game time and count it as active play."""
        if type(game_minutes) is not int or game_minutes < 0:
            raise ValueError("bulk game time must be a non-negative whole number of minutes")
        before = self.game_minutes
        hours, remainder = divmod(game_minutes, 60)
        hooked, spoiled = self._advance_hours(hours, toast=False)
        for _ in range(remainder):
            h, s, _events = self._one_span(1.0 / 60.0, collect=True, announce=False)
            hooked += h
            spoiled += s
            self.game_minutes += 1.0
        if int(self.game_minutes // calendar.WEEK_MINUTES) != int(before // calendar.WEEK_MINUTES):
            calendar.ensure_plans(self)
        self.narrative.active_play_game_minutes += max(0.0, self.game_minutes - before)
        comfort.advance_needs(self.v2, max(0.0, self.game_minutes - before) / 60)
        if spoiled:
            self.toast(self._spoilage_copy(spoiled))
        return hooked, spoiled

    def advance(self, dt: float, frozen: bool):
        self.anim += dt
        if frozen:
            return
        scale = self.time_scale if self.fast_ok() else 1
        self.minute_acc += dt * scale
        n = int(self.minute_acc)
        self.minute_acc -= n
        if n <= 0:
            return
        before = self.game_minutes
        spoiled = 0
        if n > 180:
            hours, n = divmod(n, 60)
            _hooked, spoiled = self._advance_hours(hours, toast=False)
        notes: dict[int, list] = {}
        self._tired = []
        self._records = []
        for _ in range(n):
            got, lost = self._advance_minute()
            spoiled += lost
            for line_i, sp, weight, x, z in got:
                notes.setdefault(line_i, []).append((sp, weight))
                self.splash_x, self.splash_z = float(x), float(z)
                self.splash_anim = self.anim
        self.narrative.active_play_game_minutes += max(0.0, self.game_minutes - before)
        comfort.advance_needs(self.v2, max(0.0, self.game_minutes - before) / 60)
        for line_i, items in notes.items():
            zone = self.lines[line_i].zone if line_i < len(self.lines) else "open"
            from .world import zone_label
            label = zone_label(zone)
            if len(items) == 1:
                sp, weight = items[0]
                name = SPECIES_BY_ID[sp].name.lower()
                self.toast(f"A {name}, {weight_string(weight)}, took the {label.lower()} line.")
            else:
                self.toast(f"{len(items)} fish took the {label.lower()} line.")
        if len(self._tired) == 1:
            self.toast(self._tired[0])
        elif self._tired:
            self.toast(f"{len(self._tired)} fish are getting tired. About four hours left.")
        if self._records:
            weight, name = max(self._records)
            self.toast(f"Personal best. {weight_string(weight)} {name.lower()}.")
        if spoiled:
            self.toast(self._spoilage_copy(spoiled))
        self._tired = []
        self._records = []

    @staticmethod
    def _spoilage_copy(count: int) -> str:
        if count == 1:
            return "A fish waited a long while and wriggled free. Good for it."
        return f"{count} fish waited a long while and wriggled free. Good for them."

    def catch_up(self, now: float | None = None) -> None:
        """Replay the real time since `stamp` as offline soak, then restamp at `now`.

        One real second replays as one game minute, up to this save's mode cap
        (`comfort.offline_soak_seconds`: 72 real hours in Cozy, 36 in Old Salt). A
        shorter gap replays exactly; a longer one stops at the cap. The lines soak as in
        play: a current carries lines set in it, fish bite, and hooked fish age and get away
        by the usual `SPOIL_HOURS` rule. Each bite is recorded as in play, so the journal and
        book update, a stage-up queues its `book_events` entry and toast, and a protected
        species is released on the spot. No legendary is ever hooked here: offline bites
        pick only from `SPECIES`, which holds no legendary, and their `Catch` keeps
        `legendary=False`. Week seams refresh the saved forecast plans.

        Event-driven quest progress can move: those stage-ups send `book.stage_up`, and
        those protected releases `catch.resolved` (never `legendary`), to the attached quest
        handler (`emit_quest_event`; in play the session's quest manager), whose steps
        listening for them may advance. What runs on active play stays frozen: needs,
        `narrative.active_play_game_minutes` and the quest timers measured from it do not
        move. Nothing is sold and nothing enters the livewell.

        Args:
            now: Real time to catch up to, in epoch seconds; the system clock when None.

        Side effects:
            Advances the game clock, lines, fishing RNG, journal, book, `book_events` and
            the saved forecast plans; increments the in-memory saved `hooked_total` for
            each offline bite (the caller's later `State.save` writes it), which can end a
            new game's first-bite boost, let the tutorial advance on the next drive tick,
            and, if Bot was saved out monitoring a line, cause his bite toast/sound on his
            next tick; may send quest events as above; sets `stamp` to
            `now`; toasts each stage-up, and a summary when anything was hooked or got away.
        """
        now = time.time() if now is None else now
        elapsed = max(0.0, now - self.stamp)
        elapsed = min(elapsed, comfort.offline_soak_seconds(self.v2))
        minutes = int(elapsed)
        self.stamp = now
        if minutes <= 0:
            return
        hooked, spoiled = self._advance_hours(minutes // 60, toast=False)
        for _ in range(minutes % 60):
            got, lost = self._advance_minute(announce=False)
            hooked += len(got)
            spoiled += lost
        if hooked or spoiled:
            self.toast(f"While you were away: {hooked} hooked, {spoiled} got away.")

    def first_bite_nudge(self) -> bool:
        """A new game's prologue, before its first fish is hooked: bites come
        FIRST_BITE_BOOST times as fast, so the first catch lands within the first few minutes
        of play (02 §1, V1-44). Saves past the prologue, and migrated ones, never see it."""
        if self.hooked_total:
            return False
        story = self.v2.get("story") if isinstance(self.v2, dict) else None
        scenes = story.get("scene_states") if isinstance(story, dict) else None
        return isinstance(scenes, dict) and scenes.get("prologue") == "pending"

    def _advance_hours(self, hours: int, toast: bool) -> tuple[int, int]:
        hooked = spoiled = 0
        memo = _BulkMemo()  # what these hours ask of every baited hook again and again
        for _ in range(hours):
            h, s = self._one_span(1.0, announce=toast, memo=memo)
            hooked += h
            spoiled += s
            self.game_minutes += 60.0
            if int(self.game_minutes // calendar.WEEK_MINUTES) != int((self.game_minutes-60) // calendar.WEEK_MINUTES):
                calendar.ensure_plans(self)
        return hooked, spoiled

    def _advance_minute(self, announce: bool = True) -> tuple[list[tuple[int, str, float, float, float]], int]:
        got = []
        h, s, events = self._one_span(1.0 / 60.0, collect=True, announce=announce)
        self.game_minutes += 1.0
        if int(self.game_minutes // calendar.WEEK_MINUTES) != int((self.game_minutes-1) // calendar.WEEK_MINUTES):
            calendar.ensure_plans(self)
        return events, s

    def _one_span(self, hours: float, collect: bool = False, announce: bool = False,
                  memo: _BulkMemo | None = None):
        """Age and bite across `hours` of game time. Clock is advanced by the caller.

        `memo`, from a bulk advance, spares re-reading what its earlier spans read
        (`_BulkMemo`); the outcome is the same with or without it.
        """
        hooked = 0
        spoiled = 0
        events: list[tuple[int, str, float]] = []
        # Representative hour is "now", before the caller bumps the clock.
        hour = hour_of_day(self.game_minutes)
        weather = weather_at(self)
        # Depth and zone come from the world via a callback set on the state.
        world = self._world
        if world is not None:
            self.drift_lines(world, hours * 60.0)
        cold_layer = bottools.cold_layer_m(self.lake_id, hour, weather)
        nudge = self.first_bite_nudge()
        winched = self.owns_tool("zero_g_winch")
        silent_hull = "silent" in self.boat.traits
        for li, line in enumerate(self.lines):
            for i, hook in enumerate(line.hooks):
                if hook.catch is not None:
                    hook.catch.age += hours
                    hook.catch.quality = quality_of(hook.catch.age)
                    if hook.catch.age >= SPOIL_HOURS:
                        self._drop_hook_catch(hook)
                        spoiled += 1
                        continue
                    if announce and not hook.catch.noted_tired and hook.catch.age >= 9.0:
                        hook.catch.noted_tired = True
                        species_info = SPECIES_BY_ID.get(hook.catch.species)
                        name = species_info.name.lower() if species_info is not None else hook.catch.species.replace("_", " ")
                        place = self._world.zone_name(line.zone) if self._world is not None else line.zone
                        self._tired.append(f"A {name} on the {place.lower()} line is getting tired.")
                    continue
                if not hook.baited:
                    continue
                x, z = line.point_at(i)
                zone, depth = self._ground(world, x, z, memo)
                bait = line.bait_for_hook(i)
                bot_tool = bottools.ToolState(cold_layer, self.game_minutes < line.chime_until, winched,
                                              silent_hull)
                rates, total = self._hook_rates(zone, bait, hour, weather, depth, bot_tool, memo)
                if total <= 0:
                    continue
                if nudge:
                    total *= FIRST_BITE_BOOST
                if not self.rng.chance(1.0 - math.exp(-total * hours)):
                    continue
                if rates is None:  # a remembered total; the bite needs the species
                    rates, _total = self._hook_rates(zone, bait, hour, weather, depth, bot_tool, None)
                sp = self.rng.pick(rates)
                weight = self._roll_weight(sp)
                caught_hour = hour
                book = self.v2.setdefault("book", {})
                since_before = shiny_tracker(book, self.journal, sp)["since_shiny"]
                shiny = roll_shiny(book, self.journal, sp, self.rng)
                catch = Catch(sp, weight, 1.0, 0.0, zone, bait, caught_hour,
                              self.lake_id, catch_game_minute=self.game_minutes,
                              depth_m=depth, shiny=shiny,
                              shiny_since_before=since_before if shiny else None)
                hook.catch = catch
                hook.baited = False
                hooked += 1
                self.hooked_total += 1
                self._note_journal(catch, announce=announce)
                reason = self._forced_release_reason(catch)
                if reason:
                    self._release_hook_catch(hook, catch, reason, announce=announce)
                    self._emit_catch(catch, line, i, kept=False)
                if collect:
                    events.append((li, sp, weight, x, z))
        if collect:
            return hooked, spoiled, events
        return hooked, spoiled

    @staticmethod
    def _ground(world: World, x: float, z: float, memo: _BulkMemo | None) -> tuple[str, float]:
        """Zone id and depth in metres at hook point (x, z), from `memo` once it has them."""
        if memo is None:
            return world.zone_at(x, z), float(world.depth(x, z))
        ground = memo.ground.get((x, z))
        if ground is None:
            ground = memo.remember(memo.ground, (x, z),
                                   (world.zone_at(x, z), float(world.depth(x, z))))
        return ground

    def _hook_rates(self, zone: str, bait: str, hour: float, weather: str, depth: float,
                    tool: bottools.ToolState,
                    memo: _BulkMemo | None) -> tuple[dict[str, float] | None, float]:
        """A baited hook's species rates now and their total, both per game hour.

        `species_rates` depends only on these inputs, the lake and the Lake Day in effect, so
        with `memo` a total asked before in this advance comes back alone, rates None, as the
        very float it was. A bite then asks again without `memo` for the species. The full
        key, and why it is enough, is in `_BulkMemo`.
        """
        key = None
        if memo is not None:
            special = calendar.active_lake_day(self.lake_id, self.game_minutes, zone)
            key = (zone, bait, hour, weather, depth, self.lake_id, special,
                   tool.cold_layer_m, tool.chime, tool.winch, tool.silent)
            total = memo.totals.get(key)
            if total is not None:
                return None, total
        rates = species_rates(zone, bait, hour, weather, depth, self.lake_id,
                              game_minutes=self.game_minutes, tool=tool)
        total = sum(rates.values())
        if key is not None:
            memo.remember(memo.totals, key, total)
        return rates, total

    def _roll_weight(self, species_id: str) -> float:
        sp = SPECIES_BY_ID[species_id]
        u = self.rng.u01() ** 1.55
        if self.rng.chance(sp.trophy):
            u = 0.84 + 0.16 * self.rng.u01()
        return sp.min_lb + (sp.max_lb - sp.min_lb) * u

    def _note_journal(self, catch: Catch, announce: bool = False):
        record_legendary_catch(self.v2, catch)
        rec = self.journal.get(catch.species)
        if not isinstance(rec, dict):
            return
        previous_count = max(0, int(rec.get("count", 0)))
        first = previous_count == 0
        previous = float(rec["best"])
        rec["count"] = previous_count + 1
        if catch.weight > previous:
            rec["best"] = round(catch.weight, 2)
        rec["zone"] = catch.zone
        rec["bait"] = catch.bait
        rec["band"] = band_of(catch.hour)
        rec["lake_id"] = catch.lake_id
        record_observation(self.v2.setdefault("book", {}), catch)
        for event in stage_up_events(self.v2, catch.species,
                                     previous_count, rec["count"]):
            self.book_events.append(event)
            self.toast(event["toast"], event["toast_seconds"])
            self.emit_quest_event({"type": "book.stage_up", "species_id": catch.species,
                                   "stage": event["stage"], "game_minute": self.game_minutes})
        refresh_collection_title(self.v2.setdefault("book", {}), self.journal)
        if announce and not first and catch.weight > previous + 0.01:
            self._records.append((catch.weight, SPECIES_BY_ID[catch.species].name))

    def bind(self, world: World):
        self._world = world
        self.lake_id = world.id
        calendar.ensure_plans(self)

    def emit_quest_event(self, event: dict) -> None:
        """Send a live transition to the attached session quest manager."""
        if self._quest_event_handler is not None:
            self._quest_event_handler(self, event)

    # --- boat -----------------------------------------------------------

    def drive(self, dt: float, throttle_in: float, steer_in: float, world: World, *, idle=False,
              player_controlled=False):
        if idle:
            self.throttle_setting = 0.0
            self.throttle = 0.0
        elif throttle_in:
            self.throttle_setting = max(REVERSE_LIMIT,min(1.0,
                self.throttle_setting+throttle_in*THROTTLE_RATE*dt))
        if not idle and abs(throttle_in)>0.01 and self.anchored and self._auto_anchor():
            self.anchored = False
            self.toast("Anchor up.")
        target = 0.0 if self.anchored else self.throttle_setting
        self.throttle += (target - self.throttle) * min(1.0, dt * 2.4)
        # Issue #153: an unignited engine makes no thrust. The lever
        # (throttle_setting) is preserved so it resumes on restart.
        if self.boat.fuelled and not self.engine_on:
            self.throttle = 0.0
        self.steer += (steer_in - self.steer) * min(1.0, dt * 6.0)
        if self.anchored:
            # Issue #151: dropping at speed gets a short hard decel (the jerk),
            # then the usual crawl. Throttle setting and sail survive the drop:
            # the engine idles at zero thrust but is not shut off.
            if self._anchor_settle > 0.0:
                self._anchor_settle = max(0.0, self._anchor_settle - dt)
                self.speed *= math.exp(-dt * 5.0)
            else:
                self.speed *= math.exp(-dt * 2.8)
            self.throttle = 0.0
        else:
            engine = self.throttle
            movement_propulsion = None
            if abs(engine)>0.01:
                if self.boat_id == "rowboat":
                    if self.rowboat_trolling_motor and self.rowboat_battery_kwh > 0.0:
                        needed = (ROWBOAT_MOTOR_POWER_KW
                                  * (0.12 + 0.88 * abs(engine) ** 1.7) * dt / 60.0)
                        available = min(self.rowboat_battery_kwh, needed)
                        engine *= available / max(needed, 1e-12)
                        self.rowboat_battery_kwh = max(0.0, self.rowboat_battery_kwh - available)
                        self.throttle = engine
                        movement_propulsion = "motor"
                        if self.rowboat_battery_kwh == 0.0:
                            self.toast("Battery empty. W/S still row the boat.")
                    else:
                        movement_propulsion = "oar"
                elif not self.boat.fuelled:
                    # Paddles and oars row; a starlight barge glides under its own power.
                    movement_propulsion = "motor" if self.boat.power == "starlight" else "oar"
                else:
                    burn = self.boat.fuel_burn*(1+self.motor*0.75 if self.boat.power=="tiller" else 1.0)
                    burn *= comfort.fuel_factor(self)
                    needed = burn*(0.12+0.88*abs(engine)**1.7)*dt/60.0
                    available = min(self.fuel,needed)
                    engine *= available/max(needed,1e-12)
                    was_fueled = self.fuel>0
                    self.fuel -= available
                    self.throttle = engine
                    if was_fueled and self.fuel==0:
                        self.toast("Tank empty. Refuel at the landing; R calls the tow boat.")
                    if abs(engine) > 0.01:
                        movement_propulsion = "motor"
            factor = comfort.speed_factor(self.v2)
            target_speed = engine*self.max_speed()+self.sail_drive()*factor
            target_speed = min(target_speed,max(self.max_speed(),self.boat.sail_speed*factor))
            rate = self.boat.acceleration if abs(target_speed) > abs(self.speed) else COAST_RATE[self.boat.power]
            self.speed += (target_speed - self.speed) * min(1.0, dt * rate)
            if world.zone_at(self.x, self.z) == "reeds":
                self.speed = max(-REEDS_CRAWL_SPEED, min(REEDS_CRAWL_SPEED, self.speed))
        # Issue #153: an ignited engine idling in neutral burns a small,
        # deterministic share of the full-throttle rate. Docked hulls don't
        # idle-burn (the shop is not an engine room).
        if (self.boat.fuelled and self.engine_on and abs(self.throttle) <= 0.01
                and self.slip_status(world) != "docked"):
            needed = (self.boat.fuel_burn * IDLE_FUEL_FRACTION
                      * comfort.fuel_factor(self) * dt / 60.0)
            available = min(self.fuel, needed)
            was_fueled = self.fuel > 0
            self.fuel -= available
            if was_fueled and self.fuel == 0:
                self.toast("Tank empty. Refuel at the landing; R calls the tow boat.")
        auth = 0.40 + 0.60 * (1.0 - min(1.0, abs(self.speed) / max(0.5, self.max_speed())))
        if abs(self.speed) < 0.2 and abs(self.throttle) < 0.1:
            auth *= 0.2
        direction = 1.0 if self.speed >= -0.05 else -1.0
        if abs(self.speed) <= 0.05:
            direction = 1.0 if self.throttle >= 0 else -1.0
        turn = self.steer*1.15*self.boat.turn_factor*auth*direction*dt
        distance = self.speed*dt
        # Bound the travel of even the bow tip, including simultaneous turns.
        # This prevents crossing a thin barrier between endpoint checks.
        steps = max(1,math.ceil((abs(distance)+max(abs(self.boat.bow),abs(self.boat.stern))*abs(turn))/0.10))
        old_x,old_z = self.x,self.z
        if self.sail_raised and abs(self.sail_drive()) > 0.01:
            propulsion = "sail"
        elif abs(self.throttle) > 0.01:
            propulsion = movement_propulsion
        else:
            propulsion = None
        for _ in range(steps):
            yaw = self.yaw+turn/steps
            if self._hull_ok(self.x,self.z,world,yaw=yaw):
                self.yaw = yaw
            fx,fz = math.sin(self.yaw),math.cos(self.yaw)
            nx,nz = self.x+fx*distance/steps,self.z+fz*distance/steps
            moved, accepted_path = self._move(nx,nz,world)
            if self.slip_status(world) != "docked":
                self.rowboat_charge_kwh_this_visit = 0.0
            for x0, z0, x1, z1 in accepted_path:
                self._emit_movement_events(world, x0, z0, x1, z1,
                                           player_controlled=player_controlled,
                                           propulsion=propulsion)
            if not moved:
                break
        self.yaw = (self.yaw+math.pi)%math.tau-math.pi
        weather = weather_at(self)
        if not self.anchored and weather == "snow_mist" and "wind_steady" not in self.boat.traits:
            heading, wind = wind_at(self.game_minutes, self)
            push = wind * .015 * math.sin(self.anim * .7) * dt * comfort.gust_factor(
                self, weather, using_sail=self.sail_raised)
            self._move(self.x + math.sin(heading) * push, self.z + math.cos(heading) * push, world)
        self.traveled += math.hypot(self.x-old_x,self.z-old_z)
        self._maybe_snag(world)
        self._tutorial()

    def _emit_movement_events(self, world: World, x0: float, z0: float,
                              x1: float, z1: float, *, player_controlled: bool,
                              propulsion: str | None) -> None:
        for point in lake_waypoints(world.id):
            if place_contains(point, x1, z1) and not place_contains(point, x0, z0):
                self.emit_quest_event({
                    "type": "waypoint.enter", "lake_id": world.id,
                    "waypoint_id": f"{world.id}:{point['id']}",
                    "game_minute": self.game_minutes,
                    "movement_cause": "boat",
                    "player_controlled": bool(player_controlled),
                })
        previous = world.zone_at(x0, z0)
        for zone, distance in _zone_path_segments(world, x0, z0, x1, z1):
            if zone != previous:
                self.emit_quest_event({
                    "type": "zone.enter", "lake_id": world.id,
                    "zone_id": f"{world.id}:{zone}",
                    "game_minute": self.game_minutes,
                    "movement_cause": "boat",
                    "player_controlled": bool(player_controlled),
                })
                previous = zone
            if player_controlled and propulsion is not None and distance > 0:
                self.emit_quest_event({
                    "type": "boat.move", "lake_id": world.id,
                    "zone_id": f"{world.id}:{zone}",
                    "distance_m": distance,
                    "player_controlled": True,
                    "propulsion": propulsion,
                    "game_minute": self.game_minutes,
                })

    def _emit_livewell_entry(self, catch: Catch, line: SetLine) -> None:
        self.emit_quest_event({
            "type": "fish.enter_livewell",
            "species_id": catch.species,
            "source_line_id": line.line_id,
            "lake_id": self.lake_id,
            "source_zone_id": f"{self.lake_id}:{line.zone}",
            "bait_id": catch.bait,
            "bait_sections": list(line.bait_sections),
            "catch_game_minute": catch.catch_game_minute,
            "entry_game_minute": self.game_minutes,
        })

    def _emit_catch(self, catch: Catch, line: SetLine, hook_index: int, *, kept: bool) -> None:
        """A catch resolved, kept or released, for `catch_species` (V1-31)."""
        x, z = line.point_at(hook_index)
        minute = catch.catch_game_minute if catch.catch_game_minute is not None else self.game_minutes
        cold = bottools.cold_layer_m(catch.lake_id, catch.hour, weather_at(self, minute))
        self.emit_quest_event({
            "type": "catch.resolved", "species_id": catch.species, "legendary": bool(catch.legendary),
            "kept": kept, "lake_id": catch.lake_id, "zone_id": f"{catch.lake_id}:{catch.zone}",
            "x": float(x), "z": float(z), "bait_id": catch.bait, "weight_lb": catch.weight,
            "catch_hour": catch.hour, "in_cold_band": (cold is not None and catch.depth_m is not None
                                                       and cold <= catch.depth_m <= cold + bottools.COLD_BAND_M),
            "game_minute": self.game_minutes,
        })

    def emit_tool_use(self, world: World, tool_id: str, zone: str | None = None) -> None:
        """A successful Bot tool use, with the shell worn at the time (V1-31).

        `zone` is where the tool acted (a line's zone); it defaults to the boat's.
        """
        profile = self.v2.get("profile", {})
        self.emit_quest_event({
            "type": "tool.use", "tool_id": tool_id, "lake_id": world.id,
            "zone_id": f"{world.id}:{zone or world.zone_at(self.x, self.z)}",
            "shell_id": profile.get("shell") if isinstance(profile, dict) else None,
            "game_minute": self.game_minutes,
        })

    @staticmethod
    def _forced_release_reason(catch: Catch) -> str | None:
        if catch.legendary:
            return "legendary"
        species = SPECIES_BY_ID.get(catch.species)
        if species is not None and "protected" in species.tags:
            return "protected"
        return None

    def _drop_hook_catch(self, hook: Hook) -> None:
        """Drop an escaped fish and refund its pending shiny reservation."""
        if hook.catch is not None:
            lose_shiny(self.v2["book"], hook.catch,
                       (other.catch for line in self.lines for other in line.hooks
                        if other.catch is not None))
        hook.catch = None
        hook.baited = False

    def _release_hook_catch(self, hook: Hook, catch: Catch,
                            reason: str | None = None, *, announce: bool = True) -> None:
        confirm_shiny(self.v2["book"], catch)
        catch.disposition = "released"
        hook.catch = None
        hook.baited = False
        if not announce:
            return
        species_info = SPECIES_BY_ID.get(catch.species)
        name = species_info.name if species_info is not None else catch.species.replace("_", " ").title()
        if reason == "protected":
            self.toast(f"This is a {name}. They are protected here, so back it goes. The book still counts it.")
        elif reason == "legendary":
            self.toast("I will remember that for the rest of my battery.")
        else:
            self.toast(f"Released the {name.lower()}. The book still counts it.")

    def prepare_catch_dispositions(self, line_index: int) -> bool:
        """Default pending catches to Keep and preselect one small release if needed."""
        line = self.lines[line_index]
        self.check_legendary_hook(line)
        newly_pending: list[Catch] = []
        for hook in line.hooks:
            catch = hook.catch
            if catch is None:
                continue
            reason = self._forced_release_reason(catch)
            if reason:
                catch.disposition = "release"
            elif catch.disposition not in {"keep", "release"}:
                catch.disposition = "keep"
                newly_pending.append(catch)

        keep_weight = sum(
            hook.catch.weight for hook in line.hooks
            if hook.catch is not None
            and hook.catch.disposition != "release"
            and self._forced_release_reason(hook.catch) is None
        )
        space = max(0.0, self.well_cap() - self.well_load())
        if keep_weight <= space + 1e-6:
            return False
        candidates = [catch for catch in newly_pending
                      if not catch.treasured
                      and self._forced_release_reason(catch) is None]
        if not candidates:
            return False
        min(candidates, key=lambda catch: (catch.weight, catch.species)).disposition = "release"
        self.toast("The livewell is full. I picked the smallest to swim home. You can change that.")
        return True

    def toggle_catch_disposition(self, line_index: int, hook_index: int) -> str | None:
        hook = self.lines[line_index].hooks[hook_index]
        catch = hook.catch
        if catch is None:
            return "Nothing on that hook."
        if self._forced_release_reason(catch):
            return "This fish has to be released. The book still counts it."
        catch.disposition = "keep" if catch.disposition == "release" else "release"
        return None

    def toggle_treasured(self, catch_index: int) -> str | None:
        if catch_index < 0 or catch_index >= len(self.well):
            return "Nothing there."
        catch = self.well[catch_index]
        catch.treasured = not catch.treasured
        name = SPECIES_BY_ID[catch.species].name.lower()
        self.toast(f"{name.capitalize()} marked Treasured." if catch.treasured
                   else f"Treasured mark removed from {name}.")
        return None

    def set_shiny_tracker(self, species_id: str | None) -> str | None:
        """Select a Verified target (or stop tracking) without resetting pity."""
        if not set_shiny_target(self.v2.setdefault("book", {}), self.journal, species_id):
            return "The Shiny Tracker unlocks after five catches of a standard species."
        if species_id is None:
            self.toast("Shiny Tracker paused. Your counters are saved.")
        else:
            species = SPECIES_BY_ID.get(species_id)
            name = species.name if species else species_id.replace("_", " ")
            self.toast(f"Tracking shiny {name.lower()}.")
        return None

    def mount_shiny_trophy(self, species_id: str, *, boat_id: str | None = None) -> str | None:
        """Mount a remembered shiny replica on a boat's trophy rail.

        This cosmetic does not consume the catch or its book record. The fleet
        renderer draws boat_extras[boat_id]['shiny_trophies'] through rail_trophies().
        """
        boat_id = self.boat_id if boat_id is None else boat_id
        if boat_id not in self.owned_boats or boat_id not in BOATS:
            return "You do not own that boat."
        if "trophy_rail" not in BOATS[boat_id].traits:
            return "This boat needs a trophy rail. Your shinies remain on the book's Trophy page."
        if not shiny_tracker(self.v2["book"], self.journal, species_id)["shiny"]:
            return "Catch a shiny of that species first."
        return self._mount_on_rail(boat_id, "shiny_trophies", species_id)

    def mount_legendary_replica(self, legendary_id: str, *, boat_id: str | None = None) -> str | None:
        """Hang a recorded legendary's trophy replica on a trophy rail (V1-37, 02 §5.5).

        Like a shiny's, it is cosmetic: the legendary's book page and records are untouched.
        """
        from .book import legendary_page
        boat_id = self.boat_id if boat_id is None else boat_id
        if boat_id not in self.owned_boats or boat_id not in BOATS:
            return "You do not own that boat."
        if "trophy_rail" not in BOATS[boat_id].traits:
            return "This boat needs a trophy rail. Your replicas remain on the book's Trophy page."
        page = legendary_page(legendary_id, self.v2, remember=False)
        if not page or not page["records"] or all(r.get("witnessed") for r in page["records"]):
            return "Record that legendary on a line first."
        return self._mount_on_rail(boat_id, "legendary_replicas", legendary_id)

    def rail_trophies(self, boat_id: str | None = None) -> list[tuple[str, str]]:
        """What hangs on a boat's trophy rail, in order: ("shiny" | "legendary", id)."""
        boat_id = self.boat_id if boat_id is None else boat_id
        extras = self.v2.get("boat_extras") if isinstance(self.v2, dict) else None
        fittings = extras.get(boat_id) if isinstance(extras, dict) else None
        if not isinstance(fittings, dict):
            return []
        out = []
        for key, kind in (("legendary_replicas", "legendary"), ("shiny_trophies", "shiny")):
            items = fittings.get(key)
            out.extend((kind, item) for item in (items if isinstance(items, list) else ())
                       if isinstance(item, str))
        return out

    def unmount_trophy(self, kind: str, item_id: str, *, boat_id: str | None = None) -> bool:
        """Take a replica down from a boat's rail. The book keeps everything."""
        boat_id = self.boat_id if boat_id is None else boat_id
        key = "legendary_replicas" if kind == "legendary" else "shiny_trophies"
        extras = self.v2.get("boat_extras") if isinstance(self.v2, dict) else None
        fittings = extras.get(boat_id) if isinstance(extras, dict) else None
        items = fittings.get(key) if isinstance(fittings, dict) else None
        if not isinstance(items, list) or item_id not in items:
            return False
        items.remove(item_id)
        return True

    def _mount_on_rail(self, boat_id: str, key: str, item_id: str) -> str | None:
        from .replica import RAIL_SLOTS
        extras = self.v2.setdefault("boat_extras", {})
        if not isinstance(extras, dict):
            extras = self.v2["boat_extras"] = {}
        fittings = extras.setdefault(boat_id, {})
        if not isinstance(fittings, dict):
            fittings = extras[boat_id] = {}
        trophies = fittings.setdefault(key, [])
        if not isinstance(trophies, list):
            trophies = fittings[key] = []
        if item_id in trophies:
            return None
        if len(self.rail_trophies(boat_id)) >= RAIL_SLOTS:
            return f"The rail holds {RAIL_SLOTS}. Take one down first."
        trophies.append(item_id)
        return None

    def _hull_ok(self, x, z, world: World, *, yaw=None) -> bool:
        return world.hull_clear(x,z,self.yaw if yaw is None else yaw,self.boat_id)

    def _move(self, nx, nz, world: World) -> tuple[bool, list[tuple[float, float, float, float]]]:
        accepted_path: list[tuple[float, float, float, float]] = []

        def record_segment(x0: float, z0: float) -> None:
            if math.hypot(self.x - x0, self.z - z0) > 1e-9:
                accepted_path.append((x0, z0, self.x, self.z))

        if self._hull_ok(nx, nz, world):
            start_x, start_z = self.x, self.z
            self.x, self.z = nx, nz
            record_segment(start_x, start_z)
            return True, accepted_path
        # Approach contact without jumping back an entire simulation step.
        dx,dz = nx-self.x,nz-self.z
        start_x, start_z = self.x, self.z
        lo,hi = 0.0,1.0
        for _ in range(9):
            mid = (lo+hi)*0.5
            if self._hull_ok(self.x+dx*mid,self.z+dz*mid,world):
                lo = mid
            else:
                hi = mid
        self.x += dx*lo
        self.z += dz*lo
        record_segment(start_x, start_z)
        nx,nz = self.x+dx*(1-lo),self.z+dz*(1-lo)
        if self._hull_ok(nx, self.z, world):
            start_x, start_z = self.x, self.z
            self.x = nx
            record_segment(start_x, start_z)
            self.speed *= 0.55
            return False, accepted_path
        if self._hull_ok(self.x, nz, world):
            start_x, start_z = self.x, self.z
            self.z = nz
            record_segment(start_x, start_z)
            self.speed *= 0.55
            return False, accepted_path
        self.speed = 0.0
        return False, accepted_path

    def _maybe_snag(self, world: World):
        if abs(self.speed) < 0.9:
            return
        for line in self.lines:
            if _point_seg(self.x, self.z, line.x0, line.z0, line.x1, line.z1) > 1.35:
                continue
            if self.game_minutes - line.snag_minute < 0.4:
                continue
            line.snag_minute = self.game_minutes
            dropped = False
            for hook in line.hooks:
                if hook.catch is not None:
                    self._drop_hook_catch(hook)
                    dropped = True
                    break
            self.speed *= 0.35
            self.toast("You ran over a line." + (" A fish came off." if dropped else ""))
            break

    def _tutorial(self):
        if self.tutorial == 0 and self.traveled > 30:
            self.tutorial = 1
            self.toast("Stop the boat and press F to set a trotline.")
        elif self.tutorial == 1 and self.lines:
            self.tutorial = 2
            # Issue #156: Bot explains time scaling when Grandmother's first
            # conversation closes. This generic notice only covers saves that
            # never see that conversation.
            if not self.time_tip_given():
                self.toast("Anchor and press T to let time run. E checks a line.")
        elif self.tutorial == 2 and self.hooked_total > 0:
            self.tutorial = 3
            self.toast("Nose into the landing and press E to sell.")
        elif self.tutorial == 3 and self.earned > 0:
            self.tutorial = 4

    def time_tip_given(self) -> bool:
        """Whether Bot already explained time scaling (issue #156, persisted)."""
        story = self.v2.get("story") if isinstance(self.v2, dict) else None
        return isinstance(story, dict) and bool(story.get("bot_time_tip"))

    def mark_time_tip(self) -> None:
        """Remember that Bot explained time scaling, across a reload."""
        story = self.v2.setdefault("story", {})
        if isinstance(story, dict):
            story["bot_time_tip"] = True

    def hint(self, world: World | None = None) -> str | None:
        if self.tutorial == 0:
            return "W/S row or power    Shift idle    A/D steer"
        if self.tutorial == 1:
            # Issue #152: no set-line invite where the water refuses a line.
            if (world is not None and self.held and all(
                    self.line_zone_error(world, h.hooks) is not None for h in self.held)):
                return None
            return "Stop, then F to set a trotline"
        if self.tutorial == 2:
            return "T changes time while anchored    E checks a line"
        if self.tutorial == 3:
            return f"Sell the catch at {self._world.landing}"
        return None

    def slip_status(self, world: World) -> str | None:
        if not bool(world.slip.contains(self.x, self.z)):
            return None
        a, _s = world.slip.local(self.x, self.z)
        if float(a) > 2.0:
            return "docked"
        return "slip"

    def nearest_line(self) -> int | None:
        best_i = None
        best = 8.0
        for i, line in enumerate(self.lines):
            d = _point_seg(self.x, self.z, line.x0, line.z0, line.x1, line.z1)
            if d < best:
                best = d
                best_i = i
        return best_i

    def prompt(self, world: World) -> str | None:
        status = self.slip_status(world)
        if status == "docked" and abs(self.speed) < 0.45:
            return f"E  {world.landing}"
        if status == "slip":
            return "Nose up to the dock"
        if self.nearest_line() is not None and abs(self.speed) < 1.4:
            return "E  Check the line"
        return self.hint(world)

    # --- lines ----------------------------------------------------------

    def owns_tool(self, tool_id: str) -> bool:
        """Bot tools are kept in the profile and work with any shell worn."""
        profile = self.v2.get("profile", {})
        tools = profile.get("tools", []) if isinstance(profile, dict) else []
        return isinstance(tools, list) and tool_id in tools

    def drift_lines(self, world: World, minutes: float) -> None:
        """Nebula currents carry lines in `current` zones unless the winch holds them.

        A line moves as a whole, its midpoint at most DRIFT_CAP_M from where it was
        set. A step that would leave the water or crowd another line is skipped.

        A line pinned at the cap where the current pushes straight outward steps onto the
        very endpoints it already has, span after span (a long Nebula catch-up spends most
        of its spans so). Such a step skips the wet and spacing checks (#140): they are
        pure, and pass or fail the line stays where it is. Any zero endpoint takes the
        checks anyway, because -0.0 == 0.0 and only a passed check would write the sign.
        """
        if minutes <= 0 or self.owns_tool("zero_g_winch"):
            return
        for line in self.lines:
            if line.zone != "current":
                continue
            if line.drift_origin is None:
                line.drift_origin = (line.x0, line.z0, line.x1, line.z1)
            ox0, oz0, ox1, oz1 = line.drift_origin
            mid_x, mid_z = (line.x0 + line.x1) * 0.5, (line.z0 + line.z1) * 0.5
            flow_x, flow_z = bottools.flow_at(mid_x, mid_z)
            off_x = mid_x - (ox0 + ox1) * 0.5 + flow_x * minutes
            off_z = mid_z - (oz0 + oz1) * 0.5 + flow_z * minutes
            reach = math.hypot(off_x, off_z)
            if reach > bottools.DRIFT_CAP_M:
                off_x *= bottools.DRIFT_CAP_M / reach
                off_z *= bottools.DRIFT_CAP_M / reach
            stepped = (ox0 + off_x, oz0 + off_z, ox1 + off_x, oz1 + off_z)
            if stepped == (line.x0, line.z0, line.x1, line.z1) and 0.0 not in stepped:
                continue
            moved = replace(line, x0=stepped[0], z0=stepped[1], x1=stepped[2], z1=stepped[3])
            ends_wet = all(world.navigable(px, pz) for px, pz in
                           ((moved.x0, moved.z0), (moved.x1, moved.z1)))
            if ends_wet and not any(other is not line and _seg_gap(moved, other) < bottools.DRIFT_MIN_GAP_M
                                    for other in self.lines):
                line.x0, line.z0, line.x1, line.z1 = moved.x0, moved.z0, moved.x1, moved.z1

    def use_chime(self, world: World) -> str | None:
        """G on the water: ring the Wave Chime on the nearest line within 30 m."""
        if not self.owns_tool("wave_chime"):
            return "The Wave Chime is not aboard. Rubber Duck Bot sells it."
        if abs(self.speed) >= bottools.CHIME_SLOW_MPS:
            return "Slow the boat before you ring the chime."
        tools = self.v2.get("bot_tools")
        if not isinstance(tools, dict):
            tools = self.v2["bot_tools"] = {}
        ready = comfort.number(tools.get("chime_ready_at"))
        if self.game_minutes < ready:
            return f"The chime rests for {math.ceil(ready - self.game_minutes)} more game minutes."
        near = [(_point_seg(self.x, self.z, line.x0, line.z0, line.x1, line.z1), line)
                for line in self.lines]
        near = [(distance, line) for distance, line in near if distance <= bottools.CHIME_RADIUS_M]
        if not near:
            return "No line of yours is within 30 m of the chime."
        _distance, line = min(near, key=lambda item: item[0])
        line.chime_until = self.game_minutes + bottools.CHIME_LAST_MINUTES
        tools["chime_ready_at"] = self.game_minutes + bottools.CHIME_COOLDOWN_MINUTES
        self.toast("The Wave Chime rings out over your line.")
        self.emit_tool_use(world, "wave_chime", line.zone)
        return None

    def _line_span(self, hooks: int):
        """Where a line of `hooks` hooks would lie, from the bow forward."""
        fx, fz = math.sin(self.yaw), math.cos(self.yaw)
        length = line_length(hooks)
        x0 = self.x + fx * 5.0
        z0 = self.z + fz * 5.0
        return x0, z0, x0 + fx * length, z0 + fz * length

    def line_zone_error(self, world: World, hooks: int) -> str | None:
        """Why a line of `hooks` hooks cannot be set from here, or None.

        Shared by ``try_set`` and the pre-menu check (issue #152): the water
        rules are the same whether or not the bait menu is open. Bait, spare
        line counts and spacing are checked separately in ``try_set``.
        """
        x0, z0, x1, z1 = self._line_span(hooks)
        samples = []
        shallow = False
        for i in range(8):
            t = i / 7
            px = x0 + (x1 - x0) * t
            pz = z0 + (z1 - z0) * t
            samples.append((px, pz))
            if not world.navigable(px, pz) and float(shore_sd_safe(world, px, pz)) >= -0.5:
                return "Point at open water; that line climbs the bank."
            if float(world.depth(px, pz)) < 0.9 and not bool(world.slip.contains(px, pz)):
                shallow = True
        if shallow:
            return "Too skinny for the hooks. Ease out a little."
        for px, pz in samples:
            if bool(world.slip.contains(px, pz)):
                return "The landing is a no-line zone."
            if math.hypot(px - world.slip.ox, pz - world.slip.oz) < 46:
                return "The landing is a no-line zone."
            if not world.navigable(px, pz):
                return "That water won't hold a line."
        mx, mz = (x0 + x1) * 0.5, (z0 + z1) * 0.5
        zone = world.zone_at(mx, mz)
        if zone in ("landing", "shore"):
            return "The landing is a no-line zone."
        if zone == "reeds" and not (self.owns_tool("reed_anchor") or self.boat_id in REED_LINE_BOATS):
            return "Reeds take a line only with Frog Bot's Reed Anchor."
        return None

    def try_set(self, world: World, held_index: int,
                bait_sections: str | list[str] | tuple[str, ...]) -> str | None:
        if abs(self.speed) > 0.5:
            return "Idle the boat before you set."
        if not self.held:
            return "Every line you own is already in the water."
        if held_index < 0 or held_index >= len(self.held):
            return "No line selected."
        if len(self.lines) >= self.boat.lines:
            return f"{self.boat.name} carries up to {self.boat.lines} deployed lines."
        held = self.held[held_index]
        hooks = held.hooks
        sections = ([bait_sections] if isinstance(bait_sections, str)
                    else list(bait_sections) if isinstance(bait_sections, (list, tuple)) else [])
        if not 1 <= len(sections) <= 3:
            return "Choose one to three bait sections."
        if any(bait not in BAIT_BY_ID for bait in sections):
            return "Choose bait from the list."
        needed: dict[str, int] = {}
        for index in range(hooks):
            bait = sections[index * len(sections) // hooks]
            needed[bait] = needed.get(bait, 0) + 1
        for bait, amount in needed.items():
            have = self.bait.get(bait, 0)
            if have < amount:
                return f"Need {amount} {BAIT_BY_ID[bait].name.lower()}. You have {have}."
        zone_error = self.line_zone_error(world, hooks)
        if zone_error:
            return zone_error
        x0, z0, x1, z1 = self._line_span(hooks)
        draft = SetLine(held.tier, sections, x0, z0, x1, z1, "open", [])
        for other in self.lines:
            if _seg_gap(draft, other) < 16.0:
                return "Too close to a line you already set."
        mx, mz = (x0 + x1) * 0.5, (z0 + z1) * 0.5
        zone = world.zone_at(mx, mz)
        for bait, amount in needed.items():
            self.bait[bait] -= amount
        self.held.pop(held_index)
        line_hooks = [Hook(True) for _ in range(hooks)]
        self.lines.append(SetLine(held.tier, sections, x0, z0, x1, z1, zone, line_hooks))
        line = self.lines[-1]
        self.preferred_bait = line.bait
        cold = bottools.cold_layer_m(self.lake_id, hour_of_day(self.game_minutes), weather_at(self))
        set_depth = float(world.depth(mx, mz))
        self.emit_quest_event({
            "type": "line.set",
            "x": mx, "z": mz,
            "in_cold_band": cold is not None and cold <= set_depth <= cold + bottools.COLD_BAND_M,
            "lake_id": self.lake_id,
            "line_id": line.line_id,
            "zone_id": f"{self.lake_id}:{line.zone}",
            "tier_id": line.tier,
            "hook_count": len(line.hooks),
            "bait_id": line.bait if len(set(line.bait_sections)) == 1 else None,
            "bait_sections": list(line.bait_sections),
            "game_minute": self.game_minutes,
            "active_game_minute": self.narrative.active_play_game_minutes,
        })
        if zone == "reeds" and self.boat_id not in REED_LINE_BOATS:
            self.emit_tool_use(world, "reed_anchor", zone)
        from .world import zone_label
        bait_text = ", ".join(BAIT_BY_ID[bait].name.lower() for bait in line.bait_sections)
        self.toast(f"Line set on the {zone_label(zone, self.lake_id).lower()}. {hooks} hooks, {bait_text}.")
        return None

    def line_label(self, index: int) -> str:
        from .world import zone_label
        zone = self.lines[index].zone
        same = [i for i, ln in enumerate(self.lines) if ln.zone == zone]
        name = zone_label(zone, self.lake_id)
        if len(same) == 1:
            return name
        return f"{name} {same.index(index) + 1}"

    def take_hook(self, line_index: int, hook_index: int,
                  disposition: str | None = None) -> str | None:
        line = self.lines[line_index]
        self.check_legendary_hook(line)
        hook = line.hooks[hook_index]
        if hook.catch is None:
            return "Nothing on that hook."
        catch = hook.catch
        reason = self._forced_release_reason(catch)
        if isinstance(disposition, str) and disposition in {"keep", "release"} and not reason:
            catch.disposition = disposition
        if reason or catch.disposition == "release":
            self._release_hook_catch(hook, catch, reason)
            self._emit_catch(catch, line, hook_index, kept=False)
            return None
        if self.well_load() + catch.weight > self.well_cap() + 1e-6:
            return "The livewell won't take that one. Mark a fish Release or make room."
        catch.disposition = "kept"
        confirm_shiny(self.v2["book"], catch)
        self.well.append(catch)
        self._emit_livewell_entry(catch, line)
        self._emit_catch(catch, line, hook_index, kept=True)
        hook.catch = None
        hook.baited = False
        return None

    def take_all(self, line_index: int) -> str:
        line = self.lines[line_index]
        catches = [hook.catch for hook in line.hooks if hook.catch is not None]
        if not catches:
            return "Nothing to take."
        self.prepare_catch_dispositions(line_index)
        keep = [catch for catch in catches
                if catch.disposition != "release"
                and self._forced_release_reason(catch) is None]
        if self.well_load() + sum(catch.weight for catch in keep) > self.well_cap() + 1e-6:
            return "The livewell is full. Mark more fish Release before keeping them."

        kept = released = 0
        for index, hook in enumerate(line.hooks):
            catch = hook.catch
            if catch is None:
                continue
            reason = self._forced_release_reason(catch)
            if reason or catch.disposition == "release":
                self._release_hook_catch(hook, catch, reason)
                self._emit_catch(catch, line, index, kept=False)
                released += 1
            else:
                catch.disposition = "kept"
                confirm_shiny(self.v2["book"], catch)
                self.well.append(catch)
                self._emit_livewell_entry(catch, line)
                self._emit_catch(catch, line, index, kept=True)
                hook.catch = None
                hook.baited = False
                kept += 1
        return f"Resolved catches: kept {kept}, released {released}."

    def rebait(self, line_index: int) -> str | None:
        line = self.lines[line_index]
        need = line.bare_hooks()
        if need == 0:
            return "Nothing bare on that line."
        needed: dict[str, int] = {}
        for index, hook in enumerate(line.hooks):
            if hook.catch is None and not hook.baited:
                bait = line.bait_for_hook(index)
                needed[bait] = needed.get(bait, 0) + 1
        for bait, amount in needed.items():
            have = self.bait.get(bait, 0)
            if have < amount:
                return f"Need {amount} {BAIT_BY_ID[bait].name.lower()}. You have {have}."
        for bait, amount in needed.items():
            self.bait[bait] -= amount
        for hook in line.hooks:
            if hook.catch is None and not hook.baited:
                hook.baited = True
                hook.extra_fields.pop(comfort.FREE_BAIT, None)  # paid for now
        self.toast(f"Rebaited {need} hook{'s' if need != 1 else ''} with their section baits.")
        return None

    def pull_line(self, line_index: int) -> str | None:
        """Pull line `line_index` aboard and coil it into the held lines.

        Any fish on it are taken or released first. When the livewell refuses a keeper,
        that message comes back and the line stays out with its bait. Bait still on
        unused hooks goes back into the bait box (`_return_bait`). When the line was the
        one Bot is watching, he turns for home (bot.line_pulled).

        Returns:
            None once the line is aboard, else the livewell's refusal.
        """
        line = self.lines[line_index]
        if any(hook.catch is not None for hook in line.hooks):
            result = self.take_all(line_index)
            if result.startswith("The livewell"):
                return result
        self.lines.pop(line_index)
        self.held.append(HeldLine(line.tier))
        self.toast("Line coiled in the boat." + self._return_bait(line))
        bot.line_pulled(self, line.line_id)
        return None

    def _return_bait(self, line: SetLine) -> str:
        """Put the bait still on `line`'s unused hooks back in the bait box.

        Only hooks that are baited and empty count. A bite, a fish that got away, and a
        fish taken off or released have all spent their hook's bait, and those hooks read
        unbaited. Bait the keep_bait perk put on for free (comfort.FREE_BAIT) was never
        paid for, so it is not returned. Each hook returns its own section's bait. The
        box fills up to `box_cap()` one hook at a time in hook order, and any bait past
        that goes over the side. Ids missing from BAIT_BY_ID (e.g. from an old save) are
        not returned, because the box only holds bait it can name.

        Returns:
            Feedback to append to the coil toast, starting with a space: the refunded
            counts, the over-the-side count, or both. Empty only when no hook had unused bait.
        """
        room = max(0, self.box_cap() - self.bait_count())
        back: dict[str, int] = {}
        lost = 0
        for index, hook in enumerate(line.hooks):
            if not hook.baited or hook.catch is not None or hook.extra_fields.get(comfort.FREE_BAIT):
                continue
            bait = line.bait_for_hook(index)
            if bait not in BAIT_BY_ID:
                continue
            if room == 0:
                lost += 1
                continue
            room -= 1
            back[bait] = back.get(bait, 0) + 1
            self.bait[bait] = self.bait.get(bait, 0) + 1
        returned = ", ".join(f"{count} {BAIT_BY_ID[bait].name.lower()}" for bait, count in back.items())
        feedback = f" {returned} back in the bait box." if returned else ""
        if lost:
            feedback += f" The box is full; {lost} went over the side."
        return feedback

    # --- shop -----------------------------------------------------------

    def sell_index(self, index: int) -> str | None:
        if index < 0 or index >= len(self.well):
            return "Nothing there."
        catch = self.well.pop(index)
        self._earn(catch.value())
        return None

    def sell_all(self) -> str:
        if not self.well:
            return "Livewell is empty."
        saleable = [catch for catch in self.well if not catch.treasured]
        if not saleable:
            return "Treasured fish stay in the livewell during bulk sale."
        total = round(sum(c.value() for c in saleable), 2)
        n = len(saleable)
        treasured = [catch for catch in self.well if catch.treasured]
        note = _buyer_line(saleable)
        self.well = treasured
        self._earn(total)
        self.toast(f"Sold {n} fish for {dollars(total)}.")
        if treasured:
            self.toast(f"{len(treasured)} Treasured fish stayed in the livewell.")
        if note:
            self.toast(note)
        return f"Sold {n} for {dollars(total)}."

    def _earn(self, amount: float):
        amount = round(amount, 2)
        self.money = round(self.money + amount, 2)
        self.earned = round(self.earned + amount, 2)

    def _spend(self, amount: float) -> bool:
        amount = round(amount, 2)
        if self.money + 1e-6 < amount:
            return False
        self.money = round(self.money - amount, 2)
        self.spent = round(self.spent + amount, 2)
        return True

    def buy_bait(self, bait_id: str) -> str | None:
        bait = BAIT_BY_ID.get(bait_id)
        if bait is None or not ({"all", self.lake_id} & set(bait.sold_at)):
            return "That bait is cooked or sold at another landing."
        if self.bait_count() + DOZEN > self.box_cap():
            return "The bait box is full."
        if not self._spend(bait.price):
            return f"Need {dollars(bait.price)}."
        self.bait[bait_id] = self.bait.get(bait_id, 0) + DOZEN
        self.preferred_bait = bait_id
        self.toast(f"A dozen {bait.name.lower()}.")
        return None

    def buy_line(self, tier: str) -> str | None:
        price = LINE_TIERS[tier]["price"]
        if not self._spend(price):
            return f"Need {dollars(price)}."
        self.held.append(HeldLine(tier))
        self.toast(f"Bought a {LINE_TIERS[tier]['hooks']}-hook line.")
        return None

    def buy_motor(self) -> str | None:
        if self.motor >= len(MOTORS) - 1:
            return "The transom is already at 15 horse."
        nxt = MOTORS[self.motor + 1]
        if not self._spend(nxt["price"]):
            return f"Need {dollars(nxt['price'])}."
        self.motor += 1
        self.toast(f"Hung a {nxt['name']}.")
        return None

    def buy_well(self) -> str | None:
        if self.well_tier >= len(WELLS) - 1:
            return "The livewell is as big as this hull allows."
        price = WELL_PRICE[self.well_tier + 1]
        if not self._spend(price):
            return f"Need {dollars(price)}."
        self.well_tier += 1
        self.toast(f"Livewell holds {WELLS[self.well_tier]:.0f} lb.")
        return None

    def buy_box(self) -> str | None:
        if self.box_tier >= len(BOXES) - 1:
            return "No more room for bait under the seat."
        price = BOX_PRICE[self.box_tier + 1]
        if not self._spend(price):
            return f"Need {dollars(price)}."
        self.box_tier += 1
        self.toast(f"Bait box holds {BOXES[self.box_tier]} pieces.")
        return None

    def buy_finder(self) -> str | None:
        if self.finder:
            return "You already have a depth finder."
        if not self._spend(FINDER_PRICE):
            return f"Need {dollars(FINDER_PRICE)}."
        self.finder = True
        self.toast("Depth finder is on.")
        return None

    def buy_light(self) -> str | None:
        if self.light:
            return "The spotlight is already bolted on."
        if not self._spend(LIGHT_PRICE):
            return f"Need {dollars(LIGHT_PRICE)}."
        self.light = True
        self.toast("Spotlight wired to the bow.")
        return None

    def buy_paint(self, slot: str, pid: str) -> str | None:
        if pid in self.owned.get(slot, []):
            self.look_paint[slot] = pid
            return None
        price = 0.0
        for item in PAINT[slot]:
            if item[0] == pid:
                price = item[3]
                break
        if price > 0 and not self._spend(price):
            return f"Need {dollars(price)}."
        self.owned.setdefault(slot, []).append(pid)
        self.look_paint[slot] = pid
        self.toast("Paint's dry enough.")
        return None

    def advice(self, world: World) -> str:
        zone = world.zone_at(self.x, self.z)
        hour = hour_of_day(self.game_minutes)
        weather = weather_at(self)
        depth = float(world.depth(self.x, self.z))
        best_bait = "worm"
        best_score = -1.0
        best_sp = "bluegill"
        for bait in BAIT_BY_ID:
            rates = species_rates(zone, bait, hour, weather, depth,self.lake_id, game_minutes=self.game_minutes)
            sp = max(rates, key=rates.get)
            if rates[sp] > best_score:
                best_score = rates[sp]
                best_bait = bait
                best_sp = sp
        name = BAIT_BY_ID[best_bait].name.lower()
        fish = SPECIES_BY_ID[best_sp].name.lower()
        if best_score < 0.004:
            return "Thin water for a trotline."
        return f"{name.capitalize()} for {fish} here."

    def cycle_scale(self) -> str | None:
        if not self.fast_ok():
            return "Idle the boat to change time."
        order = (1, 3, 6, 12)
        if self.time_scale not in order:
            self.time_scale = 1
        self.time_scale = order[(order.index(self.time_scale) + 1) % len(order)]
        self.toast(f"Time {self.time_scale}x.")
        return None

    # --- save -----------------------------------------------------------

    def to_json(self) -> dict:
        bot_fields = deepcopy(self.unknown_bot_fields)
        bot_fields.update({
            "phase": self.bot_phase,
            "x": round(self.bot_x, 2), "z": round(self.bot_z, 2),
            "yaw": round(self.bot_yaw, 4),
            "tx": round(self.bot_tx, 2), "tz": round(self.bot_tz, 2),
            "target_line_id": self.bot_target_line_id,
        })
        result = deepcopy(self.unknown_save_fields)
        owned_boats = list(self.owned_boats) + deepcopy(self.unknown_owned_boats)
        fuel_tanks = deepcopy(self.unknown_fuel_tanks)
        fuel_tanks.update({key: round(value, 6)
                           for key, value in self.fuel_tanks.items()})
        saved_boat_id = self.unknown_boat_id or self.boat_id
        result.update({
            "version": SAVE_VERSION,
            "lake_id":self.lake_id,"boat_id":saved_boat_id,"owned_boats":owned_boats,
            "fuel_tanks":fuel_tanks,
            "rowboat_trolling_motor":self.rowboat_trolling_motor,
            "rowboat_battery_kwh":round(self.rowboat_battery_kwh,6),
            "rowboat_charge_kwh_this_visit":round(self.rowboat_charge_kwh_this_visit,6),
            "seed": self.rng.s,
            "game_minutes": round(self.game_minutes, 3),
            "money": self.money,
            "earned": self.earned,
            "spent": self.spent,
            "bait": self.bait,
            "held": [h.tier for h in self.held],
            "lines": [ln.to_json() for ln in self.lines],
            "well": [c.to_json() for c in self.well],
            "x": round(self.x, 2), "z": round(self.z, 2), "yaw": round(self.yaw, 4),
            "anchored": self.anchored, "engine_on": self.engine_on,
            "motor": self.motor, "well_tier": self.well_tier, "box_tier": self.box_tier,
            "finder": self.finder, "light": self.light,
            "owned": self.owned, "look": self.look_paint,
            "journal": self.journal,
            "narrative_v1": self.narrative.to_json(),
            "tutorial": self.tutorial, "traveled": round(self.traveled, 1),
            "time_scale": self.time_scale, "muted": self.muted,
            "preferred_bait": self.preferred_bait,
            "hooked_total": self.hooked_total,
            "stamp": self.stamp,
            "bot": bot_fields,
            "v2": merge_v2_defaults(self, self.v2),
        })
        return result

    def save(self, path: Path, *, update_stamp: bool = True):
        path.parent.mkdir(parents=True, exist_ok=True)
        if update_stamp:
            self.stamp = time.time()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_json()))
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path, world: World) -> "State":
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("save root")
        version = raw.get("version")
        if type(version) is int and version > SAVE_VERSION:
            raise UnsupportedSaveVersionError(version, SAVE_VERSION)
        if type(version) is not int or version not in (1, SAVE_VERSION):
            raise ValueError("save version")
        if version == SAVE_VERSION and "v2" not in raw:
            raise ValueError("save v2 missing v2 object")
        st = cls(rng=RNG(int(raw["seed"])))
        st.unknown_save_fields = {
            key: deepcopy(value) for key, value in raw.items()
            if key not in _SAVE_FIELDS
        }
        if raw.get("lake_id","briar")!=world.id:
            raise ValueError("save belongs to a different lake")
        saved_boat_id = raw.get("boat_id", "jon")
        if not isinstance(saved_boat_id, str):
            raise ValueError("saved boat id must be text")
        if saved_boat_id in BOATS:
            st.boat_id = saved_boat_id
        else:
            # Use a supported boat in this build while keeping the future ID
            # intact for the build that can interpret it.
            st.boat_id = "jon"
            st.unknown_boat_id = saved_boat_id
        raw_owned_boats = raw.get("owned_boats", ["jon"])
        st.owned_boats = [key for key in raw_owned_boats
                          if isinstance(key, str) and key in BOATS]
        st.unknown_owned_boats = [deepcopy(key) for key in raw_owned_boats
                                  if isinstance(key, str) and key not in BOATS]
        if saved_boat_id in BOATS and st.boat_id not in st.owned_boats:
            st.owned_boats.append(st.boat_id)
        raw_fuel_tanks = raw.get("fuel_tanks", {"jon": 12.0})
        st.unknown_fuel_tanks = {
            key: deepcopy(value) for key, value in raw_fuel_tanks.items()
            if key not in BOATS
        }
        st.fuel_tanks = {key:max(0.0,min(BOATS[key].tank,float(value)))
                         for key,value in raw_fuel_tanks.items() if key in BOATS}
        st.rowboat_trolling_motor = (bool(raw.get("rowboat_trolling_motor", False))
                                     and "rowboat" in st.owned_boats)
        battery = raw.get("rowboat_battery_kwh", 0.0)
        try:
            battery = float(battery)
        except (TypeError, ValueError, OverflowError):
            battery = 0.0
        st.rowboat_battery_kwh = (min(ROWBOAT_BATTERY_KWH, max(0.0, battery))
                                  if st.rowboat_trolling_motor and math.isfinite(battery) else 0.0)
        charge_used = raw.get("rowboat_charge_kwh_this_visit", 0.0)
        try:
            charge_used = float(charge_used)
        except (TypeError, ValueError, OverflowError):
            charge_used = 0.0
        st.rowboat_charge_kwh_this_visit = (
            min(BATTERY_CHARGE_KWH, max(0.0, charge_used))
            if st.rowboat_trolling_motor and math.isfinite(charge_used) else 0.0)
        st.game_minutes = float(raw["game_minutes"])
        st.money = float(raw["money"])
        st.earned = float(raw.get("earned", 0))
        st.spent = float(raw.get("spent", 0))
        st.bait = {k: int(v) for k, v in raw["bait"].items()}
        st.held = [HeldLine(t) for t in raw["held"]]
        st.lines = [SetLine.from_json(ln) for ln in raw["lines"]]
        # Duplicate saved IDs are ambiguous: replace every affected identity so
        # a historical quest reference can never bind to the wrong deployment.
        ids = [line.line_id for line in st.lines]
        for line in st.lines:
            if ids.count(line.line_id) > 1:
                line.line_id = str(uuid4())
        st.well = [Catch.from_json(c) for c in raw["well"]]
        for catch in st.well:
            catch.disposition = "kept"
        st.x, st.z, st.yaw = float(raw["x"]), float(raw["z"]), float(raw["yaw"])
        st.anchored = bool(raw.get("anchored", False))
        st.engine_on = bool(raw.get("engine_on", True))
        st.motor = int(raw["motor"])
        st.well_tier = int(raw["well_tier"])
        st.box_tier = int(raw["box_tier"])
        st.finder = bool(raw["finder"])
        st.light = bool(raw["light"])
        st.owned = raw["owned"]
        st.look_paint = raw["look"]
        st.journal = raw["journal"]
        st.narrative = NarrativeState.from_json(raw.get("narrative_v1"))
        raw_bot_fields = raw.get("bot")
        if isinstance(raw_bot_fields, dict):
            st.unknown_bot_fields = {
                key: deepcopy(value) for key, value in raw_bot_fields.items()
                if key not in _BOT_FIELDS
            }
        for sp in SPECIES:
            st.journal.setdefault(sp.id, {"count": 0, "best": 0.0, "zone": "", "bait": "", "band": ""})
        st.tutorial = int(raw.get("tutorial", 4))
        st.traveled = float(raw.get("traveled", 0))
        st.time_scale = int(raw.get("time_scale", 1))
        st.muted = bool(raw.get("muted", False))
        st.preferred_bait = raw.get("preferred_bait", "worm")
        st.hooked_total = int(raw.get("hooked_total", 0))
        st.stamp = float(raw.get("stamp", time.time()))
        raw_bot = raw_bot_fields
        if isinstance(raw_bot, dict) and raw_bot.get("phase") in ("home", "go", "out", "back"):
            st.bot_phase = raw_bot["phase"]
            st.bot_x = float(raw_bot.get("x", 0.0))
            st.bot_z = float(raw_bot.get("z", 0.0))
            st.bot_yaw = float(raw_bot.get("yaw", 0.0))
            st.bot_tx = float(raw_bot.get("tx", st.bot_x))
            st.bot_tz = float(raw_bot.get("tz", st.bot_z))
            st.bot_hooks = st.hooked_total
            if not all(math.isfinite(v) for v in (st.bot_x, st.bot_z, st.bot_yaw, st.bot_tx, st.bot_tz)):
                st.bot_phase = "home"
            target_id = deployment_id(raw_bot.get("target_line_id"))
            if st.bot_phase in ("go", "out") and any(line.line_id == target_id for line in st.lines):
                st.bot_target_line_id = target_id
        st.bind(world)
        safe_x,safe_z,safe_yaw = world.clear_boat_position(st.x,st.z,st.yaw,st.boat_id)
        if (safe_x,safe_z,safe_yaw)!=(st.x,st.z,st.yaw):
            st.x,st.z,st.yaw = safe_x,safe_z,safe_yaw
            st.toast("Boat eased back into clear water.")
        if st.slip_status(world) != "docked":
            st.rowboat_charge_kwh_this_visit = 0.0
        st.v2 = merge_v2_defaults(st, raw.get("v2") if version == SAVE_VERSION else None)
        if getattr(world, "caldera", False) or getattr(world, "nebula", False):
            # New islands (Crater's cinder isle, the Lagoon's lily drifts) can
            # sit where an older save's rope lies; move it to clear water.
            from .caldera import recover_displaced_lines
            recover_displaced_lines(st, world)
        return st

    def claim_reward(self, kind: str, key: str) -> bool:
        """Persist an idempotency key for one new v2 reward kind."""
        if kind not in V2_REWARD_KINDS or not isinstance(key, str) or not key.strip():
            return False

        claims = self.v2["reward_claims"][kind]
        if key in claims:
            return False
        claims.append(key)
        return True
    def check_legendary_hook(self, line: SetLine) -> Catch | None:
        """Evaluate and hook an eligible legendary on line checks / hauls."""
        from . import legendary
        return legendary.check_legendary_hook(self, line, self._world)

    def set_book_title(self, title: str) -> bool:
        """Advance the book title from story progress or collection completion."""
        return promote_title(self.v2.setdefault("book", {}), title, self.journal)

    def take_book_events(self) -> list[dict]:
        """Return pending presentation events and clear the transient queue."""
        events, self.book_events = self.book_events, []
        return events

    def set_scene_status(self, scene_id: str, status: str) -> bool:
        """Latch a scene as pending or done; pending scenes never grant rewards."""
        if not isinstance(scene_id, str) or not scene_id.strip():
            return False
        if status not in ("pending", "done"):
            return False
        scene_states = self.v2["story"]["scene_states"]
        if scene_states.get(scene_id) == "done" and status == "pending":
            return False
        scene_states[scene_id] = status
        if status == "done":
            seen = self.v2["story"]["scenes_seen"]
            if scene_id not in seen:
                seen.append(scene_id)
        return True


def shore_sd_safe(world: World, x: float, z: float) -> float:
    return float(world.shore_sd(x, z))


def saved_lake(path: Path) -> str:
    try:
        lake = json.loads(path.read_text(encoding="utf-8")).get("lake_id","briar")
        return lake if lake in LAKES else "briar"
    except (OSError,ValueError):
        return "briar"


def clock(state: State) -> str:
    return clock_string(state.game_minutes)
