"""V1-39: 10,000 seeded random actions in Cozy never take money, boats, lines, book progress,
Ripples or keepsakes away (06 §9, 02 §2.2).

The actions drive public State methods only, with no rendering. Money may fall only through
a purchase that succeeded, which must also show up in `spent`. Owned things may only be added.
The run starts from a save that already holds every protected category, so each check has
something to protect. A guard asserts that, so a refactor can't make the test vacuous silently.
"""
import json
import math
import random
import unittest

from . import comfort
from .book import BOOK_STAGES
from .boat import BOATS
from .content import load_content_v2
from .data import BAIT_BY_ID, LAKE_SPECIES_IDS, LINE_TIERS, PAINT
from .narrative import RIPPLE_BY_QUEST
from .sim import State
from .world import World

ACTIONS = 10_000
SEED = 39
# Purchases return None on success and only then move money with `spent`.
PURCHASES = {"buy_bait", "buy_line", "buy_motor", "buy_well", "buy_box", "buy_finder", "buy_light",
             "buy_paint", "buy_boat", "refuel", "buy_rowboat_trolling_motor", "charge_rowboat_battery"}
# Owned at the start, beyond the starter Jon. Each is a real BOATS id.
SEEDED_BOATS = ("dory", "log_raft", "pontoon")
# Book counts at the start, by briar species: stage 0 (rumor) through "mastered". The
# near-threshold counts (2 and 9) let one hooked fish raise a stage during the run.
SEEDED_COUNTS = (12, 5, 3, 2, 9, 0)
# Story chapters finished at the start, so later boats are for sale at the landing.
SEEDED_CHAPTERS = [1, 2, 3, 4, 5]
SEEDED_MONEY = 5000.0


def _stage_threshold(count: int) -> int:
    """The count threshold of a book stage, so stages compare in order (not by name)."""
    return max(threshold for threshold, _stage in BOOK_STAGES if count >= threshold)


def _snapshot(state: State) -> dict:
    counts = {sid: int(record.get("count", 0)) for sid, record in state.journal.items()}
    ripples = set(state.narrative.ripples) | {("v2", rid) for rid in state.v2.get("ripples_v2", [])}
    return {
        "money": state.money,
        "spent": state.spent,
        "boats": set(state.owned_boats),
        "lines": len(state.held) + len(state.lines),
        "counts": counts,
        "stages": {sid: _stage_threshold(count) for sid, count in counts.items()},
        "ripples": ripples,
        "keepsakes": {json.dumps(row, sort_keys=True) for row in state.v2.get("keepsakes", [])},
    }


def _violations(before: dict, after: dict, name: str, result) -> list:
    """Every way one action broke an invariant, as readable strings (empty when it is clean)."""
    problems = []
    if after["money"] < before["money"] - 1e-9:
        drop = round(before["money"] - after["money"], 2)
        if name not in PURCHASES:
            problems.append(f"{name} took ${drop} without a purchase")
        elif result is not None:
            problems.append(f"{name} took ${drop} but reported {result!r}")
        elif abs((after["spent"] - before["spent"]) - drop) > 0.01:
            problems.append(f"{name} took ${drop} without the same amount in spent")
    for boat in sorted(before["boats"] - after["boats"]):
        problems.append(f"{name} removed owned boat {boat}")
    if after["lines"] < before["lines"]:
        problems.append(f"{name} removed a line ({before['lines']} -> {after['lines']})")
    for rid in sorted(map(str, before["ripples"] - after["ripples"])):
        problems.append(f"{name} removed Ripple {rid}")
    for kid in sorted(before["keepsakes"] - after["keepsakes"]):
        problems.append(f"{name} removed keepsake {kid}")
    for sid, count in before["counts"].items():
        if after["counts"].get(sid, 0) < count:
            problems.append(f"{name} lowered the count of {sid} ({count} -> {after['counts'][sid]})")
        if after["stages"].get(sid, 0) < before["stages"][sid]:
            problems.append(f"{name} lowered the book stage of {sid}")
    return problems


def _seeded_state(world: World) -> State:
    """A Cozy save holding every protected category, written the way the game writes it."""
    state = State.new(world, seed=SEED)
    state.money = SEEDED_MONEY
    state.x, state.z, state.yaw, state.anchored = 300.0, 30.0, math.pi / 2, False
    content = load_content_v2()
    # Owned boats, recorded as buy_boat records a purchase.
    for boat_id in SEEDED_BOATS:
        state.owned_boats.append(boat_id)
        state.fuel_tanks[boat_id] = BOATS[boat_id].tank
    state.v2["story"]["completed_chapters"] = list(SEEDED_CHAPTERS)
    # Ripples: the V3 list by quest, and the v2 ledger that apply_reward writes.
    state.narrative.ripples = list(RIPPLE_BY_QUEST.values())[:3]
    state.v2["ripples_v2"] = sorted(content.ripples)[:2]
    # Keepsakes are id strings, as apply_reward appends them.
    state.v2["keepsakes"] = sorted(content.keepsakes)[:2]
    # Book counts across the stages, on species this lake's landing sells fish for.
    for sid, count in zip(LAKE_SPECIES_IDS["briar"], SEEDED_COUNTS):
        state.journal[sid]["count"] = count
    return state


class _Driver:
    """Chooses one random action; indices always point at real objects.

    Weights keep the boat on the water: fishing, driving and time dominate, while
    purchases, tows and boat changes (which park the boat at the landing) stay rare.
    """

    WEIGHTS = {"time": 0.16, "drive": 0.18, "set": 0.06, "line": 0.20, "sell": 0.06,
               "buy": 0.12, "misc": 0.22}

    def __init__(self, state: State, world: World, rng: random.Random):
        self.state = state
        self.world = world
        self.rng = rng
        self.species = list(state.journal)
        self.baits = list(BAIT_BY_ID)
        self.tiers = list(LINE_TIERS)
        self.boats = list(BOATS)
        self.slots = list(PAINT)
        self.categories = list(self.WEIGHTS)
        self.weights = [self.WEIGHTS[c] for c in self.categories]

    def _pick(self, values):
        return values[self.rng.randrange(len(values))]

    def next_action(self):
        """Return (name, callable) for one action."""
        category = self.rng.choices(self.categories, self.weights)[0]
        return getattr(self, "_" + category)()

    def _time(self):
        state, rng = self.state, self.rng
        if rng.random() < 0.3:
            minutes = rng.randint(1, 90)
            return "advance_bulk", lambda: state.advance_bulk(minutes)
        dt, frozen = rng.uniform(0.0, 20.0), rng.random() < 0.1
        return "advance", lambda: state.advance(dt, frozen)

    def _drive(self):
        rng = self.rng
        dt = rng.uniform(0.05, 1.0)
        throttle = rng.uniform(0.2, 1.0) if rng.random() < 0.6 else rng.uniform(-1, 1)
        steer = rng.uniform(-1, 1)
        return "drive", lambda: self.state.drive(dt, throttle, steer, self.world, player_controlled=True)

    def _set(self):
        state, rng = self.state, self.rng
        index = rng.randrange(len(state.held) + 1)
        sections = (["worm"] if rng.random() < 0.6
                    else [self._pick(self.baits) for _ in range(rng.randint(1, 3))])

        def set_line():
            # Setting needs the boat idle, so coast to a stop first, as a player would.
            for _ in range(60):
                if abs(state.speed) <= 0.5:
                    break
                state.drive(0.5, 0.0, 0.0, self.world, idle=True, player_controlled=True)
            return state.try_set(self.world, index, sections)
        return "try_set", set_line

    def _line(self):
        state, rng = self.state, self.rng
        if not state.lines:
            return "advance", lambda: state.advance(1.0, False)
        line = rng.randrange(len(state.lines))
        hook = rng.randrange(len(state.lines[line].hooks))
        roll = rng.random()
        if roll < 0.35:
            disposition = self._pick(("keep", "release", None))
            return "take_hook", lambda: state.take_hook(line, hook, disposition)
        if roll < 0.55:
            return "take_all", lambda: state.take_all(line)
        if roll < 0.7:
            return "rebait", lambda: state.rebait(line)
        if roll < 0.8:
            return "toggle_catch_disposition", lambda: state.toggle_catch_disposition(line, hook)
        if roll < 0.9:
            return "pull_line", lambda: state.pull_line(line)
        return "use_chime", lambda: state.use_chime(self.world)

    def _sell(self):
        state, rng = self.state, self.rng
        if state.well and rng.random() < 0.5:
            index = rng.randrange(len(state.well))
            if rng.random() < 0.5:
                return "toggle_treasured", lambda: state.toggle_treasured(index)
            return "sell_index", lambda: state.sell_index(index)
        return "sell_all", state.sell_all

    def _buy(self):
        state, rng = self.state, self.rng
        roll = rng.random()
        if roll < 0.3:
            bait = self._pick(self.baits)
            return "buy_bait", lambda: state.buy_bait(bait)
        if roll < 0.5:
            tier = self._pick(self.tiers)
            return "buy_line", lambda: state.buy_line(tier)
        if roll < 0.6:
            slot = self._pick(self.slots)
            pid = self._pick([item[0] for item in PAINT[slot]])
            return "buy_paint", lambda: state.buy_paint(slot, pid)
        if roll < 0.7:
            return "refuel", state.refuel
        if roll < 0.75:
            boat = self._pick(self.boats)

            def change_boat():
                # Boats change only at the landing: lower the sail, coast to a stop, then tow in
                # (free in Cozy).
                if state.sail_raised:
                    state.toggle_sail()
                for _ in range(60):
                    state.drive(0.5, 0.0, 0.0, self.world, idle=True, player_controlled=True)
                    if abs(state.speed) <= 0.5 and abs(state.throttle_setting) <= 0.02:
                        break
                state.tow_to_landing(self.world)
                return state.buy_boat(boat, self.world)
            return "buy_boat", change_boat
        options = (("buy_motor", state.buy_motor), ("buy_well", state.buy_well),
                   ("buy_box", state.buy_box), ("buy_finder", state.buy_finder),
                   ("buy_light", state.buy_light),
                   ("buy_rowboat_trolling_motor", state.buy_rowboat_trolling_motor),
                   ("charge_rowboat_battery", state.charge_rowboat_battery))
        return self._pick(options)

    def _misc(self):
        state, rng = self.state, self.rng
        roll = rng.random()
        if roll < 0.3:
            return "toggle_sail", state.toggle_sail
        if roll < 0.55:
            return "catnap", lambda: state.catnap(self.world)
        if roll < 0.6:
            return "tow_to_landing", lambda: state.tow_to_landing(self.world)
        if roll < 0.8:
            species = self._pick(self.species)
            return "set_shiny_tracker", lambda: state.set_shiny_tracker(species)
        return "cycle_scale", state.cycle_scale


def _snap(**changes) -> dict:
    """A hand-made snapshot: one clean baseline, changed where a test says so."""
    base = {"money": 100.0, "spent": 0.0, "boats": {"jon", "dory"}, "lines": 2,
            "counts": {"bluegill": 5}, "stages": {"bluegill": 5},
            "ripples": {"ripple_01"}, "keepsakes": {"\"reed knot\""}}
    base.update(changes)
    return base


class ViolationChecker(unittest.TestCase):
    """The per-step checker must be able to fail: each protected thing removed is reported."""

    def test_a_clean_step_reports_nothing(self):
        before = _snap()
        self.assertEqual(_violations(before, _snap(), "advance", None), [])
        self.assertEqual(_violations(before, _snap(boats={"jon", "dory", "sail"}), "buy_boat", None), [])

    def test_a_removed_boat_is_reported(self):
        self.assertIn("removed owned boat dory",
                      " ".join(_violations(_snap(), _snap(boats={"jon"}), "buy_boat", None)))

    def test_a_removed_line_is_reported(self):
        self.assertIn("removed a line", " ".join(_violations(_snap(), _snap(lines=1), "pull_line", None)))

    def test_a_removed_ripple_is_reported(self):
        self.assertIn("removed Ripple ripple_01",
                      " ".join(_violations(_snap(), _snap(ripples=set()), "toggle_sail", None)))

    def test_a_removed_keepsake_is_reported(self):
        self.assertIn("removed keepsake",
                      " ".join(_violations(_snap(), _snap(keepsakes=set()), "toggle_sail", None)))

    def test_a_lowered_book_stage_is_reported(self):
        after = _snap(counts={"bluegill": 5}, stages={"bluegill": 3})
        self.assertIn("lowered the book stage of bluegill",
                      " ".join(_violations(_snap(), after, "take_hook", None)))

    def test_money_falling_outside_a_purchase_is_reported(self):
        self.assertIn("took $10.0 without a purchase",
                      " ".join(_violations(_snap(), _snap(money=90.0), "advance", None)))

    def test_money_falling_for_a_purchase_that_failed_is_reported(self):
        self.assertTrue(_violations(_snap(), _snap(money=90.0, spent=10.0), "buy_bait", "Need $5."))

    def test_a_successful_purchase_that_moves_money_is_allowed(self):
        self.assertEqual(_violations(_snap(), _snap(money=90.0, spent=10.0), "buy_bait", None), [])


class CozyInvariants(unittest.TestCase):
    def test_ten_thousand_random_cozy_actions_never_take_anything_away(self):
        world = World("briar")
        state = _seeded_state(world)
        self.assertEqual(comfort.mode(state.v2), "cozy")
        # The guard: every protected category is non-empty before the first action.
        start = _snapshot(state)
        self.assertGreaterEqual(len(start["boats"]), 3)
        self.assertGreaterEqual(len(start["ripples"]), 1)
        self.assertGreaterEqual(len(start["keepsakes"]), 1)
        self.assertTrue(any(stage > 0 for stage in start["stages"].values()))
        driver = _Driver(state, world, random.Random(SEED))
        ran = {}
        boats_bought = stage_rises = 0
        for step in range(ACTIONS):
            name, action = driver.next_action()
            before = _snapshot(state)
            result = action()
            after = _snapshot(state)
            ran[name] = ran.get(name, 0) + 1
            problems = _violations(before, after, name, result)
            self.assertEqual(problems, [], f"step {step} action {name} result {result!r}")
            if name == "buy_boat" and result is None and after["boats"] > before["boats"]:
                boats_bought += 1
            stage_rises += sum(after["stages"][sid] > before["stages"][sid] for sid in before["stages"])
        self.assertGreaterEqual(sum(ran.values()), ACTIONS)
        # The run must grow things, or it proves less than it claims.
        self.assertGreaterEqual(boats_bought, 1, "no boat was bought during the run")
        self.assertGreaterEqual(stage_rises, 1, "no book stage rose during the run")
        # Every action family must actually run, or the fuzz proves less than it claims.
        for name in ("advance", "take_hook", "try_set", "sell_all", "buy_bait", "buy_boat", "refuel",
                     "catnap", "toggle_sail", "take_all"):
            self.assertGreater(ran.get(name, 0), 0, name)
        self.assertEqual(comfort.mode(state.v2), "cozy")


if __name__ == "__main__":
    unittest.main()
