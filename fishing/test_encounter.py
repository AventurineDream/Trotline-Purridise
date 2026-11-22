"""V1-37: a legendary's encounter in the haul, its book page and photo (02 §7.2)."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from . import encounter, skipper, skipperlook
from .catmesh import PATTERNS
from .caldera import reflection_strength
from .content import load_content
from .game import Keys, Session
from .legendary import LEGENDARY_DATA
from .platform import Text
from .savepaths import load_game_save
from .sim import Catch, Hook, SetLine, State
from .ui import UI, UIState
from .weather import lighting_at
from .world import World


def _legendary(legendary_id: str, lake: str = "briar") -> Catch:
    row = LEGENDARY_DATA[legendary_id]
    return Catch(legendary_id, row["weight_lb"], 1.0, 0.0, "open", row["bait"], 21.0, lake_id=lake,
                 catch_game_minute=0.0, legendary=True, disposition="release")


class Scene(unittest.TestCase):
    def test_the_scene_lasts_four_to_six_seconds_and_every_beat_ends_inside_it(self):
        self.assertTrue(4.0 <= encounter.SCENE_S <= 6.0)
        for span in (encounter.STILL, encounter.HUM, encounter.RISE, encounter.NAME):
            self.assertTrue(0.0 <= span[0] < span[1] <= encounter.SCENE_S, span)
        end = encounter.look(encounter.SCENE_S)
        self.assertEqual((end["still"], end["rise"], end["name"], end["bars"]), (1.0, 1.0, 1.0, 1.0))
        start = encounter.look(0.0)
        self.assertEqual((start["still"], start["rise"], start["name"]), (0.0, 0.0, 0.0))
        self.assertGreater(encounter.look(1.8)["tremble"], 0.9)  # the hum at its height
        self.assertEqual(encounter.look(3.5)["tremble"], 0.0)  # and over before it surfaces

    def test_ten_legendaries_are_caught_and_each_has_its_scene_and_photo(self):
        caught = encounter.caught_ids()
        self.assertEqual(len(caught), 10)
        self.assertNotIn("star_whale", caught)
        self.assertNotIn("whiskered_guardian", caught)
        for legendary_id in caught:
            sprite = encounter.fish_sprite(legendary_id)
            self.assertEqual(sprite.shape, (encounter.SPRITE[1], encounter.SPRITE[0], 4))
            self.assertGreater(int((sprite[:, :, 3] > 0).sum()), 3000, legendary_id)
            photo = encounter.photo(legendary_id, 240, 150, (0.72, 0.57, 0.44))
            self.assertEqual(photo.shape, (150, 240, 3))
            self.assertFalse(photo.flags.writeable)

    def test_the_idle_sways_the_tail_and_reduced_motion_holds_the_pose(self):
        legendary_id = "nebula_weaver"
        shifts = np.stack([encounter.idle_offsets(legendary_id, t) for t in np.linspace(0.0, 3.0, 13)])
        cols = np.flatnonzero(encounter.fish_sprite(legendary_id)[:, :, 3].max(axis=0))
        spread = shifts.max(axis=0) - shifts.min(axis=0)
        self.assertGreater(spread[cols.min() + 4], spread[cols.max() - 4])  # the tail moves more than the snout
        self.assertGreater(int(spread.max()), 2)
        self.assertFalse(np.array_equal(encounter.posed(legendary_id, 0.0), encounter.posed(legendary_id, 0.7)))
        rest = encounter.fish_sprite(legendary_id)
        self.assertIs(encounter.posed(legendary_id, 0.7, reduced=True), rest)
        held = encounter.look(0.0, reduced=True)
        self.assertEqual((held["still"], held["rise"], held["name"], held["tremble"]), (1.0, 1.0, 1.0, 0.0))

    def test_the_still_water_reaches_both_renderers_on_every_lake(self):
        for lake in ("briar", "cedar", "flathead", "crater", "nebula"):
            state = State.new(World(lake), seed=3)
            state.game_minutes = 360  # noon: Crater's own clear-night mirror is off
            light = lighting_at(state.game_minutes, state)
            before = reflection_strength(state, light)
            state.encounter_still = 1.0
            self.assertEqual(reflection_strength(state, light), 1.0, lake)
            state.encounter_still = 0.0
            self.assertEqual(reflection_strength(state, light), before, lake)

    def test_the_winch_variant_and_the_fire_lizard_beat(self):
        state = State.new(World("nebula"), seed=3)
        self.assertEqual(encounter.variant(state), "hands")
        state.v2["profile"].setdefault("tools", []).append("zero_g_winch")
        self.assertEqual(encounter.variant(state), "winch")
        self.assertEqual(encounter.bespoke("caldera_fire_lizard")["stamp"], "NOT A FISH!")
        self.assertIsNotNone(encounter.glow_colour("caldera_fire_lizard"))
        self.assertEqual(encounter.bespoke("old_lantern"), {})

    def test_presented_is_kept_on_the_page(self):
        v2 = {"legendaries": {"old_lantern": {"records": [{"weight": 38.0}]}}}
        self.assertFalse(encounter.presented(v2, "old_lantern"))
        encounter.mark_presented(v2, "old_lantern")
        self.assertTrue(encounter.presented(v2, "old_lantern"))
        self.assertEqual(v2["legendaries"]["old_lantern"]["records"], [{"weight": 38.0}])
        encounter.mark_presented(v2, "lily_queen")  # a page with no record yet is created
        self.assertTrue(encounter.presented(v2, "lily_queen"))


class InTheHaul(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "save.json"
        self.content = load_content()
        self.world = World("briar")
        state = State.new(self.world, seed=37)
        state.x, state.z = self.world.slip.world(60.0, 0.0)
        state.speed, state.anchored = 0.0, True
        state.toasts.clear()
        hooks = [Hook(True) for _ in range(4)]
        hooks[0] = Hook(False, _legendary("old_lantern"))
        hooks[1] = Hook(False, Catch("bluegill", 0.6, 1.0, 0.0, "open", "worm", 21.0))
        state.lines = [SetLine("heavy", "lantern_liver", state.x - 3, state.z, state.x + 3, state.z, "open", hooks)]
        state._note_journal(hooks[0].catch)
        with patch("fishing.game.load_content", return_value=self.content):
            self.session = Session(self.world, self.path, state, True)
        self.session.ui.mode = "play"

    def to_scene(self):
        self.session._open_e()
        self.assertEqual(self.session.ui.mode, "haul")
        for _ in range(40):
            if self.session.ui.haul_phase == "encounter":
                return
            self.session.tick(Keys(), 0.05)
        self.fail("the legendary's scene never began")

    def test_a_first_encounter_plays_through_and_nothing_skips_or_hurries_it(self):
        self.to_scene()
        ui = self.session.ui
        self.assertEqual(ui.haul_legendary, "old_lantern")
        sounds, captions, elapsed = [], set(), 0.0
        while ui.haul_phase == "encounter":
            self.session.tick(Keys(pressed={"esc", "x"}, held={"e"}), 0.1)
            elapsed += 0.1
            sounds.append(self.session.sound)
            captions.add(ui.caption)
            self.assertEqual(ui.mode, "haul")
        self.assertAlmostEqual(elapsed, encounter.SCENE_S, delta=0.11)  # in real time, not three times faster
        self.assertEqual(sounds.count("hum"), 1)
        self.assertIn("The line hums.", captions)  # the hum reads with no sound
        self.assertEqual(ui.haul_phase, "card")
        self.assertTrue(encounter.presented(self.session.state.v2, "old_lantern"))
        self.assertEqual(self.session.state.encounter_still, 1.0)  # the lake stays glassy on the page
        self.session.tick(Keys(pressed={"x"}), 0.1)
        self.assertEqual((ui.haul_phase, ui.haul_index), ("card", 0))  # a key held through the scene doesn't turn it
        held = 0.1
        while ui.haul_index == 0:
            self.session.tick(Keys(), 0.1)
            held += 0.1
        self.assertAlmostEqual(held, encounter.PHOTO_S, delta=0.11)
        self.assertEqual(ui.haul_legendary, "")

    def test_a_seen_encounter_can_be_skipped_or_hurried(self):
        encounter.mark_presented(self.session.state.v2, "old_lantern")
        self.to_scene()
        self.session.tick(Keys(held={"e"}), 0.5)
        self.assertAlmostEqual(self.session.ui.haul_phase_timer, 1.5)  # hold E: three times as fast
        self.session.tick(Keys(pressed={"esc"}), 0.05)
        self.assertEqual(self.session.ui.haul_phase, "card")  # Esc skips to the book page
        self.assertEqual(self.session.ui.mode, "haul")
        for _ in range(6):
            self.session.tick(Keys(), 0.1)
        self.session.tick(Keys(pressed={"x"}), 0.05)  # once it has stood a moment, a key turns it
        self.assertEqual(self.session.ui.haul_index, 1)

    def test_the_lake_stills_while_the_fish_surfaces_and_returns_after(self):
        self.to_scene()
        self.assertEqual(self.session.state.encounter_still, 0.0)
        for _ in range(8):
            self.session.tick(Keys(), 0.1)
        self.assertGreater(self.session.state.encounter_still, 0.5)
        self.session.tick(Keys(pressed={"esc"}), 0.05)  # the first time, Esc does nothing
        self.assertEqual(self.session.ui.haul_phase, "encounter")
        for _ in range(int((encounter.SCENE_S + encounter.PHOTO_S) / 0.1) + 2):
            self.session.tick(Keys(), 0.1)
        self.assertEqual(self.session.ui.haul_index, 1)
        self.assertEqual(self.session.state.encounter_still, 0.0)

    def test_an_instant_haul_still_shows_a_first_encounter_then_the_summary(self):
        self.session.state.v2["settings"]["haul_speed"] = "instant"
        self.session._open_e()
        ui = self.session.ui
        self.assertEqual((ui.mode, ui.haul_phase, ui.haul_index), ("haul", "encounter", 0))
        for _ in range(int((encounter.SCENE_S + encounter.PHOTO_S) / 0.1) + 3):
            self.session.tick(Keys(), 0.1)
        self.assertEqual(ui.mode, "check")
        # Seen once, an instant haul goes straight to the summary.
        ui.mode = "play"
        self.session._open_e()
        self.assertEqual(ui.mode, "check")

    def test_the_seen_scene_survives_a_save_and_reload(self):
        self.to_scene()
        for _ in range(int(encounter.SCENE_S / 0.1) + 2):
            self.session.tick(Keys(), 0.1)
        self.session.save()
        world, state, _ = load_game_save(self.path, State, World)
        self.assertTrue(encounter.presented(state.v2, "old_lantern"))

    def test_the_winch_hums_steady_and_draws_the_line_without_a_sway(self):
        self.session.state.v2["profile"].setdefault("tools", []).append("zero_g_winch")
        self.to_scene()
        sounds = []
        for _ in range(12):
            self.session.tick(Keys(), 0.1)
            sounds.append(self.session.sound)
        self.assertIn("hum_winch", sounds)
        self.assertEqual(self.session.ui.caption, "The winch hums, steady.")
        self.assertNotIn("hum", sounds)


class Drawn(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = Text()
        cls.world = World("crater")
        cls.ui = UI(cls.text, cls.world)

    @classmethod
    def tearDownClass(cls):
        cls.text.close()

    def state(self, legendary_id="caldera_fire_lizard", **settings):
        state = State.new(self.world, seed=5)
        state.toasts.clear()
        state.tutorial = 4
        state.v2["settings"].update(settings)
        hooks = [Hook(True) for _ in range(3)]
        hooks[1] = Hook(False, _legendary(legendary_id, "crater"))
        state.lines = [SetLine("heavy", "ember_dumpling", state.x, state.z, state.x + 5, state.z, "springs", hooks)]
        state._note_journal(hooks[1].catch)
        return state

    def draw(self, state, phase, t=0.0, size=(640, 360)):
        frame = np.full((size[1], size[0], 3), (40, 60, 70), np.uint8)
        self.ui.draw(frame, state, UIState(mode="haul", has_save=True, check_line=0, haul_index=1,
                                           haul_phase=phase, haul_phase_timer=t, haul_timer=1.0,
                                           haul_legendary=state.lines[0].hooks[1].catch.species))
        return frame

    def test_the_fish_surfaces_beside_the_boat_and_moves_in_its_idle(self):
        state = self.state()
        before, surfaced = self.draw(state, "encounter", 0.0), self.draw(state, "encounter", 4.0)
        right = (slice(150, 290), slice(320, 620))  # the water beside the boat
        self.assertGreater(float(np.abs(surfaced[right].astype(int) - before[right].astype(int)).mean()), 8.0)
        later = self.draw(state, "encounter", 4.6)
        self.assertFalse(np.array_equal(surfaced[right], later[right]))  # the idle keeps it moving

    def test_reduced_motion_holds_still_but_shows_every_beat_finished(self):
        state = self.state(reduced_motion=True)
        first, last = self.draw(state, "encounter", 0.2), self.draw(state, "encounter", 4.6)
        right = (slice(150, 290), slice(320, 620))
        self.assertTrue(np.array_equal(first[right], last[right]))
        moving = self.state()
        self.assertGreater(float(np.abs(first[right].astype(int) - self.draw(moving, "encounter", 0.2)[right].astype(int)).mean()), 4.0)

    def test_the_book_page_shows_the_photo_at_every_size(self):
        state = self.state()
        for size in ((1280, 720), (640, 360), (480, 270)):
            page = self.draw(state, "card", 0.0, size)
            photo = encounter.photo("caldera_fire_lizard", 64, 40, skipper.mitt_rgb(state))
            self.assertGreater(int((page == np.asarray((232, 224, 200), np.uint8)).all(axis=2).sum()), 1000, size)
            self.assertIsNotNone(photo)

    def test_the_photo_shows_the_paw_of_the_skipper_the_player_dressed(self):
        state = self.state()
        default = encounter.photo("caldera_fire_lizard", 240, 150, skipper.mitt_rgb(state))
        # A tuxedo in ink wears white mitts: the paw on the gunwale turns pale, the rest stays.
        look = skipperlook.cycle(skipperlook.saved(state), "pattern",
                                 PATTERNS.index("tuxedo") - PATTERNS.index(skipperlook.DEFAULT["pattern"]))
        state.v2["skipper"] = skipperlook.cycle(look, "base", [n for n, _c in skipperlook.COAT_SWATCHES].index("Ink"))
        tuxedo = encounter.photo("caldera_fire_lizard", 240, 150, skipper.mitt_rgb(state))
        paw = default[int(150 * 0.86), int(240 * 0.13)].astype(int), tuxedo[int(150 * 0.86), int(240 * 0.13)].astype(int)
        self.assertGreater(int(paw[1].sum()) - int(paw[0].sum()), 60)
        np.testing.assert_array_equal(default[:100], tuxedo[:100])

    def test_the_legendary_page_in_the_book_carries_its_photo(self):
        from .bookview import ENTRY_IDS
        state = self.state("caldera_fire_lizard")
        frame = np.full((720, 1280, 3), (40, 60, 70), np.uint8)
        panel = UIState(mode="journal", has_save=True, journal_page=1,
                        book_entry_i=ENTRY_IDS.index("caldera_fire_lizard"))
        self.ui.draw(frame, state, panel)
        empty = self.state("caldera_fire_lizard")
        empty.v2["legendaries"]["caldera_fire_lizard"]["records"] = []
        bare = np.full((720, 1280, 3), (40, 60, 70), np.uint8)
        self.ui.draw(bare, empty, UIState(mode="journal", has_save=True, journal_page=1,
                                          book_entry_i=ENTRY_IDS.index("caldera_fire_lizard")))
        border = np.asarray(encounter_view_border(), np.uint8)
        self.assertGreater(int((frame == border).all(axis=2).sum()), 2000)  # the print border
        self.assertEqual(int((bare == border).all(axis=2).sum()), 0)  # no record, no photo


def encounter_view_border():
    from .encounterview import PRINT_BORDER
    return PRINT_BORDER


if __name__ == "__main__":
    unittest.main()
