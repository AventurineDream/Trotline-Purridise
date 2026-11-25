"""Pulling a line puts the bait still on its unused hooks back in the bait box.

Covers a set-then-pull round trip through try_set, mixed used and unused hooks across
bait sections, the bait box's capacity filling in hook order, free bait from the
Ember Hotpot perk (never refunded unless paid for later), a pull the livewell refuses
and then allows, and the refunded counts surviving save and load.
"""
import math
import tempfile
import unittest
from pathlib import Path

from . import comfort
from .data import DISHES
from .sim import Catch, Hook, SetLine, State
from .world import World


def fish(disposition="auto"):
    catch = Catch("bluegill", 0.4, 0.9, 1.0, "open", "worm", 3, "briar")
    catch.disposition = disposition
    return catch


class BaitComesBackOnPull(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World()

    def setUp(self):
        self.state = State.new(self.world, seed=163)
        self.state.lines = []
        self.state.well = []
        self.state.bait = {}

    @staticmethod
    def line(sections, hooks):
        return SetLine("std", sections, 0, 10, 0, 30, "open", hooks)

    def coil_toast(self):
        return [text for text, _ in self.state.toasts if text.startswith("Line coiled")][-1]

    def test_setting_then_pulling_an_untouched_line_returns_every_bait(self):
        self.state.bait = {"worm": 24, "liver": 12, "shad": 12}
        before = dict(self.state.bait)
        # Any legal open-water spot: try_set alone decides what counts as legal.
        for radius in range(40, 400, 20):
            for step in range(16):
                angle = step * math.tau / 16
                self.state.x, self.state.z = radius * math.sin(angle), radius * math.cos(angle)
                if self.state.try_set(self.world, 0, ["worm", "liver", "shad"]) is None:
                    break
            if self.state.lines:
                break
        self.assertTrue(self.state.lines, "no legal place to set a line")
        self.assertLess(sum(self.state.bait.values()), sum(before.values()))
        self.assertIsNone(self.state.pull_line(0))
        self.assertEqual(self.state.bait, before)

    def test_only_hooks_still_baited_and_empty_come_back_by_their_section(self):
        hooks = [Hook(True) for _ in range(12)]  # sections: 0-3 worm, 4-7 liver, 8-11 shad
        hooks[0] = Hook(False)                  # bait taken by a nibble
        hooks[1] = Hook(False, fish())          # a fish on: its bait is spent
        hooks[5] = Hook(False, fish("release"))
        hooks[9] = Hook(False)
        hooks[10] = Hook(False)
        self.state.lines = [self.line(["worm", "liver", "shad"], hooks)]
        self.assertIsNone(self.state.pull_line(0))
        self.assertEqual(self.state.bait, {"worm": 2, "liver": 3, "shad": 2})
        self.assertEqual(self.coil_toast(), "Line coiled in the boat. 2 nightcrawlers, 3 chicken liver, "
                                            "2 cut shad back in the bait box.")

    def test_a_line_with_no_bait_left_returns_nothing(self):
        self.state.lines = [self.line("worm", [Hook(False) for _ in range(12)])]
        self.state.pull_line(0)
        self.assertEqual(self.state.bait, {})
        self.assertEqual(self.coil_toast(), "Line coiled in the boat.")

    def test_the_bait_box_fills_to_capacity_and_the_rest_goes_over_the_side(self):
        cap = self.state.box_cap()
        self.state.bait = {"dough": cap - 5}
        self.state.lines = [self.line(["worm", "liver"], [Hook(True) for _ in range(12)])]
        self.state.pull_line(0)
        self.assertEqual(self.state.bait_count(), cap)
        self.assertEqual(self.state.bait, {"dough": cap - 5, "worm": 5})
        self.assertEqual(self.coil_toast(), "Line coiled in the boat. 5 nightcrawlers back in the bait box. "
                                            "The box is full; 7 went over the side.")

    def test_a_full_box_takes_nothing_back(self):
        cap = self.state.box_cap()
        self.state.bait = {"worm": cap}
        self.state.lines = [self.line("worm", [Hook(True) for _ in range(12)])]
        self.state.pull_line(0)
        self.assertEqual(self.state.bait, {"worm": cap})
        self.assertEqual(self.coil_toast(), "Line coiled in the boat. The box is full; 12 went over the side.")

    def test_a_refused_pull_keeps_the_bait_out_and_the_next_pull_returns_it_once(self):
        hooks = [Hook(True) for _ in range(12)]
        hooks[0] = Hook(False, fish("keep"))  # the player chose Keep, so a full livewell refuses
        self.state.lines = [self.line("worm", hooks)]
        self.state.well = [Catch("bluegill", self.state.well_cap(), 0.9, 1.0, "open", "worm", 3, "briar")]
        self.assertIsNotNone(self.state.pull_line(0))
        self.assertEqual(self.state.bait, {})
        self.assertEqual(sum(hook.baited for hook in self.state.lines[0].hooks), 11)
        self.state.well = []
        self.assertIsNone(self.state.pull_line(0))
        self.assertEqual(self.state.bait, {"worm": 11})
        self.assertEqual(self.state.lines, [])

    def test_returned_bait_survives_save_and_load(self):
        self.state.bait = {"worm": 3}
        self.state.lines = [self.line(["worm", "shad"], [Hook(True) for _ in range(12)])]
        self.state.pull_line(0)
        with tempfile.TemporaryDirectory(prefix="bait-refund-") as temp:
            path = Path(temp) / "save.json"
            self.state.save(path)
            loaded = State.load(path, self.world)
        self.assertEqual(loaded.bait, {"worm": 9, "shad": 6})
        self.assertEqual(loaded.lines, [])
        self.assertEqual(len(loaded.held), len(self.state.held))

    def test_a_full_box_keeps_the_earliest_hooks_when_one_bait_spans_two_sections(self):
        # Sections worm / liver / worm: hook order is 4 worm, then 4 liver, then 4 worm.
        self.state.bait = {"dough": self.state.box_cap() - 6}
        self.state.lines = [self.line(["worm", "liver", "worm"], [Hook(True) for _ in range(12)])]
        self.state.pull_line(0)
        self.assertEqual(self.state.bait, {"dough": self.state.box_cap() - 6, "worm": 4, "liver": 2})

    def test_bait_the_hotpot_put_on_for_free_does_not_come_back(self):
        self.state.bait = {"worm": 0}
        line = self.line("worm", [Hook(True)] + [Hook(False) for _ in range(11)])
        self.state.lines = [line]
        comfort.serve_dish(self.state, DISHES["ember_hotpot"])
        comfort.begin_haul(self.state, line)
        self.assertTrue(all(hook.baited for hook in line.hooks))
        # Through a save, as a player would quit between the check and the pull.
        with tempfile.TemporaryDirectory(prefix="bait-refund-") as temp:
            path = Path(temp) / "save.json"
            self.state.save(path)
            loaded = State.load(path, self.world)
        loaded.pull_line(0)
        self.assertEqual(loaded.bait.get("worm", 0), 1)

    def test_paid_rebait_after_a_free_one_comes_back(self):
        self.state.bait = {"worm": 12}
        line = self.line("worm", [Hook(False) for _ in range(12)])
        self.state.lines = [line]
        comfort.serve_dish(self.state, DISHES["ember_hotpot"])
        comfort.begin_haul(self.state, line)
        for hook in line.hooks[:3]:
            hook.baited = False  # three bites strip free bait
        self.assertIsNone(self.state.rebait(0))
        self.state.pull_line(0)
        self.assertEqual(self.state.bait, {"worm": 12})  # 3 paid, 3 back; the 9 free stay gone


if __name__ == "__main__":
    unittest.main()
