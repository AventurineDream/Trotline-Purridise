"""The headless pacing simulator (V1-44): an attentive player against 02 §1 and §15.

python -m fishing --pacing [--json=path]

The attentive player is a model, written down here so its numbers can be argued with:

- **Gear by stage.** The lines, motor, livewell and boat a player who buys what each
  chapter asks for has on reaching that stage (`STAGES`).
- **Where they fish.** They know which zones pay and which bait each wants (the depth
  finder, the book's rumours, Bot's reports) and drop each line at a typical place in a
  different zone, favouring water nearer the landing (`spots`).
- **How they fish.** From 06:00 they run every line in turn, rebait, and sell at the
  landing. A round takes as long as the drive (`ROUTE_DETOUR` over the boat's speed), and
  the next starts once the lines have soaked `MIN_SOAK_MIN`. The last round starts before
  22:00; the lines soak overnight. Bait bought comes off the day's money.
- **Real time.** The clock runs one game minute a real second while driving. Hauls, menus
  and talk freeze it. Waiting at the landing runs at `REAL["wait_scale"]`, the night at
  `REAL["night_scale"]`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import statistics

from . import bottools, calendar, skipperlook
from .data import BAIT_BY_ID, LINE_TIERS, SPECIES_BY_ID, fish_value
from .sim import HeldLine, State, species_rates
from .world import World

SEEDS = tuple(range(11, 26))
DAYS = 3                 # each seed fishes this many game days in a row
REFERENCE_WEATHER = "clear"
DAY_START, LAST_ROUND = 0, 16 * 60   # game minutes after 06:00
MIN_SOAK_MIN = 120
ROUTE_DETOUR = 1.25      # shorelines and islands: the route is longer than the straight line
SPREAD_M = 800.0         # how far the player will go for better water: value / (1 + d / SPREAD_M)
REAL = {
    "hook_s": 0.25,      # haul cadence at Normal speed (haul.py)
    "card_s": 2.0,       # reading a fish card
    "line_s": 6.0,       # open the check menu, rebait
    "landing_s": 20.0,   # sell the well, top up bait
    "wait_scale": 6,     # waiting at the landing between rounds
    "night_scale": 12,   # through the night
}


@dataclass(frozen=True)
class Stage:
    id: str
    lake: str
    band: tuple[float, float]  # $ per active game day, 02 §15.1
    lines: tuple[str, ...]     # line tiers the attentive player has set by then
    boat: str = "jon"
    motor: int = 0             # tiller motor index (data.MOTORS), for tiller boats
    well_tier: int = 0

    @property
    def midpoint(self) -> float:
        return (self.band[0] + self.band[1]) / 2


STAGES = (
    # The start: Grandmother's jon on its 6 hp, the starting line and a second one.
    Stage("start", "briar", (60, 120), ("std", "std")),
    # Chapter 2 asks for a premium line; the 9.9 hp and the 80 lb well come along.
    Stage("ch2", "cedar", (150, 300), ("prem", "std", "std"), motor=1, well_tier=1),
    Stage("ch3", "flathead", (300, 500), ("prem", "prem", "std", "std"), motor=2, well_tier=2),
    Stage("ch4", "crater", (450, 750), ("heavy", "prem", "prem", "std", "std"), motor=2, well_tier=2),
    # After the story: a utility skiff with six lines.
    Stage("post", "nebula", (700, 1100), ("heavy", "heavy", "heavy", "prem", "prem", "prem"),
          boat="deepv_skiff", well_tier=2),
)


# --- where the attentive player sets lines ---------------------------------------------

SAMPLES_PER_ZONE = 14


def _candidate_points(world, seed=7):
    """Deterministic sample points over the lake's water, grouped by zone (open water too),
    deep enough to set a line. The landing's own water is left to the dock."""
    import random
    rnd = random.Random(seed)
    xs = [x for _name, x, _z, _r in world.zones]
    zs = [z for _name, _x, z, _r in world.zones]
    lo_x, hi_x, lo_z, hi_z = min(xs) - 320, max(xs) + 320, min(zs) - 320, max(zs) + 320
    groups = {}
    for _ in range(6000):
        x, z = rnd.uniform(lo_x, hi_x), rnd.uniform(lo_z, hi_z)
        if not world.navigable(x, z) or float(world.depth(x, z)) < 1.3:
            continue
        zone = world.zone_at(x, z)
        if zone == "landing":
            continue
        bucket = groups.setdefault(zone, [])
        if len(bucket) < SAMPLES_PER_ZONE:
            bucket.append((x, z))
    return groups


def _pose(world, x, z, bait, tier):
    probe = State.new(world, seed=1)
    for k in range(36):
        probe.x, probe.z, probe.yaw, probe.speed = x, z, k * math.tau / 36.0, 0.0
        probe.lines.clear()
        probe.held = [HeldLine(tier)]
        probe.bait[bait] = 99
        if not probe.try_set(world, 0, bait):
            return probe.x, probe.z, probe.yaw
    return None


def expected_day_value(world, lake, x, z, bait, silent=False) -> float:
    """Dollars a hook at (x, z) with this bait would earn in a game day, by the rate model:
    each hour, every species' bite rate times its price at its mean weight."""
    zone = world.zone_at(x, z)
    depth = float(world.depth(x, z))
    total = 0.0
    for hour in range(24):
        cold = bottools.cold_layer_m(lake, hour + 0.5, REFERENCE_WEATHER)
        tool = bottools.ToolState(cold, False, False, silent)
        rates = species_rates(zone, bait, hour + 0.5, REFERENCE_WEATHER, depth, lake, tool=tool)
        for sid, rate in rates.items():
            if rate > 0:
                sp = SPECIES_BY_ID[sid]
                weight = sp.min_lb + (sp.max_lb - sp.min_lb) * 0.39  # E[u**1.55]
                total += rate * fish_value(sid, weight, 1.0)
    return total


def baits_for(lake):
    return [b for b, row in BAIT_BY_ID.items()
            if row.price and ({"all", lake} & set(row.sold_at))]


def spots(world, lake, count, silent=False, tiers=("std",), dock=None):
    """The attentive player's spots. They know which zones pay and which bait each wants
    (the depth finder, the book's rumours, Bot's reports) but drop the line at a typical
    place in the zone, not the best one: the median of a handful of sampled places, with
    the best bait for it. One line per zone, best zones first."""
    ranked = []
    for zone, points in sorted(_candidate_points(world).items()):
        options = []
        for x, z in points:
            value, bait = max(((expected_day_value(world, lake, x, z, b, silent), b)
                               for b in baits_for(lake)), default=(0.0, None))
            if bait is not None and value > 0:
                options.append((value, bait, x, z))
        options.sort(reverse=True)
        middle = len(options) // 2
        # Out from the median until a line fits.
        order = sorted(range(len(options)), key=lambda i: (abs(i - middle), i))
        for index in order:
            value, bait, x, z = options[index]
            if _pose(world, x, z, bait, tiers[0]) is not None:
                ranked.append((value, zone, bait, x, z))
                break
    dock = dock or world.dock
    ranked.sort(key=lambda r: -r[0] / (1.0 + math.dist(dock, (r[3], r[4])) / SPREAD_M))
    return ranked[:count]


def route(dock, points):
    """Nearest-first from the landing and back: the order and the metres driven."""
    order, here, left, metres = [], dock, list(range(len(points))), 0.0
    while left:
        nxt = min(left, key=lambda i: math.dist(here, points[i]))
        metres += math.dist(here, points[nxt])
        here = points[nxt]
        order.append(nxt)
        left.remove(nxt)
    metres += math.dist(here, dock)
    return order, metres * ROUTE_DETOUR


# --- a game day of fishing --------------------------------------------------------------

@dataclass
class DayResult:
    gross: float
    bait_cost: float
    fish: int
    rounds: int
    real_s: float
    days: int = 1
    species: set = field(default_factory=set)

    @property
    def net(self) -> float:
        return (self.gross - self.bait_cost) / self.days

    @property
    def real_min_per_day(self) -> float:
        return self.real_s / 60.0 / self.days


def _advance(state, minutes):
    """The world's clock and bites over whole minutes: hour spans, then one short span."""
    hours, rest = divmod(int(minutes), 60)
    if hours:
        state._advance_hours(hours, toast=False)
    if rest:
        before = state.game_minutes
        state._one_span(rest / 60.0, announce=False)
        state.game_minutes += float(rest)
        if int(state.game_minutes // calendar.WEEK_MINUTES) != int(before // calendar.WEEK_MINUTES):
            calendar.ensure_plans(state)


def _real_wait(clock, minutes):
    """Real seconds to wait `minutes` from `clock`: at the waiting scale by day, the night
    scale from the last round until 06:00."""
    real, t, stop = 0.0, clock, clock + minutes
    while t < stop:
        into_day = t % 1440
        if into_day >= LAST_ROUND:
            piece = min(stop, t - into_day + 1440) - t
            real += piece / REAL["night_scale"]
        else:
            piece = min(stop, t - into_day + LAST_ROUND) - t
            real += piece / REAL["wait_scale"]
        t += piece
    return real


def _rig(stage: Stage, world, seed):
    state = State.new(world, seed=seed)
    state.money = 0.0
    state.hooked_total = 1  # past the new game's first-bite nudge
    state.boat_id = stage.boat
    if stage.boat not in state.owned_boats:
        state.owned_boats.append(stage.boat)
    state.motor = stage.motor
    state.well_tier = stage.well_tier
    for key in list(state.bait):
        state.bait[key] = 0
    return state


def fish_days(stage: Stage, seed: int, world=None, picks=None, days=DAYS) -> DayResult:
    """`days` game days of the attentive player's routine, from 06:00 on day one."""
    world = world or World(stage.lake)
    state = _rig(stage, world, seed)
    silent = "silent" in state.boat.traits
    picks = picks or spots(world, stage.lake, len(stage.lines), silent, ("heavy",))
    state.held = [HeldLine(tier) for tier in stage.lines[:len(picks)]]
    state.lines.clear()
    stocked = {}
    for index, (_value, _zone, bait, x, z) in enumerate(picks):
        pose = _pose(world, x, z, bait, stage.lines[index])
        if pose is None:
            continue
        state.x, state.z, state.yaw = pose
        state.speed = 0.0
        state.bait[bait] = state.bait.get(bait, 0) + 999
        stocked[bait] = stocked.get(bait, 0) + 999
        if state.try_set(world, 0, bait):
            state.bait[bait] -= 999
            stocked[bait] -= 999
    state.anchored = True
    speed = state.max_speed()
    _order, metres = route(world.dock, [(line.x0, line.z0) for line in state.lines])
    round_min = max(1, int(round(metres / speed)))  # 1 game minute a real second at 1x
    caught, rounds, real_s, species = 0, 0, 0.0, set()
    clock, next_start, end = 0, DAY_START, days * 1440
    while next_start < end:
        if next_start % 1440 >= LAST_ROUND:  # too late for a round: the next morning
            next_start = (next_start // 1440 + 1) * 1440 + DAY_START
            continue
        _advance(state, next_start - clock)
        real_s += _real_wait(clock, next_start - clock)
        clock = next_start
        # The round: drive it (the clock runs) and check each line on the way (frozen).
        _advance(state, round_min)
        clock += round_min
        real_s += round_min + REAL["landing_s"]
        for index in range(len(state.lines)):
            fish = [hook.catch for hook in state.lines[index].hooks if hook.catch is not None]
            caught += len(fish)
            species.update(f.species for f in fish)
            real_s += (REAL["line_s"] + len(state.lines[index].hooks) * REAL["hook_s"]
                       + len(fish) * REAL["card_s"])
            state.take_all(index)
            if any(hook.catch is not None for hook in state.lines[index].hooks):
                state.sell_all()  # a full well: unload on the way
                state.take_all(index)
            state.rebait(index)
        state.sell_all()
        rounds += 1
        next_start = max(clock, next_start + MIN_SOAK_MIN)
    real_s += _real_wait(clock, max(0, end - clock))
    # The last night's soak is the next day's business; settle the bait.
    used = {bait: stocked[bait] - state.bait.get(bait, 0) for bait in stocked}
    cost = sum(count / 12.0 * BAIT_BY_ID[bait].price for bait, count in used.items())
    result = DayResult(state.money, cost, caught, rounds, real_s, days, species)
    result.round_min = round_min
    return result


def stage_income(stage: Stage, seeds=SEEDS) -> dict:
    world = World(stage.lake)
    probe = _rig(stage, world, 1)
    silent = "silent" in probe.boat.traits
    picks = spots(world, stage.lake, len(stage.lines), silent, ("heavy",))
    runs = [fish_days(stage, seed, world, picks) for seed in seeds]
    nets = sorted(run.net for run in runs)
    median = statistics.median(nets)
    return {
        "stage": stage.id, "lake": stage.lake, "lines": list(stage.lines), "boat": stage.boat,
        "speed_m_s": round(probe.max_speed(), 2),
        "spots": [{"zone": zone, "bait": bait, "expected_per_hook": round(value, 2),
                   "metres_from_landing": round(math.dist(world.dock, (x, z)))}
                  for value, zone, bait, x, z in picks],
        "net_per_day": round(median, 1), "low": round(nets[0], 1), "high": round(nets[-1], 1),
        "fish_per_day": round(statistics.median(run.fish / run.days for run in runs), 1),
        "rounds_per_day": round(statistics.median(run.rounds / run.days for run in runs), 1),
        "real_min_per_day": round(statistics.median(run.real_min_per_day for run in runs), 1),
        "drive_min_per_day": round(statistics.median(run.rounds / run.days * run.round_min for run in runs), 1),
        "new_species_per_day": round(statistics.median(len(run.species) / run.days for run in runs), 1),
        "band": list(stage.band), "in_band": stage.band[0] <= median <= stage.band[1],
    }


# --- the first catch from a new game ------------------------------------------------------

READ_KEY_S = 0.4  # pressing on after a bubble


def _bubbles(text):
    if isinstance(text, str):
        return [text]
    if isinstance(text, (list, tuple)):
        return [str(t) for t in text]
    return []


def _read_dialogue(session, choose=0) -> float:
    """Read the conversation on screen to its end, as the game shows it: each bubble at
    the reading pace of reading.py. Returns real seconds."""
    from .botidentity import format_text
    from .game import Keys
    from .reading import reading_seconds
    real = 0.0
    content = session._npc_content
    guard = 0
    while session.ui.mode == "dialogue" and session.conversation is not None and guard < 200:
        guard += 1
        node = session.conversation.node(content)
        for bubble in _bubbles(node.get("text")):
            real += reading_seconds(format_text(bubble, session.state)) + READ_KEY_S
        if "choices" in node:
            real += 2.0  # choosing
            session.tick(Keys(pressed={str(choose + 1)}), 0.05)
        else:
            session.tick(Keys(pressed={"c"}), 0.05)
    return real


def _first_line_spot(state, world):
    """The nearest legal first line to the slip, as the tutorial asks: a short drive out."""
    slip = world.slip
    best = None
    for radius in (60, 70, 80, 90, 100, 110):
        for k in range(24):
            angle = k * math.tau / 24
            x, z = slip.ox + radius * math.sin(angle), slip.oz + radius * math.cos(angle)
            if not world.navigable(x, z):
                continue
            probe = State.new(world, seed=1)
            probe.x, probe.z, probe.yaw, probe.speed = x, z, angle, 0.0
            if probe.try_set(world, 0, "worm") is None:
                return x, z, angle, radius
    return best


def first_catch(seed: int) -> dict:
    """Real seconds from "New morning" to the first fish card, for a new player who reads
    every bubble, drives out to set the line the tutorial asks for, anchors, runs the clock
    at 3x (one press of T, as the tutorial suggests) and checks the line once it bites."""
    import tempfile
    from pathlib import Path
    from .game import Keys, Session
    from .sim import RNG
    with tempfile.TemporaryDirectory(prefix="trotline-pacing-") as folder:
        world = World("briar")
        session = Session(world, Path(folder) / "save.json", State.new(world, seed=seed), False)
        session.ui.mode, session.ui.new_mode_i = "new_mode", 0
        session.tick(Keys(pressed={"return"}), 0.05)
        session.ui.skipper_i = len(skipperlook.ROWS) - 1  # the creator: keep the default look, Done
        session.tick(Keys(pressed={"return"}), 0.05)
        state, world = session.state, session.world
        state.rng = RNG(seed)
        # The creator: a look down the rows and a turn of the card, then Done. A player who
        # dresses at length is lingering by choice, as with the pause menu, so the budget counts a glance.
        steps = {"choose a pace": 4.0, "dress the Skipper": 20.0}
        steps["arrival scenes"] = _read_dialogue(session)
        spot = _first_line_spot(state, world)
        if spot is None:
            raise AssertionError("no legal first line near the Briar landing")
        x, z, yaw, radius = spot
        drive = radius * ROUTE_DETOUR / state.max_speed()
        _advance(state, round(drive))
        state.x, state.z, state.yaw, state.speed = x, z, yaw, 0.0
        steps["drive out"] = drive
        error = state.try_set(world, 0, "worm")
        if error:
            raise AssertionError(error)
        steps["set the line"] = 8.0
        session.tick(Keys(), 0.05)
        steps["scenes after the line"] = _read_dialogue(session)
        state.anchored = True
        state.speed = state.throttle = state.throttle_setting = 0.0
        state.time_scale = 3
        steps["anchor, T"] = 2.0
        waited, line = 0.0, state.lines[0]
        while not any(hook.catch is not None for hook in line.hooks) and waited < 3600:
            session.tick(Keys(), 0.5)
            waited += 0.5
            if session.ui.mode == "dialogue":
                steps["scenes while waiting"] = steps.get("scenes while waiting", 0.0) + _read_dialogue(session)
            session.ui.mode = "play" if session.ui.mode != "dialogue" else session.ui.mode
            state.anchored = True
        steps["wait for a bite"] = waited
        first = next((i for i, hook in enumerate(line.hooks) if hook.catch is not None), len(line.hooks))
        steps["haul to the fish"] = 3.0 + (first + 1) * REAL["hook_s"] + REAL["card_s"]
        species = line.hooks[first].catch.species if first < len(line.hooks) else None
    total = sum(steps.values())
    return {"seed": seed, "seconds": round(total, 1), "species": species,
            "steps": {k: round(v, 1) for k, v in steps.items()}}


# --- how often the game speaks up -------------------------------------------------------

# No spec figure: V1-44's own limits for the first game day, the busiest by design (every
# species is new, so most catches bring a book prompt as well as the bite notice).
PROMPTS_PER_MIN_MAX = 2.0   # toasts a real minute, on average
BOT_LINES_PER_MIN_MAX = 0.5  # Bot's own lines; before V1-44 he said "Fish on" at every bite (0.68)


def prompt_density(seed: int, game_hours: int = 24) -> dict:
    """A new game's first game day in a real Session: the prologue, the first line, Bot out,
    then the attentive routine (two lines, checked about every three game hours, waiting at
    3x). Every toast is counted, and Bot's lines separately, per real minute of play."""
    import tempfile
    from pathlib import Path
    from .game import Keys, Session
    from .sim import RNG
    shown = []
    original = State.toast
    watched = []  # the session's own state: probes and scratch states don't count

    def toast(self, text, seconds=4.8):
        if watched and self is watched[0]:
            shown.append(str(text))
        return original(self, text, seconds)

    State.toast = toast
    try:
        with tempfile.TemporaryDirectory(prefix="trotline-prompts-") as folder:
            world = World("briar")
            session = Session(world, Path(folder) / "save.json", State.new(world, seed=seed), False)
            session.ui.mode, session.ui.new_mode_i = "new_mode", 0
            session.tick(Keys(pressed={"return"}), 0.05)
            session.ui.skipper_i = len(skipperlook.ROWS) - 1  # the creator: keep the default look, Done
            session.tick(Keys(pressed={"return"}), 0.05)
            state, world = session.state, session.world
            state.rng = RNG(seed)
            watched.append(state)
            shown.extend(text for text, _ttl in state.toasts)  # what the new game opened with
            real = _read_dialogue(session)
            x, z, yaw, _radius = _first_line_spot(state, world)
            state.x, state.z, state.yaw, state.speed = x, z, yaw, 0.0
            state.try_set(world, 0, "worm")
            real += 30.0
            session.tick(Keys(), 0.05)
            real += _read_dialogue(session)
            session.tick(Keys(pressed={"b"}), 0.05)  # Bot out
            state.anchored, state.time_scale = True, 3
            start = state.game_minutes
            next_check = start + 180
            while state.game_minutes < start + game_hours * 60:
                session.tick(Keys(), 1.0)
                real += 1.0
                if session.ui.mode == "dialogue":
                    real += _read_dialogue(session)
                if session.ui.mode not in ("play", "dialogue"):
                    session.ui.mode = "play"
                state.anchored = True
                if state.game_minutes >= next_check:
                    for index in range(len(state.lines)):
                        state.take_all(index)
                        state.rebait(index)
                    real += 30.0
                    next_check = state.game_minutes + 180
    finally:
        State.toast = original
    minutes = real / 60.0
    bot = [t for t in shown if t.startswith("Bot")]
    return {"seed": seed, "real_min": round(minutes, 1), "toasts": len(shown), "bot_lines": len(bot),
            "toasts_per_min": round(len(shown) / minutes, 2), "bot_per_min": round(len(bot) / minutes, 2),
            "shown": shown}
