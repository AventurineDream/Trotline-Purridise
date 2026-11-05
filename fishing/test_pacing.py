"""V1-44: the pacing simulator's report meets 02 §1 and §15, and the changes it led to hold.

The report is computed once (`pacingreport.full_report`, several minutes) and each test
checks its own part. The attentive player it models is written down in pacing.py and
pacingstory.py.
"""

from __future__ import annotations

import unittest

from . import pacing, pacingreport, pacingstory
from .bot import tick as bot_tick
from .sim import HeldLine, State
from .world import World


class PacingReport(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = pacingreport.full_report()

    def test_the_first_catch_comes_within_three_minutes(self):
        first = self.report["first_catch"]
        self.assertLessEqual(first["max_s"], pacingreport.FIRST_CATCH_S, first["runs"])

    def test_every_stage_earns_its_band(self):
        for stage in pacing.STAGES:
            row = self.report["income"][stage.id]
            with self.subTest(stage=stage.id):
                self.assertTrue(row["in_band"], row)

    def test_chapters_and_story_run_to_their_targets(self):
        for row in self.report["chapters"]:
            with self.subTest(chapter=row["chapter"]):
                self.assertTrue(row["story_done"], row)
                self.assertTrue(row["ok"], row)
        self.assertTrue(self.report["story"]["ok"], self.report["story"])

    def test_the_book_takes_about_fifty_hours(self):
        book = self.report["book"]
        self.assertEqual(book["unverified"], [])
        self.assertTrue(book["ok"], book["all_verified_hours"])

    def test_every_legendary_becomes_catchable(self):
        for row in self.report["legendaries"]:
            with self.subTest(legendary=row["id"]):
                self.assertIsNotNone(row["eligible_h"], row)

    def test_guardrails(self):
        guard = self.report["guardrails"]
        for row in guard["required_gear"] + guard["boat_tiers"]:
            with self.subTest(row=row.get("check") or row.get("boat")):
                self.assertTrue(row["ok"], row)

    def test_the_first_day_does_not_talk_over_the_player(self):
        self.assertTrue(self.report["prompts"]["ok"], self.report["prompts"]["runs"])


class PacingChanges(unittest.TestCase):
    def test_a_new_games_first_bite_comes_quickly_then_the_nudge_ends(self):
        from .story import begin_prologue
        world = World("briar")
        odds = {}
        for case in ("prologue, nothing hooked", "prologue, one hooked", "no prologue"):
            state = State.new(world, seed=5)
            if case.startswith("prologue"):
                begin_prologue(state)
            point = pacingstory._points("briar")["open"][0]
            state.x, state.z, state.yaw = pacing._pose(world, *point, "worm", "std")
            state.speed = 0.0
            self.assertIsNone(state.try_set(world, 0, "worm"))
            state.hooked_total = 1 if case.endswith("one hooked") else 0
            seen = []
            state.rng.chance = lambda p, seen=seen: seen.append(p) or False
            state._one_span(1.0)
            odds[case] = max(seen)
        # The same hook, the same hour: a new game's prologue bites faster until its first fish.
        # After that, and in any save without a pending prologue, the ordinary rates apply.
        self.assertGreater(odds["prologue, nothing hooked"], odds["prologue, one hooked"] * 3)
        self.assertEqual(odds["prologue, one hooked"], odds["no prologue"])

    def test_bot_calls_the_first_bite_of_a_trip_only(self):
        world = World("briar")
        state = State.new(world, seed=5)
        state.toasts.clear()
        state.bot_phase, state.bot_hooks, state._bot_called_bite = "out", 0, False
        for bites in (1, 2, 3):
            state.hooked_total = bites
            bot_tick(state, world, 0.1)
        calls = [text for text, _ttl in state.toasts if text.startswith("Bot: Fish on")]
        self.assertEqual(len(calls), 1)

    def test_one_rebaited_hook_is_singular(self):
        world = World("briar")
        state = State.new(world, seed=5)
        x, z, yaw = pacing._pose(world, *pacingstory._points("briar")["open"][0], "worm", "std")
        state.x, state.z, state.yaw, state.speed = x, z, yaw, 0.0
        state.held = [HeldLine("std")]
        self.assertIsNone(state.try_set(world, 0, "worm"))
        state.lines[0].hooks[0].baited = False
        state.toasts.clear()
        self.assertIsNone(state.rebait(0))
        self.assertIn("Rebaited 1 hook with", state.toasts[-1][0])


if __name__ == "__main__":
    unittest.main()
