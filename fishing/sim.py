"""Boat, trotlines, bites, and the bait-shop ledger.

Time: one real second is one game minute at 1x, and a new game starts at dawn.
Lines keep fishing while the game is closed, capped at six hours, and a hook
only holds one fish, so a long absence is one soak rather than a jackpot.
"""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from uuid import uuid4

from .data import (
    BAIT_BY_ID,
    BOX_PRICE,
    BOXES,
    DOZEN,
    FINDER_PRICE,
    LIGHT_PRICE,
    LINE_TIERS,
    MAX_LINES,
    MOTORS,
    PAINT,
    SPECIES,
    SPECIES_BY_ID,
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
    weather_at,
    bait_mult,
    zone_mult,
    time_mult,
    weather_mult,
    depth_mult,
    CEDAR_FISH,
)
from .world import World
from .boat import BOATS, FUEL_PRICE, THROTTLE_RATE, REVERSE_LIMIT, sailing_speed
from .weather import wind_at
from .lakes import LAKES
from .narrative import NarrativeState, deployment_id

MASK = (1 << 64) - 1
SAVE_VERSION = 1


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

    def value(self) -> float:
        return fish_value(self.species, self.weight, self.quality)

    def to_json(self) -> dict:
        return {
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
        }

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
        return cls(
            raw["species"], float(raw["weight"]), float(raw["quality"]),
            float(raw["age"]), raw["zone"], raw["bait"], float(raw["hour"]),raw.get("lake_id","briar"),
            bool(raw.get("noted_tired", False)),
            float(catch_minute) if catch_minute is not None else None,
        )


@dataclass
class Hook:
    baited: bool
    catch: Catch | None = None

    def to_json(self) -> dict:
        return {"baited": self.baited, "catch": None if self.catch is None else self.catch.to_json()}

    @classmethod
    def from_json(cls, raw: dict) -> "Hook":
        catch = None if raw.get("catch") is None else Catch.from_json(raw["catch"])
        return cls(bool(raw["baited"]), catch)


@dataclass
class HeldLine:
    tier: str

    @property
    def hooks(self) -> int:
        return LINE_TIERS[self.tier]["hooks"]


@dataclass
class SetLine:
    tier: str
    bait: str
    x0: float
    z0: float
    x1: float
    z1: float
    zone: str
    hooks: list[Hook]
    snag_minute: float = -999.0
    line_id: str = field(default_factory=lambda: str(uuid4()))

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
        return {
            "tier": self.tier, "bait": self.bait,
            "x0": round(self.x0, 2), "z0": round(self.z0, 2),
            "x1": round(self.x1, 2), "z1": round(self.z1, 2),
            "zone": self.zone,
            "hooks": [h.to_json() for h in self.hooks],
            "snag_minute": self.snag_minute,
            "line_id": self.line_id,
        }

    @classmethod
    def from_json(cls, raw: dict) -> "SetLine":
        return cls(
            raw["tier"], raw["bait"], float(raw["x0"]), float(raw["z0"]),
            float(raw["x1"]), float(raw["z1"]), raw["zone"],
            [Hook.from_json(h) for h in raw["hooks"]],
            float(raw.get("snag_minute", -999)),
            deployment_id(raw.get("line_id")) or str(uuid4()),
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


def species_rates(zone: str, bait: str, hour: float, weather: str, depth: float, lake_id="briar") -> dict[str, float]:
    out = {}
    for sp in SPECIES:
        out[sp.id] = (
            sp.rate
            * bait_mult(bait, sp.id)
            * zone_mult(zone, sp.id)
            * time_mult(sp.pref_time, hour)
            * weather_mult(sp.id, weather)
            * depth_mult(sp, depth)
            * (CEDAR_FISH.get(sp.id,0.0) if lake_id=="cedar" else 1.0)
        )
    return out


def fishing_hint(state, world) -> str | None:
    """What the depth finder would bait here. Read-only. None while moving."""
    if not state.finder or abs(state.speed) > 0.55:
        return None
    zone = world.zone_at(state.x, state.z)
    if zone == "landing":
        return None
    depth = float(world.depth(state.x, state.z))
    hour = hour_of_day(state.game_minutes)
    weather = weather_at(state.game_minutes)
    best_bait, best_sp, best = "worm", "bluegill", -1.0
    for bait in BAIT_BY_ID:
        rates = species_rates(zone, bait, hour, weather, depth, state.lake_id)
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
    rng: RNG
    lake_id: str = "briar"
    boat_id: str = "jon"
    owned_boats: list[str] = field(default_factory=lambda:["jon"])
    fuel_tanks: dict[str,float] = field(default_factory=lambda:{"jon":12.0})
    sail_raised: bool = False
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
    # Runtime actors for the loaded lake only; definitions are never serialized.
    npcs: tuple = field(default_factory=tuple, repr=False)
    tutorial: int = 0
    traveled: float = 0.0
    time_scale: int = 1
    muted: bool = False
    toasts: list = field(default_factory=list)
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

    def toast(self, text: str):
        self.toasts.append([text, 4.8])
        if len(self.toasts) > 4:
            self.toasts = self.toasts[-4:]

    def tick_toasts(self, dt: float):
        for item in self.toasts:
            item[1] -= dt
        self.toasts = [t for t in self.toasts if t[1] > 0]

    # --- capacity -------------------------------------------------------

    def well_cap(self) -> float:
        return WELLS[self.well_tier] + self.boat.well_bonus

    def well_load(self) -> float:
        return sum(c.weight for c in self.well)

    def box_cap(self) -> int:
        return BOXES[self.box_tier]

    def bait_count(self) -> int:
        return sum(self.bait.values())

    def max_speed(self) -> float:
        if self.boat_id=="sail":
            return 1.8  # small auxiliary; powered-boat upgrades stay available
        return MOTORS[self.motor]["speed"] * self.boat.speed_factor

    @property
    def boat(self):
        return BOATS[self.boat_id]

    @property
    def fuel(self):
        return self.fuel_tanks.get(self.boat_id,0.0)

    @fuel.setter
    def fuel(self,value):
        self.fuel_tanks[self.boat_id] = max(0.0,min(self.boat.tank,float(value)))

    def toggle_sail(self) -> str | None:
        if not self.boat.sail_speed:
            return "The daysailer has the sail."
        self.sail_raised = not self.sail_raised
        if self.sail_raised:
            self.anchored = False
        self.toast("Sail raised. A/D steers; Q lowers it." if self.sail_raised else "Sail lowered.")
        return None

    def sail_drive(self):
        if not self.sail_raised or self.anchored:
            return 0.0
        heading,speed = wind_at(self.game_minutes+self.minute_acc)
        return sailing_speed(self.yaw,heading,speed,self.boat.sail_speed)

    def buy_boat(self,boat_id,world) -> str | None:
        model = BOATS[boat_id]
        if self.slip_status(world)!="docked" or abs(self.speed)>=0.45:
            return "Idle at the landing to change boats."
        if self.well_load()>WELLS[self.well_tier]+model.well_bonus:
            return "Sell some fish before switching to the smaller livewell."
        if boat_id not in self.owned_boats:
            if not self._spend(model.price):
                return f"Need {dollars(model.price)}."
            self.owned_boats.append(boat_id)
            self.fuel_tanks[boat_id] = model.tank
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

    def owned_lines(self) -> int:
        return len(self.held) + len(self.lines)

    # --- time -----------------------------------------------------------

    def fast_ok(self) -> bool:
        return self.anchored or (abs(self.speed)<0.25 and abs(self.throttle)<0.08
                                and abs(self.throttle_setting)<0.02 and not self.sail_raised)

    def tow_to_landing(self,world) -> str | None:
        if self.sail_raised or abs(self.speed)>0.5 or abs(self.throttle_setting)>0.02:
            return "Lower the sail and idle before calling the tow boat."
        fee = min(10.0,max(0.0,self.money))
        self._spend(fee)
        self._park(world)
        if self.fuel<0.75:
            self.fuel = 0.75
        before = self.game_minutes
        self._advance_hours(1,toast=False)
        self.narrative.active_play_game_minutes += max(0.0, self.game_minutes - before)
        self.toast(f"Tow to {world.landing}: {dollars(fee)}. Lines kept soaking.")
        return None

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
        if n > 180:
            hours, n = divmod(n, 60)
            self._advance_hours(hours, toast=False)
        notes: dict[int, list] = {}
        self._tired = []
        self._records = []
        for _ in range(n):
            got = self._advance_minute()
            for line_i, sp, weight, x, z in got:
                notes.setdefault(line_i, []).append((sp, weight))
                self.splash_x, self.splash_z = float(x), float(z)
                self.splash_anim = self.anim
        self.narrative.active_play_game_minutes += max(0.0, self.game_minutes - before)
        for line_i, items in notes.items():
            zone = self.lines[line_i].zone if line_i < len(self.lines) else "open"
            from .world import zone_label
            label = zone_label(zone)
            if len(items) == 1:
                sp, weight = items[0]
                name = SPECIES_BY_ID[sp].name.lower()
                self.toast(f"A {name}, {weight:.1f} lb, took the {label.lower()} line.")
            else:
                self.toast(f"{len(items)} fish took the {label.lower()} line.")
        if len(self._tired) == 1:
            self.toast(self._tired[0])
        elif self._tired:
            self.toast(f"{len(self._tired)} fish are getting tired. About four hours left.")
        if self._records:
            weight, name = max(self._records)
            self.toast(f"Personal best. {weight:.1f} lb {name.lower()}.")
        self._tired = []
        self._records = []

    def catch_up(self, now: float | None = None) -> None:
        now = time.time() if now is None else now
        elapsed = max(0.0, now - self.stamp)
        elapsed = min(elapsed, 6 * 3600)
        minutes = int(elapsed)
        self.stamp = now
        if minutes <= 0:
            return
        hooked, spoiled = self._advance_hours(minutes // 60, toast=False)
        for _ in range(minutes % 60):
            got = self._advance_minute(announce=False)
            hooked += len(got)
        if hooked or spoiled:
            self.toast(f"While you were away: {hooked} hooked, {spoiled} spoiled.")

    def _advance_hours(self, hours: int, toast: bool) -> tuple[int, int]:
        hooked = spoiled = 0
        for _ in range(hours):
            h, s = self._one_span(1.0)
            hooked += h
            spoiled += s
            self.game_minutes += 60.0
        return hooked, spoiled

    def _advance_minute(self, announce: bool = True) -> list[tuple[int, str, float, float, float]]:
        got = []
        h, s, events = self._one_span(1.0 / 60.0, collect=True, announce=announce)
        self.game_minutes += 1.0
        return events

    def _one_span(self, hours: float, collect: bool = False, announce: bool = False):
        """Age and bite across `hours` of game time. Clock is advanced by the caller."""
        hooked = 0
        spoiled = 0
        events: list[tuple[int, str, float]] = []
        # Representative hour is "now", before the caller bumps the clock.
        hour = hour_of_day(self.game_minutes)
        weather = weather_at(self.game_minutes)
        # Depth and zone come from the world via a callback set on the state.
        world = self._world
        for li, line in enumerate(self.lines):
            for i, hook in enumerate(line.hooks):
                if hook.catch is not None:
                    hook.catch.age += hours
                    hook.catch.quality = quality_of(hook.catch.age)
                    if hook.catch.age >= SPOIL_HOURS:
                        hook.catch = None
                        hook.baited = False
                        spoiled += 1
                        continue
                    if announce and not hook.catch.noted_tired and hook.catch.age >= 9.0:
                        hook.catch.noted_tired = True
                        name = SPECIES_BY_ID[hook.catch.species].name.lower()
                        place = self._world.zone_name(line.zone) if self._world is not None else line.zone
                        self._tired.append(f"A {name} on the {place.lower()} line is getting tired.")
                    continue
                if not hook.baited:
                    continue
                x, z = line.point_at(i)
                zone = world.zone_at(x, z)
                depth = float(world.depth(x, z))
                rates = species_rates(zone, line.bait, hour, weather, depth,self.lake_id)
                total = sum(rates.values())
                if total <= 0:
                    continue
                if not self.rng.chance(1.0 - math.exp(-total * hours)):
                    continue
                sp = self.rng.pick(rates)
                weight = self._roll_weight(sp)
                caught_hour = hour
                catch = Catch(sp, weight, 1.0, 0.0, zone, line.bait, caught_hour,
                              self.lake_id, catch_game_minute=self.game_minutes)
                hook.catch = catch
                hook.baited = False
                hooked += 1
                self.hooked_total += 1
                self._note_journal(catch, announce=announce)
                if collect:
                    events.append((li, sp, weight, x, z))
        if collect:
            return hooked, spoiled, events
        return hooked, spoiled

    def _roll_weight(self, species_id: str) -> float:
        sp = SPECIES_BY_ID[species_id]
        u = self.rng.u01() ** 1.55
        if self.rng.chance(sp.trophy):
            u = 0.84 + 0.16 * self.rng.u01()
        return sp.min_lb + (sp.max_lb - sp.min_lb) * u

    def _note_journal(self, catch: Catch, announce: bool = False):
        rec = self.journal[catch.species]
        first = int(rec["count"]) == 0
        previous = float(rec["best"])
        rec["count"] += 1
        if catch.weight > previous:
            rec["best"] = round(catch.weight, 2)
        rec["zone"] = catch.zone
        rec["bait"] = catch.bait
        rec["band"] = band_of(catch.hour)
        rec["lake_id"] = catch.lake_id
        if announce and not first and catch.weight > previous + 0.01:
            self._records.append((catch.weight, SPECIES_BY_ID[catch.species].name))

    def bind(self, world: World):
        self._world = world
        self.lake_id = world.id

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
        if not idle and abs(throttle_in)>0.01 and self.anchored:
            self.anchored = False
            self.toast("Anchor up.")
        target = 0.0 if self.anchored else self.throttle_setting
        self.throttle += (target - self.throttle) * min(1.0, dt * 2.4)
        self.steer += (steer_in - self.steer) * min(1.0, dt * 6.0)
        if self.anchored:
            self.speed *= math.exp(-dt * 2.8)
            self.throttle = 0.0
            self.throttle_setting = 0.0
            self.sail_raised = False
        else:
            engine = self.throttle
            if abs(engine)>0.01:
                burn = self.boat.fuel_burn*(1.0 if self.boat_id=="sail" else 1+self.motor*0.75)
                needed = burn*(0.12+0.88*abs(engine)**1.7)*dt/60.0
                available = min(self.fuel,needed)
                engine *= available/max(needed,1e-12)
                was_fueled = self.fuel>0
                self.fuel -= available
                self.throttle = engine
                if was_fueled and self.fuel==0:
                    self.toast("Tank empty. Refuel at the landing; R calls the tow boat.")
            target_speed = engine*self.max_speed()+self.sail_drive()
            target_speed = min(target_speed,max(self.max_speed(),self.boat.sail_speed))
            rate = self.boat.acceleration if abs(target_speed) > abs(self.speed) else 0.65
            self.speed += (target_speed - self.speed) * min(1.0, dt * rate)
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
            propulsion = "motor"
        else:
            propulsion = None
        for _ in range(steps):
            yaw = self.yaw+turn/steps
            if self._hull_ok(self.x,self.z,world,yaw=yaw):
                self.yaw = yaw
            fx,fz = math.sin(self.yaw),math.cos(self.yaw)
            nx,nz = self.x+fx*distance/steps,self.z+fz*distance/steps
            start_x, start_z = self.x, self.z
            moved = self._move(nx,nz,world)
            self._emit_movement_events(world, start_x, start_z, self.x, self.z,
                                       player_controlled=player_controlled,
                                       propulsion=propulsion)
            if not moved:
                break
        self.yaw = (self.yaw+math.pi)%math.tau-math.pi
        self.traveled += math.hypot(self.x-old_x,self.z-old_z)
        self._maybe_snag(world)
        self._tutorial()

    def _emit_movement_events(self, world: World, x0: float, z0: float,
                              x1: float, z1: float, *, player_controlled: bool,
                              propulsion: str | None) -> None:
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
            "bait_id": line.bait,
            "catch_game_minute": catch.catch_game_minute,
            "entry_game_minute": self.game_minutes,
        })

    def _hull_ok(self, x, z, world: World, *, yaw=None) -> bool:
        return world.hull_clear(x,z,self.yaw if yaw is None else yaw,self.boat_id)

    def _move(self, nx, nz, world: World):
        if self._hull_ok(nx, nz, world):
            self.x, self.z = nx, nz
            return True
        # Approach contact without jumping back an entire simulation step.
        dx,dz = nx-self.x,nz-self.z
        lo,hi = 0.0,1.0
        for _ in range(9):
            mid = (lo+hi)*0.5
            if self._hull_ok(self.x+dx*mid,self.z+dz*mid,world):
                lo = mid
            else:
                hi = mid
        self.x += dx*lo
        self.z += dz*lo
        nx,nz = self.x+dx*(1-lo),self.z+dz*(1-lo)
        if self._hull_ok(nx, self.z, world):
            self.x = nx
            self.speed *= 0.55
            return False
        if self._hull_ok(self.x, nz, world):
            self.z = nz
            self.speed *= 0.55
            return False
        self.speed = 0.0
        return False

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
                    hook.catch = None
                    hook.baited = False
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
            self.toast("Anchor and press T to let time run. E checks a line.")
        elif self.tutorial == 2 and self.hooked_total > 0:
            self.tutorial = 3
            self.toast("Nose into the landing and press E to sell.")
        elif self.tutorial == 3 and self.earned > 0:
            self.tutorial = 4

    def hint(self) -> str | None:
        if self.tutorial == 0:
            return "W/S adjust throttle    Shift idle    A/D steer"
        if self.tutorial == 1:
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
        return self.hint()

    # --- lines ----------------------------------------------------------

    def try_set(self, world: World, held_index: int, bait_id: str) -> str | None:
        if abs(self.speed) > 0.5:
            return "Idle the boat before you set."
        if not self.held:
            return "Every line you own is already in the water."
        if held_index < 0 or held_index >= len(self.held):
            return "No line selected."
        held = self.held[held_index]
        hooks = held.hooks
        have = self.bait.get(bait_id, 0)
        if have < hooks:
            return f"Need {hooks} {BAIT_BY_ID[bait_id].name.lower()}. You have {have}."
        fx, fz = math.sin(self.yaw), math.cos(self.yaw)
        length = line_length(hooks)
        x0 = self.x + fx * 5.0
        z0 = self.z + fz * 5.0
        x1 = x0 + fx * length
        z1 = z0 + fz * length
        samples = []
        shallow = False
        for i in range(8):
            t = i / 7
            px = x0 + (x1 - x0) * t
            pz = z0 + (z1 - z0) * t
            samples.append((px, pz))
            if not world.navigable(px, pz) and float(shore_sd_safe(world, px, pz)) >= -0.5:
                return "That line would climb the bank. Point toward open water."
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
        draft = SetLine(held.tier, bait_id, x0, z0, x1, z1, "open", [])
        for other in self.lines:
            if _seg_gap(draft, other) < 16.0:
                return "Too close to a line you already set."
        mx, mz = (x0 + x1) * 0.5, (z0 + z1) * 0.5
        zone = world.zone_at(mx, mz)
        if zone in ("landing", "shore"):
            return "The landing is a no-line zone."
        self.bait[bait_id] -= hooks
        self.held.pop(held_index)
        line_hooks = [Hook(True) for _ in range(hooks)]
        self.lines.append(SetLine(held.tier, bait_id, x0, z0, x1, z1, zone, line_hooks))
        line = self.lines[-1]
        self.preferred_bait = bait_id
        self.emit_quest_event({
            "type": "line.set",
            "lake_id": self.lake_id,
            "line_id": line.line_id,
            "zone_id": f"{self.lake_id}:{line.zone}",
            "tier_id": line.tier,
            "hook_count": len(line.hooks),
            "bait_id": line.bait,
            "game_minute": self.game_minutes,
            "active_game_minute": self.narrative.active_play_game_minutes,
        })
        from .world import zone_label
        self.toast(f"Line set on the {zone_label(zone).lower()}. {hooks} hooks, {BAIT_BY_ID[bait_id].name.lower()}.")
        return None

    def line_label(self, index: int) -> str:
        from .world import zone_label
        zone = self.lines[index].zone
        same = [i for i, ln in enumerate(self.lines) if ln.zone == zone]
        name = zone_label(zone)
        if len(same) == 1:
            return name
        return f"{name} {same.index(index) + 1}"

    def take_hook(self, line_index: int, hook_index: int) -> str | None:
        line = self.lines[line_index]
        hook = line.hooks[hook_index]
        if hook.catch is None:
            return "Nothing on that hook."
        if self.well_load() + hook.catch.weight > self.well_cap() + 1e-6:
            return "The livewell won't take that one."
        catch = hook.catch
        self.well.append(catch)
        self._emit_livewell_entry(catch, line)
        hook.catch = None
        hook.baited = False
        return None

    def take_all(self, line_index: int) -> str:
        line = self.lines[line_index]
        moved = 0
        left = 0
        for hook in line.hooks:
            if hook.catch is None:
                continue
            if self.well_load() + hook.catch.weight > self.well_cap() + 1e-6:
                left += 1
                continue
            catch = hook.catch
            self.well.append(catch)
            self._emit_livewell_entry(catch, line)
            hook.catch = None
            hook.baited = False
            moved += 1
        if moved == 0 and left:
            return "Livewell is full."
        if left:
            return f"Took {moved}. {left} stayed on the line."
        if moved == 0:
            return "Nothing to take."
        return f"Took {moved} into the livewell."

    def rebait(self, line_index: int) -> str | None:
        line = self.lines[line_index]
        need = line.bare_hooks()
        if need == 0:
            return "Nothing bare on that line."
        have = self.bait.get(line.bait, 0)
        if have < need:
            return f"Need {need} {BAIT_BY_ID[line.bait].name.lower()}. You have {have}."
        self.bait[line.bait] -= need
        for hook in line.hooks:
            if hook.catch is None and not hook.baited:
                hook.baited = True
        self.toast(f"Rebaited {need} hooks with {BAIT_BY_ID[line.bait].name.lower()}.")
        return None

    def pull_line(self, line_index: int) -> str | None:
        line = self.lines[line_index]
        fish = [h.catch for h in line.hooks if h.catch is not None]
        if self.well_load() + sum(c.weight for c in fish) > self.well_cap() + 1e-6:
            return "The livewell can't hold every fish on that line."
        for catch in fish:
            self.well.append(catch)
            self._emit_livewell_entry(catch, line)
        self.lines.pop(line_index)
        if self.bot_target_line_id == line.line_id:
            self.bot_target_line_id = None
        self.held.append(HeldLine(line.tier))
        self.toast("Line coiled in the boat.")
        return None

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
        total = round(sum(c.value() for c in self.well), 2)
        n = len(self.well)
        note = _buyer_line(self.well)
        self.well.clear()
        self._earn(total)
        self.toast(f"Sold {n} fish for {dollars(total)}.")
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
        bait = BAIT_BY_ID[bait_id]
        if self.bait_count() + DOZEN > self.box_cap():
            return "The bait box is full."
        if not self._spend(bait.price):
            return f"Need {dollars(bait.price)}."
        self.bait[bait_id] = self.bait.get(bait_id, 0) + DOZEN
        self.preferred_bait = bait_id
        self.toast(f"A dozen {bait.name.lower()}.")
        return None

    def buy_line(self, tier: str) -> str | None:
        if self.owned_lines() >= MAX_LINES:
            return f"Five lines is the limit on this lake."
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
        weather = weather_at(self.game_minutes)
        depth = float(world.depth(self.x, self.z))
        best_bait = "worm"
        best_score = -1.0
        best_sp = "bluegill"
        for bait in BAIT_BY_ID:
            rates = species_rates(zone, bait, hour, weather, depth,self.lake_id)
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
        return {
            "version": SAVE_VERSION,
            "lake_id":self.lake_id,"boat_id":self.boat_id,"owned_boats":self.owned_boats,
            "fuel_tanks":{key:round(value,6) for key,value in self.fuel_tanks.items()},
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
            "anchored": self.anchored,
            "motor": self.motor, "well_tier": self.well_tier, "box_tier": self.box_tier,
            "finder": self.finder, "light": self.light,
            "owned": self.owned, "look": self.look_paint,
            "journal": self.journal,
            "narrative_v1": self.narrative.to_json(),
            "tutorial": self.tutorial, "traveled": round(self.traveled, 1),
            "time_scale": self.time_scale, "muted": self.muted,
            "preferred_bait": self.preferred_bait,
            "hooked_total": self.hooked_total,
            "stamp": time.time(),
            "bot": {
                "phase": self.bot_phase,
                "x": round(self.bot_x, 2), "z": round(self.bot_z, 2),
                "yaw": round(self.bot_yaw, 4),
                "tx": round(self.bot_tx, 2), "tz": round(self.bot_tz, 2),
                "target_line_id": self.bot_target_line_id,
            },
        }

    def save(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.to_json()))
        tmp.replace(path)

    @classmethod
    def load(cls, path: Path, world: World) -> "State":
        raw = json.loads(path.read_text())
        if raw.get("version") != SAVE_VERSION:
            raise ValueError("save version")
        st = cls(rng=RNG(int(raw["seed"])))
        if raw.get("lake_id","briar")!=world.id:
            raise ValueError("save belongs to a different lake")
        st.boat_id = raw.get("boat_id","jon")
        if st.boat_id not in BOATS:
            raise ValueError("unknown saved boat")
        st.owned_boats = [key for key in raw.get("owned_boats",["jon"]) if key in BOATS]
        if st.boat_id not in st.owned_boats:
            st.owned_boats.append(st.boat_id)
        st.fuel_tanks = {key:max(0.0,min(BOATS[key].tank,float(value)))
                         for key,value in raw.get("fuel_tanks",{"jon":12.0}).items() if key in BOATS}
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
        st.x, st.z, st.yaw = float(raw["x"]), float(raw["z"]), float(raw["yaw"])
        st.anchored = bool(raw.get("anchored", False))
        st.motor = int(raw["motor"])
        st.well_tier = int(raw["well_tier"])
        st.box_tier = int(raw["box_tier"])
        st.finder = bool(raw["finder"])
        st.light = bool(raw["light"])
        st.owned = raw["owned"]
        st.look_paint = raw["look"]
        st.journal = raw["journal"]
        st.narrative = NarrativeState.from_json(raw.get("narrative_v1"))
        for sp in SPECIES:
            st.journal.setdefault(sp.id, {"count": 0, "best": 0.0, "zone": "", "bait": "", "band": ""})
        st.tutorial = int(raw.get("tutorial", 4))
        st.traveled = float(raw.get("traveled", 0))
        st.time_scale = int(raw.get("time_scale", 1))
        st.muted = bool(raw.get("muted", False))
        st.preferred_bait = raw.get("preferred_bait", "worm")
        st.hooked_total = int(raw.get("hooked_total", 0))
        st.stamp = float(raw.get("stamp", time.time()))
        raw_bot = raw.get("bot")
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
        return st


def shore_sd_safe(world: World, x: float, z: float) -> float:
    return float(world.shore_sd(x, z))


def saved_lake(path: Path) -> str:
    try:
        lake = json.loads(path.read_text()).get("lake_id","briar")
        return lake if lake in LAKES else "briar"
    except (OSError,ValueError):
        return "briar"


def clock(state: State) -> str:
    return clock_string(state.game_minutes)
