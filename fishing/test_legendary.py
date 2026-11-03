"""Tests for legendary system: watch cards, guaranteed hooks, records, and day-one Spillway (V1-36)."""

from __future__ import annotations

import unittest

from . import calendar, legendary
from .guardian import maybe_start_sighting
from .sim import Catch, Hook, SetLine, State
from .world import World


def _minutes(hour: float) -> float:
    """Convert clock hour (0.0–24.0) to game minutes where 06:00 is 0.0."""
    return ((hour - 6.0) % 24.0) * 60.0


def _line(tier="std", bait="worm", zone="open", x0=0.0, z0=0.0, x1=10.0, z1=0.0, extra=None):
    return SetLine(tier, bait, x0, z0, x1, z1, zone, [Hook(True)], extra_fields=extra or {})


class LegendarySystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.briar = World("briar")
        cls.cedar = World("cedar")

    def _state(self, lake_id="briar", seed=101):
        world = self.cedar if lake_id == "cedar" else self.briar
        state = State.new(world, seed=seed)
        state.lake_id = lake_id
        return state

    # -------------------------------------------------------------------------
    # Acceptance Criteria 1: A test per legendary
    # Meeting every requirement inside the window hooks it on the first haul,
    # and missing any one requirement doesn't.
    # -------------------------------------------------------------------------

    def test_old_lantern(self):
        # Meets all: briar, landing_edge, 20:00–24:00, lantern_liver, spotlight owned/on
        state = self._state("briar")
        state.light = True
        state.game_minutes = _minutes(21.0)
        lx, lz = -435.789 + 80.0, 107.381
        line = _line("std", "lantern_liver", "landing_edge", lx - 5, lz, lx + 5, lz)

        catch = legendary.check_legendary_hook(state, line, self.briar)
        self.assertIsNotNone(catch)
        self.assertEqual(catch.species, "old_lantern")
        self.assertTrue(catch.legendary)
        self.assertEqual(catch.disposition, "release")
        self.assertAlmostEqual(catch.weight, 38.0, delta=4.0)

        # Missing window (14:00)
        s_bad = self._state("briar")
        s_bad.light = True
        s_bad.game_minutes = _minutes(14.0)
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "lantern_liver", "landing_edge", lx - 5, lz, lx + 5, lz), self.briar))

        # Missing spotlight
        s_bad = self._state("briar")
        s_bad.light = False
        s_bad.game_minutes = _minutes(21.0)
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "lantern_liver", "landing_edge", lx - 5, lz, lx + 5, lz), self.briar))

        # Missing bait
        s_bad = self._state("briar")
        s_bad.light = True
        s_bad.game_minutes = _minutes(21.0)
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "worm", "landing_edge", lx - 5, lz, lx + 5, lz), self.briar))

        # Missing location (in deep instead of landing_edge)
        self.assertIsNone(legendary.check_legendary_hook(state, _line("std", "lantern_liver", "deep", 0, 0, 10, 0), self.briar))

        # Missing lake (cedar)
        s_bad = self._state("cedar")
        s_bad.light = True
        s_bad.game_minutes = _minutes(21.0)
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "lantern_liver", "landing_edge", lx - 5, lz, lx + 5, lz), self.cedar))

    def test_lily_queen(self):
        # Meets all: briar, lilies or reeds, 05:00–08:00, mist or drizzle, queens_breakfast, Ch. 1 complete
        state = self._state("briar")
        state.v2.setdefault("story", {})["completed_chapters"] = [1]
        state.game_minutes = _minutes(6.0)
        state.weather = "mist"
        line = _line("std", "queens_breakfast", "lilies")

        catch = legendary.check_legendary_hook(state, line)
        self.assertIsNotNone(catch)
        self.assertEqual(catch.species, "lily_queen")
        self.assertAlmostEqual(catch.weight, 14.0, delta=2.0)

        # Missing chapter (Ch 0)
        s_bad = self._state("briar")
        s_bad.v2.setdefault("story", {})["completed_chapters"] = []
        s_bad.game_minutes = _minutes(6.0)
        s_bad.weather = "mist"
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "queens_breakfast", "lilies")))

        # Missing weather (clear)
        s_bad = self._state("briar")
        s_bad.v2.setdefault("story", {})["completed_chapters"] = [1]
        s_bad.game_minutes = _minutes(6.0)
        s_bad.weather = "clear"
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "queens_breakfast", "lilies")))

        # Missing bait
        self.assertIsNone(legendary.check_legendary_hook(state, _line("std", "worm", "lilies")))

        # Missing location (open instead of lilies/reeds)
        self.assertIsNone(legendary.check_legendary_hook(state, _line("std", "queens_breakfast", "open")))

        # Missing window (12:00)
        s_bad = self._state("briar")
        s_bad.v2.setdefault("story", {})["completed_chapters"] = [1]
        s_bad.game_minutes = _minutes(12.0)
        s_bad.weather = "mist"
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "queens_breakfast", "lilies")))

    def test_spillway_monster(self):
        # Meets all: cedar, marked_pool, 20:00–04:00, cut shad, heavy line
        state = self._state("cedar")
        state.game_minutes = _minutes(22.0)
        mx, mz = 403.611, -1212.677
        line = _line("heavy", "shad", "rocks", mx - 5, mz, mx + 5, mz)

        catch = legendary.check_legendary_hook(state, line, self.cedar)
        self.assertIsNotNone(catch)
        self.assertEqual(catch.species, "spillway_monster")
        self.assertAlmostEqual(catch.weight, 95.0, delta=10.0)

        # Missing heavy line (std line)
        self.assertIsNone(legendary.check_legendary_hook(state, _line("std", "shad", "rocks", mx - 5, mz, mx + 5, mz), self.cedar))

        # Missing bait (worm)
        self.assertIsNone(legendary.check_legendary_hook(state, _line("heavy", "worm", "rocks", mx - 5, mz, mx + 5, mz), self.cedar))

        # Missing window (12:00)
        s_bad = self._state("cedar")
        s_bad.game_minutes = _minutes(12.0)
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("heavy", "shad", "rocks", mx - 5, mz, mx + 5, mz), self.cedar))

        # Missing location (outside marked pool)
        self.assertIsNone(legendary.check_legendary_hook(state, _line("heavy", "shad", "rocks", 0, 0, 10, 0), self.cedar))

    def test_channel_leviathan(self):
        # Meets all: cedar, inlet, 22:00–02:00, rain within 6h, pecan_smoked_shad, Ch. 2 complete
        state = self._state("cedar")
        state.v2.setdefault("story", {})["completed_chapters"] = [1, 2]
        state.game_minutes = _minutes(23.0)
        state.recent_rain = True
        line = _line("std", "pecan_smoked_shad", "inlet")

        catch = legendary.check_legendary_hook(state, line)
        self.assertIsNotNone(catch)
        self.assertEqual(catch.species, "channel_leviathan")
        self.assertAlmostEqual(catch.weight, 120.0, delta=12.0)

        # Missing chapter (Ch 1 only)
        s_bad = self._state("cedar")
        s_bad.v2.setdefault("story", {})["completed_chapters"] = [1]
        s_bad.game_minutes = _minutes(23.0)
        s_bad.recent_rain = True
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "pecan_smoked_shad", "inlet")))

        # Missing rain within 6h
        s_bad = self._state("cedar")
        s_bad.v2.setdefault("story", {})["completed_chapters"] = [1, 2]
        s_bad.game_minutes = _minutes(23.0)
        s_bad.recent_rain = False
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "pecan_smoked_shad", "inlet")))

        # Missing bait
        self.assertIsNone(legendary.check_legendary_hook(state, _line("std", "worm", "inlet")))

        # Missing location (deep instead of inlet)
        self.assertIsNone(legendary.check_legendary_hook(state, _line("std", "pecan_smoked_shad", "deep")))

        # Missing window (12:00)
        s_bad = self._state("cedar")
        s_bad.v2.setdefault("story", {})["completed_chapters"] = [1, 2]
        s_bad.game_minutes = _minutes(12.0)
        s_bad.recent_rain = True
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "pecan_smoked_shad", "inlet")))

    def test_glacial_phantom(self):
        # Meets all: flathead, inlet, 05:00–09:00, snow_mist, phantom_roe, line in cold band
        state = self._state("flathead")
        state.game_minutes = _minutes(6.0)
        state.weather = "snow_mist"
        line = _line("std", "phantom_roe", "inlet", extra={"in_cold_band": True})

        catch = legendary.check_legendary_hook(state, line)
        self.assertIsNotNone(catch)
        self.assertEqual(catch.species, "glacial_phantom")
        self.assertAlmostEqual(catch.weight, 22.0, delta=3.0)

        # Missing cold band
        self.assertIsNone(legendary.check_legendary_hook(state, _line("std", "phantom_roe", "inlet", extra={"in_cold_band": False})))

        # Missing weather (clear)
        s_bad = self._state("flathead")
        s_bad.game_minutes = _minutes(6.0)
        s_bad.weather = "clear"
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "phantom_roe", "inlet", extra={"in_cold_band": True})))

        # Missing window (12:00)
        s_bad = self._state("flathead")
        s_bad.game_minutes = _minutes(12.0)
        s_bad.weather = "snow_mist"
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "phantom_roe", "inlet", extra={"in_cold_band": True})))

        # Missing bait
        self.assertIsNone(legendary.check_legendary_hook(state, _line("std", "worm", "inlet", extra={"in_cold_band": True})))

        # Missing location (deep instead of inlet)
        self.assertIsNone(legendary.check_legendary_hook(state, _line("std", "phantom_roe", "deep", extra={"in_cold_band": True})))

    def test_old_silverhead(self):
        # Meets all: flathead, deep, 03:00–07:00, clear, huckleberry_mash, line in cold band
        state = self._state("flathead")
        state.game_minutes = _minutes(5.0)
        state.weather = "clear"
        line = _line("std", "huckleberry_mash", "deep", extra={"in_cold_band": True})

        catch = legendary.check_legendary_hook(state, line)
        self.assertIsNotNone(catch)
        self.assertEqual(catch.species, "old_silverhead")
        self.assertAlmostEqual(catch.weight, 60.0, delta=6.0)

        # Missing cold band
        self.assertIsNone(legendary.check_legendary_hook(state, _line("std", "huckleberry_mash", "deep", extra={"in_cold_band": False})))

        # Missing weather (snow_mist)
        s_bad = self._state("flathead")
        s_bad.game_minutes = _minutes(5.0)
        s_bad.weather = "snow_mist"
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "huckleberry_mash", "deep", extra={"in_cold_band": True})))

        # Missing bait
        self.assertIsNone(legendary.check_legendary_hook(state, _line("std", "worm", "deep", extra={"in_cold_band": True})))

        # Missing window (12:00)
        s_bad = self._state("flathead")
        s_bad.game_minutes = _minutes(12.0)
        s_bad.weather = "clear"
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "huckleberry_mash", "deep", extra={"in_cold_band": True})))

        # Missing location (inlet instead of deep)
        self.assertIsNone(legendary.check_legendary_hook(state, _line("std", "huckleberry_mash", "inlet", extra={"in_cold_band": True})))

    def test_huckleberrys_whopper(self):
        # Meets all: flathead, rocks, 22:00–02:00, snow_mist, roe, Whopper story on 3 days
        state = self._state("flathead")
        state.game_minutes = _minutes(23.0)
        state.weather = "snow_mist"
        state.v2.setdefault("npcs", {})["talk_days"] = {"captain_huckleberry": [1, 2, 3]}
        line = _line("std", "roe", "rocks")

        catch = legendary.check_legendary_hook(state, line)
        self.assertIsNotNone(catch)
        self.assertEqual(catch.species, "huckleberrys_whopper")
        self.assertAlmostEqual(catch.weight, 18.0, delta=2.0)

        # Missing Whopper story (only 1 day)
        s_bad = self._state("flathead")
        s_bad.game_minutes = _minutes(23.0)
        s_bad.weather = "snow_mist"
        s_bad.v2.setdefault("npcs", {})["talk_days"] = {"captain_huckleberry": [1]}
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "roe", "rocks")))

        # Missing weather (clear)
        s_bad = self._state("flathead")
        s_bad.game_minutes = _minutes(23.0)
        s_bad.weather = "clear"
        s_bad.v2.setdefault("npcs", {})["talk_days"] = {"captain_huckleberry": [1, 2, 3]}
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "roe", "rocks")))

        # Missing bait
        self.assertIsNone(legendary.check_legendary_hook(state, _line("std", "worm", "rocks")))

        # Missing location (deep instead of rocks)
        self.assertIsNone(legendary.check_legendary_hook(state, _line("std", "roe", "deep")))

        # Missing window (12:00)
        s_bad = self._state("flathead")
        s_bad.game_minutes = _minutes(12.0)
        s_bad.weather = "snow_mist"
        s_bad.v2.setdefault("npcs", {})["talk_days"] = {"captain_huckleberry": [1, 2, 3]}
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "roe", "rocks")))

    def test_obsidian_gar(self):
        # Meets all: crater, rocks, 16:00–20:00, clear, mineral_shad, Ch. 4 complete
        state = self._state("crater")
        state.v2.setdefault("story", {})["completed_chapters"] = [1, 2, 3, 4]
        state.game_minutes = _minutes(18.0)
        state.weather = "clear"
        line = _line("std", "mineral_shad", "rocks")

        catch = legendary.check_legendary_hook(state, line)
        self.assertIsNotNone(catch)
        self.assertEqual(catch.species, "obsidian_gar")
        self.assertAlmostEqual(catch.weight, 48.0, delta=5.0)

        # Missing chapter (Ch 3 only)
        s_bad = self._state("crater")
        s_bad.v2.setdefault("story", {})["completed_chapters"] = [1, 2, 3]
        s_bad.game_minutes = _minutes(18.0)
        s_bad.weather = "clear"
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "mineral_shad", "rocks")))

        # Missing weather (fog)
        s_bad = self._state("crater")
        s_bad.v2.setdefault("story", {})["completed_chapters"] = [1, 2, 3, 4]
        s_bad.game_minutes = _minutes(18.0)
        s_bad.weather = "fog"
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "mineral_shad", "rocks")))

        # Missing bait
        self.assertIsNone(legendary.check_legendary_hook(state, _line("std", "worm", "rocks")))

        # Missing location (springs instead of rocks)
        self.assertIsNone(legendary.check_legendary_hook(state, _line("std", "mineral_shad", "springs")))

        # Missing window (12:00)
        s_bad = self._state("crater")
        s_bad.v2.setdefault("story", {})["completed_chapters"] = [1, 2, 3, 4]
        s_bad.game_minutes = _minutes(12.0)
        s_bad.weather = "clear"
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "mineral_shad", "rocks")))

    def test_caldera_fire_lizard(self):
        # Meets all: crater, springs, 00:00–04:00, fog, ember_dumpling, heard Mist's poem
        state = self._state("crater")
        state.game_minutes = _minutes(2.0)
        state.weather = "fog"
        state.mist_poem_heard = True
        line = _line("std", "ember_dumpling", "springs")

        catch = legendary.check_legendary_hook(state, line)
        self.assertIsNotNone(catch)
        self.assertEqual(catch.species, "caldera_fire_lizard")
        self.assertAlmostEqual(catch.weight, 30.0, delta=3.0)

        # Missing poem
        s_bad = self._state("crater")
        s_bad.game_minutes = _minutes(2.0)
        s_bad.weather = "fog"
        s_bad.mist_poem_heard = False
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "ember_dumpling", "springs")))

        # Missing weather (clear)
        s_bad = self._state("crater")
        s_bad.game_minutes = _minutes(2.0)
        s_bad.weather = "clear"
        s_bad.mist_poem_heard = True
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "ember_dumpling", "springs")))

        # Missing bait
        self.assertIsNone(legendary.check_legendary_hook(state, _line("std", "worm", "springs")))

        # Missing location (rocks instead of springs)
        self.assertIsNone(legendary.check_legendary_hook(state, _line("std", "ember_dumpling", "rocks")))

        # Missing window (12:00)
        s_bad = self._state("crater")
        s_bad.game_minutes = _minutes(12.0)
        s_bad.weather = "fog"
        s_bad.mist_poem_heard = True
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "ember_dumpling", "springs")))

    def test_nebula_weaver(self):
        # Meets all: nebula, current, 20:00–24:00, aurora, moonmilk_stardust, Zero-G Winch owned
        state = self._state("nebula")
        state.game_minutes = _minutes(21.0)
        state.weather = "aurora"
        state.v2.setdefault("profile", {})["tools"] = ["zero_g_winch"]
        line = _line("std", "moonmilk_stardust", "current")

        catch = legendary.check_legendary_hook(state, line)
        self.assertIsNotNone(catch)
        self.assertEqual(catch.species, "nebula_weaver")
        self.assertAlmostEqual(catch.weight, 26.0, delta=3.0)

        # Missing tool
        s_bad = self._state("nebula")
        s_bad.game_minutes = _minutes(21.0)
        s_bad.weather = "aurora"
        s_bad.v2.setdefault("profile", {})["tools"] = []
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "moonmilk_stardust", "current")))

        # Missing weather (clear)
        s_bad = self._state("nebula")
        s_bad.game_minutes = _minutes(21.0)
        s_bad.weather = "clear"
        s_bad.v2.setdefault("profile", {})["tools"] = ["zero_g_winch"]
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "moonmilk_stardust", "current")))

        # Missing bait
        self.assertIsNone(legendary.check_legendary_hook(state, _line("std", "worm", "current")))

        # Missing location (open instead of current)
        self.assertIsNone(legendary.check_legendary_hook(state, _line("std", "moonmilk_stardust", "open")))

        # Missing window (12:00)
        s_bad = self._state("nebula")
        s_bad.game_minutes = _minutes(12.0)
        s_bad.weather = "aurora"
        s_bad.v2.setdefault("profile", {})["tools"] = ["zero_g_winch"]
        self.assertIsNone(legendary.check_legendary_hook(s_bad, _line("std", "moonmilk_stardust", "current")))

    def test_whiskered_guardian_witnessed_integration(self):
        # Existing rule: cedar, deep, 18:00–20:00, 8 of 10 ripples
        state = self._state("cedar")
        state.x, state.z = self.cedar.anchors["cedar:deep"].position
        state.narrative.ripples = [f"ripple_{i:02d}" for i in range(1, 9)]
        state.game_minutes = _minutes(19.0)

        self.assertTrue(maybe_start_sighting(state, self.cedar, "play"))
        self.assertTrue(state.narrative.guardian_seen)
        records = state.v2.get("legendaries", {}).get("whiskered_guardian", {}).get("records", [])
        self.assertTrue(records)
        self.assertIn("whiskered_guardian", state.v2["reward_claims"]["legendary_record"])

        # Missing ripples (<8)
        s_bad = self._state("cedar")
        s_bad.x, s_bad.z = self.cedar.anchors["cedar:deep"].position
        s_bad.narrative.ripples = ["ripple_01", "ripple_02"]
        s_bad.game_minutes = _minutes(19.0)
        self.assertFalse(maybe_start_sighting(s_bad, self.cedar, "play"))

        # Missing window (12:00)
        s_bad = self._state("cedar")
        s_bad.x, s_bad.z = self.cedar.anchors["cedar:deep"].position
        s_bad.narrative.ripples = [f"ripple_{i:02d}" for i in range(1, 9)]
        s_bad.game_minutes = _minutes(12.0)
        self.assertFalse(maybe_start_sighting(s_bad, self.cedar, "play"))

        # Missing location (open instead of deep)
        s_bad = self._state("cedar")
        s_bad.x, s_bad.z = self.cedar.anchors["cedar:open"].position
        s_bad.narrative.ripples = [f"ripple_{i:02d}" for i in range(1, 9)]
        s_bad.game_minutes = _minutes(19.0)
        self.assertFalse(maybe_start_sighting(s_bad, self.cedar, "play"))

    def test_star_whale_witnessed_requirements(self):
        # Evaluated via requirements and watch card
        state = self._state("nebula")
        state.game_minutes = _minutes(22.0)
        state.weather = "clear"
        state.zone = "open"
        state.v2.setdefault("story", {})["completed_chapters"] = [1, 2, 3, 4, 5]

        eval_res = legendary.evaluate_requirements(state, "star_whale")
        self.assertTrue(eval_res["met"])

        # Missing chapter 5
        s_bad = self._state("nebula")
        s_bad.game_minutes = _minutes(22.0)
        s_bad.weather = "clear"
        s_bad.zone = "open"
        s_bad.v2.setdefault("story", {})["completed_chapters"] = [1, 2, 3, 4]
        self.assertFalse(legendary.evaluate_requirements(s_bad, "star_whale")["met"])

    # -------------------------------------------------------------------------
    # Acceptance Criteria 2: Watch card states match requirements
    # -------------------------------------------------------------------------

    def test_watch_card_states_match_requirements(self):
        state = self._state("briar")
        state.light = False
        state.game_minutes = _minutes(12.0)

        card = legendary.watch_card(state, "old_lantern")
        self.assertEqual(card.name, "Old Lantern")
        self.assertIn("Grandmother Whiskers", card.clue_source)
        self.assertFalse(card.ready_now)
        self.assertFalse(card.states["window"])
        self.assertFalse(card.states["gate"])

        # Change state to meet window and gate:
        state.light = True
        state.game_minutes = _minutes(21.0)
        card_updated = legendary.watch_card(state, "old_lantern")
        self.assertTrue(card_updated.states["window"])
        self.assertTrue(card_updated.states["gate"])

        # Check line output formatting
        lines = card_updated.lines()
        self.assertTrue(any("Old Lantern" in line or "Grandmother Whiskers" in line for line in lines))
        self.assertTrue(any("[✓] Window: 20:00–24:00" in line for line in lines))

    # -------------------------------------------------------------------------
    # Acceptance Criteria 3: Spillway Monster on fresh save with heavy line
    # -------------------------------------------------------------------------

    def test_spillway_monster_catchable_on_fresh_save_with_heavy_line(self):
        # Fresh save: Chapter 0, day 1, no story progress or prior catches
        state = State.new(self.cedar, seed=999)
        state.lake_id = "cedar"
        state.game_minutes = _minutes(21.0)

        # Deployed heavy line in Cedar Marked Pool with shad bait
        mx, mz = 403.611, -1212.677
        heavy_line = _line("heavy", "shad", "rocks", mx - 5, mz, mx + 5, mz)
        state.lines = [heavy_line]

        # First haul via prepare_catch_dispositions / check_legendary_hook
        catch = legendary.check_legendary_hook(state, heavy_line, self.cedar)
        self.assertIsNotNone(catch)
        self.assertEqual(catch.species, "spillway_monster")
        self.assertTrue(catch.legendary)
        self.assertEqual(catch.disposition, "release")

        # Recorded in the book
        records = state.v2["legendaries"]["spillway_monster"]["records"]
        self.assertEqual(len(records), 1)
        self.assertAlmostEqual(records[0]["weight"], catch.weight, places=2)

        # Verified on watch card and book page
        card = legendary.watch_card(state, "spillway_monster")
        self.assertTrue(card.verified)

    # -------------------------------------------------------------------------
    # Weekly repeat rule and forced release
    # -------------------------------------------------------------------------

    def test_weekly_repeat_and_forced_release(self):
        state = self._state("cedar")
        state.game_minutes = _minutes(21.0)
        mx, mz = 403.611, -1212.677
        heavy_line = _line("heavy", "shad", "rocks", mx - 5, mz, mx + 5, mz)
        state.lines = [heavy_line]

        first_catch = legendary.check_legendary_hook(state, heavy_line, self.cedar)
        self.assertIsNotNone(first_catch)

        # Forced release check
        self.assertEqual(state._forced_release_reason(first_catch), "legendary")
        state.prepare_catch_dispositions(0)
        self.assertEqual(first_catch.disposition, "release")
        state.take_all(0)
        self.assertEqual(len(state.well), 0)  # Never enters livewell

        # Hauling again in the same game week does NOT hook it again
        rebait_line = _line("heavy", "shad", "rocks", mx - 5, mz, mx + 5, mz)
        state.lines = [rebait_line]
        self.assertIsNone(legendary.check_legendary_hook(state, rebait_line, self.cedar))

        # Advance to next game week (+7 days)
        state.game_minutes += calendar.WEEK_MINUTES
        repeat_catch = legendary.check_legendary_hook(state, rebait_line, self.cedar)
        self.assertIsNotNone(repeat_catch)
        self.assertEqual(repeat_catch.species, "spillway_monster")
        records = state.v2["legendaries"]["spillway_monster"]["records"]
        self.assertEqual(len(records), 2)  # Added a second weight record

    def test_split_bait_hook_selection(self):
        state = self._state("cedar")
        state.game_minutes = _minutes(21.0)
        mx, mz = 403.611, -1212.677
        # Line with 3 bait sections: worm, shad, cricket
        hooks = [Hook(True) for _ in range(3)]
        line = SetLine("heavy", ["worm", "shad", "cricket"], mx - 5, mz, mx + 5, mz, "rocks", hooks)
        state.lines = [line]

        catch = legendary.check_legendary_hook(state, line, self.cedar)
        self.assertIsNotNone(catch)
        self.assertEqual(catch.species, "spillway_monster")
        # Hook 1 (middle section) had "shad", so hook 1 should have caught it
        self.assertIsNone(line.hooks[0].catch)
        self.assertEqual(line.hooks[1].catch, catch)
        self.assertIsNone(line.hooks[2].catch)


if __name__ == "__main__":
    unittest.main()
