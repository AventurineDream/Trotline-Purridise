"""Creation-time shiny odds, tracker pity, persistence and integration."""

from copy import deepcopy
from dataclasses import replace
from itertools import product
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import numpy as np

from .boat import BOATS
from .book import (BOOK_SPECIES_IDS, LEGENDARY_IDS, SHINY_CHANCE, SHINY_PITY_CATCHES,
                   roll_shiny, set_shiny_target, shiny_tracker)
from .bookview import ENTRY_IDS, book_controls, book_layout, collection_rows
from .data import SPECIES_BY_ID
from .game import Keys, Session
from .gamepad import BUTTON_ACTIONS, BUTTON_X
from .platform import Input, Text
from .sim import Catch, Hook, RNG, SetLine, State
from .ui import UI, shop_rows
from .world import World


class ShinyRollChecks(unittest.TestCase):
    def setUp(self):
        self.book = {"species": {}, "tracked": None}
        self.journal = {"bluegill": {"count": 5}, "carp": {"count": 5}}

    def test_ten_thousand_tracked_catches_never_exceed_fifty(self):
        self.assertTrue(set_shiny_target(self.book, self.journal, "bluegill"))
        rng = RNG(41013)
        gap, longest, shinies = 0, 0, 0
        for _ in range(10_000):
            gap += 1
            shiny = roll_shiny(self.book, self.journal, "bluegill", rng)
            self.assertLessEqual(gap, SHINY_PITY_CATCHES)
            if shiny:
                longest = max(longest, gap)
                shinies += 1
                gap = 0
            self.assertEqual(self.book["species"]["bluegill"]["since_shiny"], gap)
        self.assertEqual(longest, 50)
        self.assertGreaterEqual(shinies, 200)

    def test_untracked_frequency_is_within_ten_percent_of_one_in_sixty_four(self):
        rng, trials = RNG(41014), 128_000
        shinies = sum(roll_shiny(self.book, self.journal, "bluegill", rng)
                      for _ in range(trials))
        self.assertLessEqual(abs(shinies / trials - SHINY_CHANCE), SHINY_CHANCE * .1)
        # Tracking a different species also uses ordinary odds for this one.
        set_shiny_target(self.book, self.journal, "carp")
        other_book = {"species": {}, "tracked": None}
        left, right = RNG(41015), RNG(41015)
        self.assertEqual([roll_shiny(self.book, self.journal, "bluegill", left) for _ in range(500)],
                         [roll_shiny(other_book, self.journal, "bluegill", right) for _ in range(500)])

    def test_boundary_roll_and_natural_shiny_each_reset_counter(self):
        set_shiny_target(self.book, self.journal, "bluegill")
        no_shiny = Mock()
        no_shiny.chance.return_value = False
        for _ in range(49):
            self.assertFalse(roll_shiny(self.book, self.journal, "bluegill", no_shiny))
        self.assertTrue(roll_shiny(self.book, self.journal, "bluegill", no_shiny))
        self.assertEqual(no_shiny.chance.call_count, 50)
        no_shiny.chance.assert_called_with(1 / 64)
        self.assertEqual(shiny_tracker(self.book, self.journal, "bluegill")["since_shiny"], 0)
        natural = Mock()
        natural.chance.return_value = True
        self.assertTrue(roll_shiny(self.book, self.journal, "bluegill", natural))
        self.assertEqual(shiny_tracker(self.book, self.journal, "bluegill")["since_shiny"], 0)

    def test_verified_targets_switch_and_pause_without_resetting_any_counter(self):
        no_shiny = Mock()
        no_shiny.chance.return_value = False
        for sid, count in (("bluegill", 49), ("carp", 17)):
            for _ in range(count):
                roll_shiny(self.book, self.journal, sid, no_shiny)
        counts = deepcopy(self.book["species"])
        for sid in ("bluegill", "carp", None, "bluegill"):
            self.assertTrue(set_shiny_target(self.book, self.journal, sid))
            self.assertEqual(self.book["species"], counts)
        for sid in ("bullhead", *LEGENDARY_IDS, "unknown"):
            self.assertFalse(set_shiny_target(self.book, self.journal, sid))
            self.assertEqual(self.book["tracked"], "bluegill")
        self.assertTrue(roll_shiny(self.book, self.journal, "bluegill", no_shiny))
        self.assertEqual(self.book["species"]["carp"]["since_shiny"], 17)

    def test_stale_unverified_target_does_not_apply_pity(self):
        self.book.update({"tracked": "bluegill", "species": {
            "bluegill": {"since_shiny": 49}}})
        self.journal["bluegill"]["count"] = 4
        rng = Mock()
        rng.chance.return_value = False
        self.assertFalse(roll_shiny(self.book, self.journal, "bluegill", rng))
        self.assertFalse(shiny_tracker(self.book, self.journal, "bluegill")["tracked"])

    def test_legendaries_and_unknown_species_have_no_shiny_roll(self):
        rng = Mock()
        for sid in (*LEGENDARY_IDS, "unknown"):
            self.assertFalse(roll_shiny(self.book, self.journal, sid, rng))
        self.assertFalse(roll_shiny(self.book, self.journal, "bluegill", rng, legendary=True))
        self.assertEqual(self.book["species"], {})
        rng.chance.assert_not_called()
        self.assertFalse(Catch("bluegill", 1, 1, 0, "flats", "worm", 8,
                               shiny=True, legendary=True).shiny)

    def test_malformed_counter_defaults_safely_and_status_is_read_only(self):
        for value in (None, "bad", -9, float("inf"), {}):
            self.book["species"]["bluegill"] = {"since_shiny": value, "future": "keep"}
            before = deepcopy(self.book)
            self.assertEqual(shiny_tracker(self.book, self.journal, "bluegill")["since_shiny"], 0)
            self.assertEqual(self.book, before)
            rng = Mock()
            rng.chance.return_value = False
            roll_shiny(self.book, self.journal, "bluegill", rng)
            self.assertEqual(self.book["species"]["bluegill"]["since_shiny"], 1)
            self.assertEqual(self.book["species"]["bluegill"]["future"], "keep")


class ShinyIntegrationChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World()

    def setUp(self):
        self.state = State.new(self.world, seed=41016)
        self.temporary = tempfile.TemporaryDirectory(prefix="trotline-shiny-")
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "save.json"

    def spawn_catch(self, state, *, natural_shiny=False):
        """Create a real hooked catch while retaining older occupied hooks."""
        line = SetLine("std", "worm", 0, 0, 12, 0, "flats", [Hook(True)])
        state.lines.append(line)
        with patch("fishing.sim.species_rates", return_value={"bluegill": 1}), \
                patch.object(state, "_roll_weight", return_value=.75), \
                patch.object(state.rng, "chance", side_effect=[True, natural_shiny]):
            self.assertEqual(state._one_span(1), (1, 0))
        return line.hooks[0].catch

    def test_roll_occurs_once_on_creation_and_never_on_check_or_reload(self):
        state = self.state
        state.journal["bluegill"]["count"] = 5
        state.v2["book"]["species"]["bluegill"] = {"since_shiny": 49}
        state.set_shiny_tracker("bluegill")
        state.lines = [SetLine("std", "worm", 0, 0, 12, 0, "flats", [Hook(True)])]
        with patch("fishing.sim.species_rates", return_value={"bluegill": 1}), \
                patch.object(state, "_roll_weight", return_value=.75), \
                patch.object(state.rng, "chance", side_effect=[True, False]) as chance:
            self.assertEqual(state._one_span(1), (1, 0))
            self.assertEqual(chance.call_count, 2)  # bite, then the one shiny roll
            self.assertEqual(state._one_span(.01), (0, 0))
            self.assertEqual(chance.call_count, 2)
        catch = state.lines[0].hooks[0].catch
        self.assertTrue(catch.shiny)
        self.assertTrue(catch.treasured)
        self.assertEqual(state.journal["bluegill"]["count"], 6)
        page = state.v2["book"]["species"]["bluegill"]
        self.assertEqual((page["since_shiny"], page["shiny"]), (0, 0))
        self.assertNotIn("shiny", page["found"][0])
        state.save(self.path, update_stamp=False)
        loaded = State.load(self.path, self.world)
        self.assertEqual(loaded.rng.s, state.rng.s)
        self.assertEqual(loaded.v2["book"], state.v2["book"])
        self.assertTrue(loaded.lines[0].hooks[0].catch.shiny)
        self.assertEqual(loaded.lines[0].hooks[0].catch.shiny_since_before, 49)
        self.assertEqual(loaded.lines[0].hooks[0].catch.shiny_observation, 0)
        self.assertIsNone(loaded.take_hook(0, 0, "release"))
        self.assertEqual(loaded.v2["book"]["species"]["bluegill"]["shiny"], 1)
        self.assertTrue(loaded.v2["book"]["species"]["bluegill"]["found"][0]["shiny"])
        self.assertEqual(loaded.journal["bluegill"]["count"], 6)
        rows = collection_rows(loaded, None, 2)
        self.assertIn("✦ Bluegill", [row[0] for row in rows])

    def test_forced_shiny_getaway_refunds_pity_across_reload_and_target_changes(self):
        for reload in (False, True):
            for resolution, snag in product(("keep", "release", "all"), (False, True)):
                with self.subTest(reload=reload, resolution=resolution, snag=snag):
                    state = State.new(self.world, seed=41017)
                    state.journal["bluegill"]["count"] = 5
                    state.journal["carp"]["count"] = 5
                    state.v2["book"]["species"]["bluegill"] = {"since_shiny": 49}
                    state.v2["book"]["species"]["carp"] = {
                        "found": [], "shiny": 0, "since_shiny": 0}
                    state.set_shiny_tracker("bluegill")
                    self.assertTrue(self.spawn_catch(state).shiny)
                    self.assertEqual(collection_rows(state, None, 2), [])
                    with patch.dict(BOATS, {"jon": replace(BOATS["jon"], traits=("trophy_rail",))}):
                        self.assertIsNotNone(state.mount_shiny_trophy("bluegill"))
                    if reload:
                        state.save(self.path, update_stamp=False)
                        state = State.load(self.path, self.world)
                    state.set_shiny_tracker("carp")
                    rng_state = state.rng.s
                    if snag:
                        state.x, state.z, state.speed = 6., 0., 1.2
                        state._maybe_snag(self.world)
                        self.assertIsNone(state.lines[0].hooks[0].catch)
                        self.assertFalse(state.lines[0].hooks[0].baited)
                    else:
                        self.assertEqual(state._one_span(14), (0, 1))
                    self.assertEqual(state.rng.s, rng_state)
                    entry = state.v2["book"]["species"]["bluegill"]
                    self.assertEqual((entry["shiny"], entry["since_shiny"]), (0, 49))
                    self.assertNotIn("shiny", entry["found"][0])
                    self.assertEqual(collection_rows(state, None, 2), [])
                    self.assertEqual(state.well, [])
                    self.assertEqual(state.journal["bluegill"]["count"], 6)
                    state.set_shiny_tracker("bluegill")
                    replacement = self.spawn_catch(state)
                    self.assertTrue(replacement.shiny)
                    if resolution == "all":
                        self.assertIn("kept 1", state.take_all(1))
                    else:
                        self.assertIsNone(state.take_hook(1, 0, resolution))
                    self.assertEqual((entry["shiny"], entry["since_shiny"]), (1, 0))
                    self.assertTrue(entry["found"][1]["shiny"])
                    self.assertIsNone(replacement.shiny_since_before)
                    state.save(self.path, update_stamp=False)
                    loaded = State.load(self.path, self.world)
                    self.assertEqual(loaded.v2["book"], state.v2["book"])

    def test_overlapping_pending_shinies_refund_in_either_escape_order(self):
        for order in ((0, 3), (3, 0)):
            with self.subTest(order=order):
                state = State.new(self.world, seed=41018)
                state.journal["bluegill"]["count"] = 5
                state.v2["book"]["species"]["bluegill"] = {"since_shiny": 49}
                state.set_shiny_tracker("bluegill")
                self.spawn_catch(state)  # forced; 49 before it
                for _ in range(2):
                    self.assertFalse(self.spawn_catch(state).shiny)
                self.assertTrue(self.spawn_catch(state, natural_shiny=True).shiny)
                for _ in range(3):
                    self.assertFalse(self.spawn_catch(state).shiny)
                for index in order:
                    state.lines[index].hooks[0].catch.age = 12.5
                    self.assertEqual(state._one_span(1), (0, 1))
                    state.save(self.path, update_stamp=False)
                    state = State.load(self.path, self.world)
                entry = state.v2["book"]["species"]["bluegill"]
                self.assertEqual((entry["shiny"], entry["since_shiny"]), (0, 54))
                self.assertFalse(any(row.get("shiny") for row in entry["found"]))
                self.assertEqual(collection_rows(state, None, 2), [])
                self.assertTrue(self.spawn_catch(state).shiny)

    def test_confirmed_shiny_keeps_the_correct_counter_when_another_escapes(self):
        for confirmed, escaped, expected in ((0, 3, 5), (3, 0, 3)):
            with self.subTest(confirmed=confirmed):
                state = State.new(self.world, seed=41019)
                state.journal["bluegill"]["count"] = 5
                state.v2["book"]["species"]["bluegill"] = {"since_shiny": 49}
                state.set_shiny_tracker("bluegill")
                self.spawn_catch(state)
                for _ in range(2):
                    self.spawn_catch(state)
                self.spawn_catch(state, natural_shiny=True)
                for _ in range(3):
                    self.spawn_catch(state)
                self.assertIsNone(state.take_hook(confirmed, 0, "keep"))
                state.lines[escaped].hooks[0].catch.age = 12.5
                self.assertEqual(state._one_span(1), (0, 1))
                entry = state.v2["book"]["species"]["bluegill"]
                self.assertEqual((entry["shiny"], entry["since_shiny"]), (1, expected))
                self.assertTrue(entry["found"][confirmed]["shiny"])
                self.assertNotIn("shiny", entry["found"][escaped])

    def test_counter_target_and_next_rng_sequence_round_trip(self):
        state = self.state
        for sid, counter in (("bluegill", 49), ("carp", 23)):
            state.journal[sid]["count"] = 5
            state.v2["book"]["species"][sid] = {"since_shiny": counter, "shiny": 2, "found": [],
                                                "future_field": ["preserve"]}
        state.set_shiny_tracker("bluegill")
        state.well = [Catch("bluegill", .75, 1, 0, "flats", "worm", 8,
                            shiny=True, treasured=False)]
        state.save(self.path, update_stamp=False)
        loaded = State.load(self.path, self.world)
        self.assertEqual(loaded.v2["book"], state.v2["book"])
        self.assertTrue(loaded.well[0].shiny)
        self.assertFalse(loaded.well[0].treasured)
        for sid in ("carp", None, "bluegill"):
            loaded.set_shiny_tracker(sid)
        self.assertEqual(loaded.v2["book"], state.v2["book"])
        for _ in range(256):
            for sid in ("bluegill", "carp"):
                self.assertEqual(roll_shiny(state.v2["book"], state.journal, sid, state.rng),
                                 roll_shiny(loaded.v2["book"], loaded.journal, sid, loaded.rng))
        self.assertEqual(loaded.v2["book"], state.v2["book"])
        self.assertEqual(loaded.rng.s, state.rng.s)

    def test_old_saved_counters_are_preserved_and_new_records_start_at_zero(self):
        self.assertEqual(shiny_tracker(self.state.v2["book"], self.state.journal,
                                       "bluegill")["since_shiny"], 0)
        self.state.journal["bluegill"]["count"] = 5
        self.state.v2["book"]["species"]["bluegill"] = {
            "found": [], "shiny": 0, "since_shiny": 3}
        self.state.save(self.path, update_stamp=False)
        loaded = State.load(self.path, self.world)
        self.assertEqual(loaded.v2["book"]["species"]["bluegill"]["since_shiny"], 3)

    def test_three_times_value_and_treasured_bulk_sale_protection(self):
        normal = Catch("bluegill", .75, .65, 0, "flats", "worm", 8)
        shiny = Catch("bluegill", .75, .65, 0, "flats", "worm", 8, shiny=True)
        self.assertEqual(shiny.value(), round(normal.value() * 3, 2))
        self.assertTrue(shiny.treasured)
        self.state.well = [normal, shiny]
        money = self.state.money
        self.state.sell_all()
        self.assertEqual(self.state.money, round(money + normal.value(), 2))
        self.assertEqual(self.state.well, [shiny])
        self.assertIn("✦ Bluegill", shop_rows(self.state, 0)[1].label)
        self.state.toggle_treasured(0)
        money = self.state.money
        self.state.sell_all()
        self.assertEqual(self.state.money, round(money + shiny.value(), 2))
        self.assertEqual(self.state.well, [])

    def test_mount_hook_requires_owned_rail_and_keeps_book_record(self):
        self.state._note_journal(Catch("bluegill", 1, 1, 0, "flats", "worm", 8, shiny=True))
        before = deepcopy(self.state.v2["book"])
        self.assertIsNotNone(self.state.mount_shiny_trophy("bluegill"))
        self.assertIsNotNone(self.state.mount_shiny_trophy("bluegill", boat_id="pontoon"))
        with patch.dict(BOATS, {"jon": replace(BOATS["jon"], traits=("trophy_rail",))}):
            self.assertIsNotNone(self.state.mount_shiny_trophy("carp"))
            self.assertIsNotNone(self.state.mount_shiny_trophy("old_lantern"))
            for _ in range(2):
                self.assertIsNone(self.state.mount_shiny_trophy("bluegill"))
        self.assertEqual(self.state.v2["boat_extras"]["jon"]["shiny_trophies"], ["bluegill"])
        self.assertEqual(self.state.v2["book"], before)
        self.state.save(self.path, update_stamp=False)
        loaded = State.load(self.path, self.world)
        self.assertEqual(loaded.v2["boat_extras"], self.state.v2["boat_extras"])

    def test_book_tracker_works_with_keyboard_mouse_and_controller_and_saves(self):
        state = self.state
        session = Session(self.world, self.path, state, False)
        ui = session.ui
        ui.mode, ui.journal_page = "journal", 1
        ui.book_entry_i = ENTRY_IDS.index("bluegill")
        layout = book_layout(480, 270)
        self.assertNotIn("tracker", book_controls(layout, state, ui))
        session.tick(Keys(pressed={"f"}), .01)
        self.assertIsNone(state.v2["book"]["tracked"])
        state.journal["bluegill"]["count"] = 5
        state.v2["book"]["species"]["bluegill"] = {"since_shiny": 37}
        rng_state, minute = state.rng.s, state.game_minutes
        session.tick(Keys(pressed={"f"}), .01)
        self.assertEqual(State.load(self.path, self.world).v2["book"]["tracked"], "bluegill")
        x, y, _w, _h = book_controls(layout, state, ui)["tracker"]
        # Pointer input resolves against the last rendered frame; draw once so the
        # tracker control is published at this viewport before the click.
        renderer = UI(Text(), self.world)
        self.addCleanup(renderer.close)
        renderer.draw(np.zeros((270, 480, 3), np.uint8), state, ui)
        keys = Input()
        keys.viewport, keys.mouse_click = (480, 270), (x + 5, y + 5)
        session.tick(keys, .01)
        self.assertIsNone(state.v2["book"]["tracked"])
        keys = Input()
        keys.device = "gamepad"
        keys.gamepad_pressed = set(BUTTON_ACTIONS[BUTTON_X])
        session.tick(keys, .01)
        self.assertEqual(state.v2["book"]["tracked"], "bluegill")
        self.assertEqual(state.v2["book"]["species"]["bluegill"]["since_shiny"], 37)
        self.assertEqual((state.rng.s, state.game_minutes), (rng_state, minute))
        ui.book_entry_i = ENTRY_IDS.index(LEGENDARY_IDS[0])
        self.assertNotIn("tracker", book_controls(layout, state, ui))
        # A future save can contain Verified pages beyond this build's roster.
        future = "future_verified_fish"
        state.journal[future] = {"count": 5}
        from .book import SPECIES_RUMORS, Rumor
        with patch.dict(SPECIES_RUMORS, {future: Rumor("A future page.", "A future cat")}):
            self.assertIsNone(state.set_shiny_tracker(future))
        self.assertEqual(state.v2["book"]["tracked"], future)

    def test_sparkle_marker_renders_in_both_fonts_and_uses_the_bounded_cache(self):
        text = Text()
        self.addCleanup(text.close)
        for family in ("mono", "dyslexia"):
            for size in (12, 24, 40):
                image = text.render("✦", size, (60, 80, 70), family)
                height, width = image.shape[:2]
                self.assertGreater(image[height // 2, width // 2, 3], 0)
                self.assertTrue(np.all(image[0, :, 3] == 0))
                self.assertEqual(image.shape[2], 4)
                label = text.render("A ✦ Bluegill", size, (60, 80, 70), family)
                self.assertIs(label, text.render("A ✦ Bluegill", size, (60, 80, 70), family))
                self.assertLessEqual(text.cache_bytes, text.cache_limit)
        # Some CI fonts extend a surface for descenders; reproduce that
        # independently of which native fonts happen to be installed here.
        def fragments(value, *_args):
            height = 15 if value == " Bluegill" else 14
            return np.full((height, 8, 4), 255, np.uint8)
        with patch.object(text, "render", side_effect=fragments):
            composed = text._sparkle_text("A ✦ Bluegill", 12, (60, 80, 70), "mono")
        self.assertEqual(composed.shape, (15, 24, 4))
        self.assertEqual(composed[-1, 0, 3], 0)
        self.assertEqual(composed[-1, -1, 3], 255)


if __name__ == "__main__":
    unittest.main()
