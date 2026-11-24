"""Mode invariants, needs timelines, catnap, dreams and never-stranding tow."""

from copy import deepcopy
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from . import comfort
from .boat import BOATS
from .book import species_page
from .data import SPECIES
from .game import Keys, Session
from .haul import haul_cadence
from .platform import Input, Text
from .sim import Catch, Hook, RNG, SetLine, State
from .test_skipper_creator import finish_creator
from .ui import UI, UIState, comfort_controls
from .world import World


class ComfortChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World()

    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="trotline-comfort-")
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "save.json"
        self.state = State.new(self.world, seed=42014)
        self.session = Session(self.world, self.path, self.state, False)
        self.session.ui.mode = "play"

    def test_cozy_never_applies_needs_even_with_stale_counters(self):
        state = self.state
        base_speed = state.max_speed()
        state.v2["needs"].update({"awake_h": 1000, "since_meal_h": 1000})
        state.advance_bulk(1440)
        self.assertFalse(comfort.drowsy(state.v2))
        self.assertFalse(comfort.doze_due(state.v2))
        self.assertEqual(comfort.speed_factor(state.v2), 1)
        self.assertEqual(state.max_speed(), base_speed)
        self.assertEqual(haul_cadence(state), .25)
        self.assertIsNone(comfort.next_prompt(state.v2))
        before = state.to_json()
        self.assertIsNotNone(state.catnap(self.world, forced=True))
        self.assertEqual(state.to_json(), before)

    def test_mode_fuel_economy_changes_actual_burn(self):
        def burn(mode):
            state = State.new(self.world, seed=42014)
            state.x, state.z = self.world.anchors["briar:deep"].position
            state.anchored = False
            state.throttle = state.throttle_setting = 1.0
            comfort.change_mode(state.v2, mode)
            before = state.fuel
            state.drive(10.0, 0.0, 0.0, self.world)
            return before - state.fuel

        cozy_burn = burn("cozy")
        old_salt_burn = burn("old_salt")
        self.assertGreater(cozy_burn, 0.0)
        self.assertAlmostEqual(old_salt_burn / cozy_burn, 4.0 / 3.0)

    def test_cozy_halves_unsailed_snow_mist_gust_drift(self):
        anchor = self.world.anchors["briar:deep"]

        def drift(mode):
            state = State.new(self.world, seed=42014)
            state.x, state.z = anchor.position
            state.anchored = False
            state.anim = 1.0
            comfort.change_mode(state.v2, mode)
            with patch("fishing.sim.weather_at", return_value="snow_mist"), \
                    patch("fishing.sim.wind_at", return_value=(0.0, 10.0)):
                state.drive(1.0, 0.0, 0.0, self.world)
            return math.hypot(state.x - anchor.x, state.z - anchor.z)

        self.assertAlmostEqual(drift("cozy"), drift("old_salt") * 0.5)
        cozy = State.new(self.world, seed=42014)
        self.assertEqual(comfort.gust_factor(cozy, "snow_mist", using_sail=True), 1.0)

    def test_old_salt_timeline_at_sixteen_twenty_and_twenty_four_hours(self):
        state = self.state
        comfort.change_mode(state.v2, "old_salt")
        speed = state.max_speed()
        state.advance_bulk(16 * 60)
        self.assertTrue(comfort.drowsy(state.v2))
        self.assertEqual(haul_cadence(state), .3125)
        self.assertFalse(comfort.doze_due(state.v2))
        state.advance_bulk(4 * 60)
        self.assertEqual(state.v2["needs"]["awake_h"], 20)
        self.assertFalse(comfort.doze_due(state.v2))
        state.advance_bulk(4 * 60)
        self.assertTrue(comfort.doze_due(state.v2))
        self.assertEqual(comfort.speed_factor(state.v2), 1)  # strictly over 24
        state.advance_bulk(1)
        self.assertAlmostEqual(state.max_speed(), speed * .8)
        state.anchored, state.speed, state.throttle_setting = False, 2., .5
        state.lines = [SetLine("std", "worm", state.x, state.z, state.x + 12, state.z,
                               "flats", [Hook(False, Catch("bluegill", .5, 1, 0, "flats", "worm", 8))])]
        self.session.tick(Keys(), 0)
        self.assertEqual(self.session.ui.mode, "catnap")
        self.assertTrue(self.session.ui.nap_forced)
        self.assertTrue(state.anchored)
        self.assertEqual((state.speed, state.throttle, state.throttle_setting), (0, 0, 0))
        self.assertEqual(state.v2["needs"]["awake_h"], 0)
        self.assertIsNotNone(state.lines[0].hooks[0].catch)
        self.assertGreater(state.v2["needs"]["since_meal_h"], 26)
        comfort.meal(state.v2)
        self.assertEqual(comfort.speed_factor(state.v2), 1)

    def test_switching_resets_needs_keeps_positive_comfort_and_future_fields(self):
        state = self.state
        comfort.change_mode(state.v2, "old_salt")
        state.v2["needs"].update({"awake_h": 19., "since_meal_h": 25., "rested_until": 1000})
        state.v2["needs"]["prompted"]["future"] = "keep"
        self.session.ui.mode = "settings"
        self.session._adjust_setting(0, 1)
        self.assertEqual(comfort.mode(state.v2), "cozy")
        self.assertEqual((state.v2["needs"]["awake_h"], state.v2["needs"]["since_meal_h"]), (0, 0))
        self.assertEqual(state.v2["needs"]["rested_until"], 1000)
        self.assertEqual(state.v2["needs"]["prompted"]["future"], "keep")
        self.session._adjust_setting(0, 1)
        self.assertEqual(comfort.mode(state.v2), "old_salt")
        self.assertFalse(comfort.drowsy(state.v2))
        self.assertEqual(comfort.speed_factor(state.v2), 1)

    def test_manual_nap_advances_once_soaks_and_skips_only_the_fade(self):
        state = self.state
        state.lines = [SetLine("std", "worm", 0, 0, 12, 0, "flats",
                               [Hook(False, Catch("bluegill", .5, 1, 0, "flats", "worm", 8))])]
        before = state.game_minutes
        self.session.tick(Keys(pressed={"z"}), 0)
        self.assertEqual(state.game_minutes, before + 120)
        self.assertEqual(state.lines[0].hooks[0].catch.age, 2)
        self.assertEqual(state.narrative.active_play_game_minutes, 120)
        self.assertEqual(self.session.ui.mode, "catnap")
        self.session.tick(Keys(pressed={"space"}), 0)
        self.assertEqual(self.session.ui.mode, "play")
        self.assertEqual(state.game_minutes, before + 120)
        self.assertEqual(State.load(self.path, self.world).game_minutes, before + 120)

    def test_nap_requires_anchor_dock_or_idle_hammock(self):
        state = self.state
        state.x, state.z = 100., 100.
        state.anchored = False
        self.assertIsNotNone(state.catnap(self.world))
        state.boat_id = "pontoon"
        state.owned_boats.append("pontoon")
        self.assertIn("hammock", state.boat.traits)
        self.assertIsNone(state.catnap(self.world))
        self.assertFalse(state.anchored)
        state.throttle_setting = .3
        self.assertIsNotNone(state.catnap(self.world))

    def test_rested_cooldown_and_one_unread_deterministic_dream(self):
        state = self.state
        twin = State.new(self.world, seed=42014)
        self.assertIsNone(state.catnap(self.world))
        self.assertIsNone(twin.catnap(self.world))
        first = deepcopy(state.v2["book"]["dream_clue"])
        self.assertEqual(first, twin.v2["book"]["dream_clue"])
        self.assertEqual(state.rng.s, twin.rng.s)
        until, rng_state = state.v2["needs"]["rested_until"], state.rng.s
        self.assertIsNone(state.catnap(self.world))
        self.assertEqual(state.v2["needs"]["rested_until"], until)
        self.assertEqual(state.rng.s, rng_state)
        self.assertEqual(state.v2["book"]["dream_clue"], first)
        self.session.tick(Keys(pressed={"j"}), 0)
        self.assertIsNone(state.v2["book"]["dream_clue"])
        page = species_page(state.v2["book"], first["species"], 0)
        self.assertEqual(page["dreams"][0]["teller"], "Bot's dream")
        self.session.ui.mode = "play"
        state.advance_bulk(240)
        self.assertFalse(comfort.rested(state.v2, state.narrative.active_play_game_minutes))
        self.assertIsNone(state.catnap(self.world))
        self.assertNotEqual(state.v2["book"]["dream_clue"]["species"], first["species"])

    def test_dream_lead_is_uncaught_on_this_lake_and_never_rerolls_on_load(self):
        state = self.state
        for sp in SPECIES:
            state.journal[sp.id].update({"count": 1, "lake_id": "briar"})
        state.journal["bluegill"]["lake_id"] = "cedar"
        state.catnap(self.world)
        self.assertEqual(state.v2["book"]["dream_clue"]["species"], "bluegill")
        state.v2["needs"]["future"] = {"keep": True}
        state.save(self.path, update_stamp=False)
        loaded = State.load(self.path, self.world)
        self.assertEqual(loaded.v2["needs"], state.v2["needs"])
        self.assertEqual(loaded.v2["book"], state.to_json()["v2"]["book"])
        self.assertEqual(loaded.rng.s, state.rng.s)

    def test_prompts_use_active_real_seconds_global_throttle_and_snooze(self):
        v2 = self.state.v2
        comfort.change_mode(v2, "old_salt")
        v2["needs"].update({"awake_h": 16, "since_meal_h": 25})
        self.assertEqual(comfort.next_prompt(v2), "energy")
        self.assertIsNone(comfort.next_prompt(v2))
        comfort.active_time(v2, 599)
        self.assertIsNone(comfort.next_prompt(v2))
        comfort.active_time(v2, 1)
        self.assertEqual(comfort.next_prompt(v2), "hunger")
        comfort.snooze(v2, "hunger")
        comfort.active_time(v2, 1799)
        self.assertIsNone(comfort.next_prompt(v2))
        comfort.active_time(v2, 1)
        self.assertEqual(comfort.next_prompt(v2), "hunger")
        comfort.change_mode(v2, "cozy")
        self.assertIsNone(comfort.next_prompt(v2))

    def test_needs_and_rested_freeze_in_menus_focus_loss_and_offline(self):
        state = self.state
        comfort.change_mode(state.v2, "old_salt")
        state.catnap(self.world)
        before = deepcopy(state.v2["needs"])
        state.lines = [SetLine("std", "worm", 0, 0, 12, 0, "flats", [Hook(True)])]
        for mode in ("pause", "settings", "journal", "new_mode", "needs", "catnap", "haul", "skipper"):
            self.session.ui.mode = mode
            self.session.ui.nap_timer = 20
            self.session.tick(Keys(), .25)
            self.assertEqual(state.v2["needs"], before)
        self.session.ui.mode = "play"
        self.session.tick(Keys(focused=False), 10)
        self.assertEqual(state.v2["needs"], before)
        state.catch_up(state.stamp + 1000)
        self.assertEqual(state.v2["needs"], before)
        self.assertTrue(comfort.rested(state.v2, state.narrative.active_play_game_minutes))

    def test_new_game_selects_mode_defaults_cozy_and_cancel_keeps_existing_save(self):
        """Choose a new slot's pace while cancellation preserves the main save bytes."""
        self.session.save()
        original = self.path.read_bytes()
        self.session.ui.mode, self.session.ui.confirm_new = "title", True
        self.session.tick(Keys(pressed={"return"}), 0)
        self.assertEqual(self.session.ui.mode, "new_mode")
        self.assertEqual(self.session.ui.new_mode_i, 0)
        self.assertEqual(self.path.read_bytes(), original)
        self.session.tick(Keys(pressed={"esc"}), 0)
        self.assertEqual(self.path.read_bytes(), original)
        self.session.ui.confirm_new = True
        self.session.tick(Keys(pressed={"return"}), 0)
        self.session.tick(Keys(pressed={"right"}), 0)
        self.session.tick(Keys(pressed={"return"}), 0)
        finish_creator(self.session)
        self.assertEqual(comfort.mode(self.session.state.v2), "old_salt")
        # A new morning now owns a separate slot instead of replacing the main save.
        self.assertEqual(comfort.mode(State.load(self.session.save_path, self.world).v2), "old_salt")
        self.assertEqual(self.path.read_bytes(), original)

    def test_both_new_game_modes_can_hail_and_render_npc_dialogue(self):
        text = Text()
        self.addCleanup(text.close)
        renderer = UI(text, self.world)
        for index, mode in enumerate(comfort.MODES):
            with self.subTest(mode=mode):
                self.session.ui.mode = "new_mode"
                self.session.ui.new_mode_i = index
                self.session.tick(Keys(pressed={"return"}), 0)  # the pace; the creator
                finish_creator(self.session)  # Done starts the morning
                state = self.session.state
                npc = state.npcs[0]
                state.x, state.z = npc.anchor.position
                self.session.tick(Keys(pressed={"c"}), 0)
                self.assertEqual(self.session.ui.mode, "dialogue")
                frame = np.zeros((720, 1280, 3), np.uint8)
                renderer.draw(frame, state, self.session.ui)
                self.assertIs(self.session.ui.dialogue_content, self.session._npc_content)
                self.assertTrue(frame.any())

    def test_mouse_mode_choice_and_controller_pause_catnap(self):
        """Choose the displayed pace by pointer, then retain controller catnap access."""
        self.session.ui.mode = "new_mode"
        text = Text()
        self.addCleanup(text.close)
        renderer = UI(text, self.world)
        self.addCleanup(renderer.close)
        renderer.draw(np.zeros((270, 480, 3), np.uint8), self.state, self.session.ui)
        x, y, _w, _h = comfort_controls((480, 270))[1]
        keys = Input()
        keys.viewport, keys.mouse_click = (480, 270), (x + 4, y + 4)
        self.session.tick(keys, 0)
        self.assertEqual(self.session.ui.mode, "skipper")  # the pace is chosen; the creator comes next
        finish_creator(self.session)
        self.assertEqual(comfort.mode(self.session.state.v2), "old_salt")
        self.session.ui.mode = "pause"
        keys = Input()
        keys.device, keys.gamepad_pressed = "gamepad", {"f"}
        self.session.tick(keys, 0)
        self.assertEqual(self.session.ui.mode, "catnap")

    def test_native_comfort_panels_fit_all_sizes_and_both_fonts(self):
        text = Text()
        self.addCleanup(text.close)
        renderer = UI(text, self.world)
        original = renderer._text
        records = []
        def record(frame, label, x, y, size, color, shadow=True, family="mono"):
            image = renderer._render(label, size, color, family)
            if label:
                records.append((label, x, y, image.shape[1], image.shape[0]))
            return original(frame, label, x, y, size, color, shadow, family)
        renderer._text = record
        comfort.change_mode(self.state.v2, "old_salt")
        self.state.catnap(self.world)
        for width, height in ((1280, 720), (480, 270)):
            for dyslexia in (False, True):
                for size in range(3):
                    self.state.v2["settings"].update({"text_size": size, "dyslexia_font": dyslexia})
                    for mode, kind in (("new_mode", ""), ("needs", "energy"), ("needs", "hunger"), ("catnap", "")):
                        records.clear()
                        frame = np.zeros((height, width, 3), np.uint8)
                        before = deepcopy(self.state.v2)
                        renderer.draw(frame, self.state, UIState(mode=mode, needs_kind=kind, nap_timer=1.5))
                        self.assertEqual(self.state.v2, before)
                        for i, (label, x, y, w, h) in enumerate(records):
                            with self.subTest(width=width, size=size, dyslexia=dyslexia, mode=mode, label=label):
                                self.assertGreaterEqual(x, 0)
                                self.assertGreaterEqual(y, 0)
                                self.assertLessEqual(x + w, width)
                                self.assertLessEqual(y + h, height)
                                for other, ox, oy, ow, oh in records[:i]:
                                    self.assertFalse(x < ox + ow and ox < x + w and y < oy + oh and oy < y + h,
                                                     f"{label!r} overlaps {other!r}")

    def test_tow_fees_all_boats_zero_cash_and_ten_thousand_no_stranding_cases(self):
        state, rng = self.state, RNG(42015)
        state.owned_boats = list(BOATS)
        treasure = Catch("bluegill", .5, 1, 0, "flats", "worm", 8, shiny=True)
        state.well = [treasure]
        for i in range(10_000):
            state.boat_id = rng.pick({bid: 1 for bid in BOATS})
            comfort.change_mode(state.v2, "cozy" if i % 2 else "old_salt")
            state.money = round(rng.u01() * 200, 2) if i % 3 else 0.
            cash = state.money
            state.fuel = 0
            state.rowboat_battery_kwh = 0
            state.sail_raised = False
            state.speed = state.throttle = state.throttle_setting = 0
            expected = 0 if comfort.mode(state.v2) == "cozy" else min(cash, round(25 + .02 * state.boat.price, 2))
            self.assertIsNone(state.tow_to_landing(self.world))
            self.assertAlmostEqual(state.money, cash - expected)
            self.assertGreaterEqual(state.money, 0)
            self.assertEqual(state.slip_status(self.world), "docked")
            self.assertEqual(state.well, [treasure])
            self.assertEqual(state.owned_boats, list(BOATS))


if __name__ == "__main__":
    unittest.main()
