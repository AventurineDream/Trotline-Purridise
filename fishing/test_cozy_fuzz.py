"""V1-39: 10,000 seeded random actions in Cozy never take money, boats, lines, book progress,
Ripples or keepsakes away (06 §9, 02 §2.2).

The actions drive public State methods only, with no rendering. Money may fall only through
a purchase that succeeded, which must also show up in `spent`. Owned things may only be added.
"""
import json
import math
import random
import time
import unittest

from . import comfort
from .book import BOOK_STAGES
from .boat import BOATS
from .data import BAIT_BY_ID, LINE_TIERS, PAINT
from .sim import State
from .world import World

ACTIONS = 10_000
SEED = 39
# Purchases return None on success and only then move money with `spent`.
PURCHASES = {"buy_bait", "buy_line", "buy_motor", "buy_well", "buy_box", "buy_finder", "buy_light",
             "buy_paint", "buy_boat", "refuel", "buy_rowboat_trolling_motor", "charge_rowboat_battery"}


def _stage_threshold(count: int) -> int:
    """The count threshold of a book stage, so stages compare in order (not by name)."""
    return max(threshold for threshold, _stage in BOOK_STAGES if count >= threshold)


def _snapshot(state: State) -> dict:
    counts = {sid: int(record.get("count", 0)) for sid, record in state.journal.items()}
    return {
        "money": state.money,
        "spent": state.spent,
        "boats": set(state.owned_boats),
        "lines": len(state.held) + len(state.lines),
        "counts": counts,
        "stages": {sid: _stage_threshold(count) for sid, count in counts.items()},
        "ripples": set(state.narrative.ripples),
        "keepsakes": {json.dumps(row, sort_keys=True) for row in state.v2.get("keepsakes", [])},
    }


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
            return "buy_boat", lambda: state.buy_boat(boat, self.world)
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


class CozyInvariants(unittest.TestCase):
    def test_ten_thousand_random_cozy_actions_never_take_anything_away(self):
        world = World("briar")
        state = State.new(world, seed=SEED)
        self.assertEqual(comfort.mode(state.v2), "cozy")
        # A purse and an open-water spot, so fishing happens within the run.
        state.money = 300.0
        state.x, state.z, state.yaw, state.anchored = 300.0, 30.0, math.pi / 2, False
        driver = _Driver(state, world, random.Random(SEED))
        started = time.perf_counter()
        ran = {}
        for step in range(ACTIONS):
            name, action = driver.next_action()
            before = _snapshot(state)
            result = action()
            after = _snapshot(state)
            ran[name] = ran.get(name, 0) + 1
            context = f"step {step} action {name} result {result!r}"
            if after["money"] < before["money"] - 1e-9:
                # Only a successful purchase may reduce money, and it must be the amount spent.
                self.assertIn(name, PURCHASES, context)
                self.assertIsNone(result, context)
                self.assertAlmostEqual(after["spent"] - before["spent"], before["money"] - after["money"],
                                       places=2, msg=context)
            self.assertLessEqual(before["boats"], after["boats"], context)
            self.assertLessEqual(before["lines"], after["lines"], context)
            self.assertLessEqual(before["ripples"], after["ripples"], context)
            self.assertLessEqual(before["keepsakes"], after["keepsakes"], context)
            for sid, count in before["counts"].items():
                self.assertGreaterEqual(after["counts"][sid], count, context)
                self.assertLessEqual(before["stages"][sid], after["stages"][sid], context)
        elapsed = time.perf_counter() - started
        self.assertLess(elapsed, 60.0, f"fuzz took {elapsed:.1f}s")
        self.assertGreaterEqual(sum(ran.values()), ACTIONS)
        # Every action family must actually run, or the fuzz proves less than it claims.
        for name in ("advance", "take_hook", "try_set", "sell_all", "buy_bait", "buy_boat", "refuel",
                     "catnap", "toggle_sail", "take_all"):
            self.assertGreater(ran.get(name, 0), 0, name)
        self.assertEqual(comfort.mode(state.v2), "cozy")


if __name__ == "__main__":
    unittest.main()
