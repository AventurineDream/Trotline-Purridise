"""Hook-by-hook haul timing, pause, and presentation regressions."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from .game import Keys, Session
from .sim import Catch, Hook, SetLine, State
from .ui import UI, UIState
from .world import World


class TextStub:
    def __init__(self):
        self.calls = []

    def render(self, value, size, color, family="mono"):
        self.calls.append(value)
        return np.zeros((max(1, size), max(1, len(value) * max(1, size // 2)), 4),
                        np.uint8)


class HaulChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World()

    def make_session(self, hook_count=24, *, catch=None):
        temp = tempfile.TemporaryDirectory(prefix="trotline-haul-")
        self.addCleanup(temp.cleanup)
        state = State.new(self.world, seed=121)
        state.x, state.z = self.world.anchors["briar:inlet"].position
        state.speed = 0.0
        state.throttle = state.throttle_setting = 0.0
        state.anchored = True
        hooks = [Hook(True) for _ in range(hook_count)]
        if catch is not None:
            hooks[0] = Hook(False, catch)
            state._note_journal(catch)
        state.lines = [SetLine(
            "std", "worm", state.x - 10, state.z, state.x + 10, state.z,
            "open", hooks,
        )]
        path = Path(temp.name) / "save.json"
        session = Session(self.world, path, state, False)
        session.ui.mode = "play"
        # These tests exercise haul presentation and timing, not dock prompts.
        state.slip_status = lambda _world: None
        return session

    def start_haul(self, session):
        session.tick(Keys(pressed={"e"}), 0.0)
        self.assertEqual(session.ui.mode, "haul")
        self.assertFalse(session.world_running())

    def test_24_hook_normal_haul_completes_in_six_seconds_and_pauses_world(self):
        session = self.make_session(24)
        self.start_haul(session)
        state = session.state
        before = (state.game_minutes, state.minute_acc,
                  state.narrative.active_play_game_minutes, state.anim)

        for _ in range(24):
            session.tick(Keys(), 0.25)

        self.assertEqual(session.ui.mode, "check")
        self.assertEqual((state.game_minutes, state.minute_acc,
                          state.narrative.active_play_game_minutes, state.anim), before)

    def test_quick_instant_and_held_e_use_their_selected_speeds(self):
        quick = self.make_session(24)
        quick.state.v2["settings"]["haul_speed"] = "quick"
        self.start_haul(quick)
        for _ in range(24):
            quick.tick(Keys(), 0.10)
        self.assertEqual(quick.ui.mode, "check")

        instant = self.make_session(24)
        instant.state.v2["settings"]["haul_speed"] = "instant"
        instant.tick(Keys(pressed={"e"}), 0.0)
        self.assertEqual(instant.ui.mode, "check")

        boosted = self.make_session(24)
        self.start_haul(boosted)
        for _ in range(8):
            boosted.tick(Keys(held={"e"}), 0.25)
        self.assertEqual(boosted.ui.mode, "check")

    def test_fish_surfaces_before_card_and_a_key_skips_card_to_next_hook(self):
        fish = Catch("bluegill", 0.75, 1.0, 0.0, "flats", "worm", 8.0)
        session = self.make_session(12, catch=fish)
        self.start_haul(session)
        session.tick(Keys(), 0.25)
        self.assertEqual(session.ui.haul_phase, "surface")
        session.tick(Keys(), 0.24)
        self.assertEqual(session.ui.haul_phase, "card")
        session.tick(Keys(pressed={"space"}), 0.0)
        self.assertEqual(session.ui.haul_index, 1)
        self.assertEqual(session.ui.haul_phase, "rise")

    def test_reduced_motion_omits_splash_particles_and_sway(self):
        fish = Catch("bluegill", 0.75, 1.0, 0.0, "flats", "worm", 8.0)
        session = self.make_session(12, catch=fish)
        state = session.state
        state.v2["settings"]["reduced_motion"] = True
        ui = UI(TextStub(), self.world)
        ui_state = UIState(mode="haul", check_line=0, haul_index=0,
                           haul_phase="surface", haul_counts_before={"bluegill": 0})
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        with patch.object(ui, "_haul_splashes", wraps=ui._haul_splashes) as splashes:
            ui.draw(frame, state, ui_state)
            splashes.assert_not_called()
        self.assertEqual(ui._haul_sway(ui_state, True), 0.0)
        self.assertTrue(np.any(frame))

    def test_fish_card_shows_new_and_shiny_badges(self):
        text = TextStub()
        ui = UI(text, self.world)
        frame = np.zeros((720, 1280, 3), dtype=np.uint8)
        normal = Catch("bluegill", 0.75, 1.0, 0.0, "flats", "worm", 8.0)
        session = self.make_session(12, catch=normal)
        ui_state = UIState(mode="haul", check_line=0, haul_index=0,
                           haul_phase="card", haul_counts_before={"bluegill": 0})
        ui.draw(frame.copy(), session.state, ui_state)
        self.assertIn("NEW!", text.calls)

        text.calls.clear()
        stage_session = self.make_session(12, catch=normal)
        stage_state = UIState(
            mode="haul", check_line=0, haul_index=0, haul_phase="card",
            haul_counts_before={"bluegill": 2},
        )
        ui.draw(frame.copy(), stage_session.state, stage_state)
        self.assertIn("STAGE UP!", text.calls)

        text.calls.clear()
        shiny = Catch("channel", 2.4, 1.0, 0.0, "flats", "worm", 8.0, shiny=True)
        shiny_session = self.make_session(12, catch=shiny)
        shiny_state = UIState(mode="haul", check_line=0, haul_index=0,
                              haul_phase="card", haul_counts_before={"channel": 0})
        ui.draw(frame.copy(), shiny_session.state, shiny_state)
        self.assertIn("SHINY  *", text.calls)


if __name__ == "__main__":
    unittest.main()
