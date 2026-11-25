"""Mouse look: the turn arithmetic, the Session look tick, the saved setting, and the camera.

Pins what a player sees when the pointer moves on the water: how far a sweep turns the
view, where the turn stops, when it holds and when it eases back to centre, when a menu,
a lost focus or a story stage takes the view, and that the hull and paws stay on the
unturned eye. Platform delta cases live in test_platform_input.py; help wording lives in
test_help.py. Everything here is deterministic: fixed seeds, fixed time steps, no clock.
"""
import math
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from . import mouselook, pointer
from .game import Keys, Session, THIRD_PERSON_DISTANCE, _camera
from .render import Renderer
from .savepaths import merge_v2_defaults
from .sim import State
from .skipper import paw_mesh
from .software import BASE_PITCH
from .ui import SETTINGS_ROW_COUNT, UI
from .weather import lighting_at
from .world import World

DT = 1 / 60
TURN = mouselook.gain(mouselook.DEFAULT_LEVEL)


class MouseLookMath(unittest.TestCase):
    """The pure turn arithmetic in mouselook: levels, gain, clamps, the turn and the ease."""

    def test_missing_or_unknown_levels_read_as_the_default(self):
        self.assertEqual(mouselook.level({}), "normal")
        self.assertEqual(mouselook.level({"mouse_look": "wild"}), "normal")
        self.assertEqual(mouselook.level({"mouse_look": "gentle"}), "gentle")
        self.assertEqual(mouselook.level(None), "normal")

    def test_cycling_wraps_at_both_ends(self):
        self.assertEqual(mouselook.cycle("normal", 1), "quick")
        self.assertEqual(mouselook.cycle("quick", 1), "off")
        self.assertEqual(mouselook.cycle("off", -1), "quick")
        self.assertEqual(mouselook.cycle("gentle", -1), "off")

    def test_higher_levels_turn_further_and_off_turns_nothing(self):
        self.assertEqual(mouselook.gain("off"), 0.0)
        self.assertLess(mouselook.gain("gentle"), mouselook.gain("normal"))
        self.assertLess(mouselook.gain("normal"), mouselook.gain("quick"))

    def test_a_full_width_sweep_matches_the_angles_the_docs_quote(self):
        """README and the QA checklist quote about 46, 75 and 115 degrees for a full sweep."""
        for name, degrees in (("gentle", 46), ("normal", 75), ("quick", 115)):
            self.assertAlmostEqual(math.degrees(mouselook.gain(name)), degrees, delta=1.0)

    def test_pointer_right_turns_right_and_pointer_up_looks_up(self):
        yaw, pitch = mouselook.turn(0.0, 0.0, 0.1, 0.0, 1.0, 0.0)
        self.assertGreater(yaw, 0.0)
        self.assertEqual(pitch, 0.0)
        yaw, pitch = mouselook.turn(0.0, 0.0, 0.0, -0.1, 1.0, 0.0)
        self.assertEqual(yaw, 0.0)
        self.assertGreater(pitch, 0.0)

    def test_the_turn_stops_at_the_yaw_limit_and_the_keyboard_pitch_bounds(self):
        yaw, _ = mouselook.turn(0.0, 0.0, 50.0, 0.0, TURN, 0.0)
        self.assertAlmostEqual(yaw, mouselook.YAW_LIMIT)
        yaw, _ = mouselook.turn(0.0, 0.0, -50.0, 0.0, TURN, 0.0)
        self.assertAlmostEqual(yaw, -mouselook.YAW_LIMIT)
        _, pitch = mouselook.turn(0.0, 0.0, 0.0, 50.0, TURN, 0.0)
        self.assertAlmostEqual(pitch, mouselook.KEY_LOOK_MIN)
        _, pitch = mouselook.turn(0.0, 0.0, 0.0, -50.0, TURN, 0.0)
        self.assertAlmostEqual(pitch, mouselook.KEY_LOOK_MAX)

    def test_mouse_pitch_shares_the_keyboard_look_budget(self):
        """With the arrows already looking up, the mouse adds only what is left below the limit."""
        _, pitch = mouselook.turn(0.0, 0.0, 0.0, -50.0, TURN, 0.5)
        self.assertAlmostEqual(pitch, mouselook.KEY_LOOK_MAX - 0.5)

    def test_easing_back_is_exponential_and_snaps_when_tiny_or_reduced(self):
        yaw, pitch = mouselook.settle(1.0, -0.5, mouselook.TAU_S)
        self.assertAlmostEqual(yaw, math.exp(-1.0))
        self.assertAlmostEqual(pitch, -0.5 * math.exp(-1.0))
        self.assertEqual(mouselook.settle(1.0, 0.0, 0.0), (1.0, 0.0))
        self.assertEqual(mouselook.settle(0.5 * mouselook.SNAP_RAD, 0.0, 0.0), (0.0, 0.0))
        self.assertEqual(mouselook.settle(1.0, -1.0, 0.1, snap=True), (0.0, 0.0))


class PlaySession(unittest.TestCase):
    """Shared fixture: a fresh save in play mode, with the keyboard look centred."""

    @classmethod
    def setUpClass(cls):
        cls.world = World()

    def make_session(self, level=None):
        temp = tempfile.TemporaryDirectory(prefix="trotline-look-")
        self.addCleanup(temp.cleanup)
        session = Session(self.world, Path(temp.name) / "save.json",
                          State.new(self.world, seed=31), False)
        session.ui.mode = "play"
        session.state.look = 0.0
        if level is not None:
            session.state.v2.setdefault("settings", {})["mouse_look"] = level
        return session

    @staticmethod
    def motion(dx=0.0, dy=0.0):
        """Frame input carrying pointer travel as fractions of the window width."""
        return Keys(mouse_delta=(dx, dy), mouse_moved=True)


class MouseLookSession(PlaySession):
    """The look tick on a Session: when it pans, how far it goes, and how it recentres."""

    def test_motion_in_play_turns_the_view_by_the_pointer_direction(self):
        session = self.make_session()
        session.tick(self.motion(0.1, -0.1), DT)
        self.assertAlmostEqual(session.look_yaw, 0.1 * TURN)
        self.assertAlmostEqual(session.look_pitch, 0.1 * TURN)

    def test_the_turn_is_bounded_in_both_directions(self):
        session = self.make_session()
        for _ in range(30):
            session.tick(self.motion(0.5, -0.5), DT)
        self.assertAlmostEqual(session.look_yaw, mouselook.YAW_LIMIT)
        self.assertAlmostEqual(session.look_pitch, mouselook.KEY_LOOK_MAX)
        for _ in range(30):
            session.tick(self.motion(-0.5, 0.5), DT)
        self.assertAlmostEqual(session.look_yaw, -mouselook.YAW_LIMIT)
        self.assertAlmostEqual(session.look_pitch, mouselook.KEY_LOOK_MIN)

    def test_the_keyboard_look_already_held_shares_the_pitch_budget(self):
        session = self.make_session()
        session.state.look = 0.5
        session.tick(self.motion(0.0, -50.0), DT)
        self.assertAlmostEqual(session.look_pitch, mouselook.KEY_LOOK_MAX - 0.5)

    def test_zero_motion_holds_the_turn_until_the_pointer_has_rested(self):
        session = self.make_session()
        session.tick(self.motion(0.1), DT)
        turned = session.look_yaw
        for _ in range(11):
            session.tick(Keys(), 0.1)  # 1.1 s without motion: still inside the rest delay
        self.assertEqual(session.look_yaw, turned)
        for _ in range(20):
            session.tick(Keys(), 0.1)
        self.assertGreater(session.look_yaw, 0.0)
        self.assertLess(session.look_yaw, turned)

    def test_new_motion_restarts_the_rest_delay(self):
        session = self.make_session()
        session.tick(self.motion(0.1), DT)
        for _ in range(11):
            session.tick(Keys(), 0.1)
        session.tick(self.motion(0.01), DT)
        turned = session.look_yaw
        for _ in range(11):
            session.tick(Keys(), 0.1)
        self.assertEqual(session.look_yaw, turned)

    def test_reduced_motion_recentres_by_one_snap_after_the_rest(self):
        session = self.make_session()
        session.state.v2.setdefault("settings", {})["reduced_motion"] = True
        session.tick(self.motion(0.1), DT)
        session.tick(Keys(), 0.5)
        session.tick(Keys(), 0.5)
        self.assertGreater(session.look_yaw, 0.0)  # 1.0 s: still resting
        session.tick(Keys(), 0.5)
        self.assertEqual(session.look_yaw, 0.0)  # 1.5 s: snapped, not eased
        self.assertEqual(session.look_pitch, 0.0)

    def test_a_menu_ignores_motion_and_starts_recentring_at_once(self):
        for mode in ("pause", "settings"):
            with self.subTest(mode=mode):
                session = self.make_session()
                session.tick(self.motion(0.1), DT)
                turned = session.look_yaw
                session.ui.mode = mode
                session.tick(self.motion(0.3), 0.1)
                self.assertAlmostEqual(session.look_yaw,
                                       turned * math.exp(-0.1 / mouselook.TAU_S))

    def test_losing_window_focus_stops_the_pan_and_recentres_at_once(self):
        session = self.make_session()
        session.tick(self.motion(0.1), DT)
        turned = session.look_yaw
        session.tick(Keys(mouse_delta=(0.3, 0.0), mouse_moved=True, focused=False), 0.1)
        self.assertAlmostEqual(session.look_yaw, turned * math.exp(-0.1 / mouselook.TAU_S))

    def test_motion_over_a_displayed_target_does_not_pan_but_a_stale_one_does(self):
        session = self.make_session()
        registry = session.ui.pointer
        over = Keys(mouse_pos=(150, 120), mouse_moved=True, mouse_delta=(0.3, 0.0))
        registry.begin(pointer.context(session.state, session.ui), (1280, 720))
        registry.add((100, 100, 200, 60))
        session.tick(over, DT)
        self.assertEqual(session.look_yaw, 0.0)

        # A target left by an earlier screen, or drawn at another size, must not block the look.
        registry.begin(("an earlier screen",), (1280, 720))
        registry.add((100, 100, 200, 60))
        session.tick(over, DT)
        self.assertAlmostEqual(session.look_yaw, 0.3 * TURN)
        session.look_yaw = 0.0
        registry.begin(pointer.context(session.state, session.ui), (640, 360))
        registry.add((100, 100, 200, 60))
        session.tick(over, DT)
        self.assertAlmostEqual(session.look_yaw, 0.3 * TURN)

    def test_the_off_setting_never_pans_and_recentres_an_existing_turn(self):
        session = self.make_session(level="off")
        session.tick(self.motion(0.3), DT)
        self.assertEqual(session.look_yaw, 0.0)
        session.look_yaw = 0.4
        session.tick(self.motion(0.3), 0.1)
        self.assertAlmostEqual(session.look_yaw, 0.4 * math.exp(-0.1 / mouselook.TAU_S))

    def test_a_running_story_stage_owns_the_camera(self):
        session = self.make_session()
        session.stage = SimpleNamespace(over=False)
        session._tick_look(self.motion(0.3), DT)
        self.assertEqual(session.look_yaw, 0.0)

    def test_a_running_whale_clock_owns_the_camera(self):
        session = self.make_session()
        session.whale_clock = SimpleNamespace(over=False)
        session._tick_look(self.motion(0.3), DT)
        self.assertEqual(session.look_yaw, 0.0)

    def test_a_finished_story_clock_gives_the_camera_back(self):
        session = self.make_session()
        session.stage = SimpleNamespace(over=True)
        session._tick_look(self.motion(0.3), DT)
        self.assertAlmostEqual(session.look_yaw, 0.3 * TURN)

    def test_the_settings_row_cycles_the_level_and_shows_its_label(self):
        session = self.make_session()
        session._adjust_setting(13, 1)
        self.assertEqual(session.state.v2["settings"]["mouse_look"], "quick")
        session._adjust_setting(13, 1)
        self.assertEqual(session.state.v2["settings"]["mouse_look"], "off")
        session._adjust_setting(13, -1)
        self.assertEqual(session.state.v2["settings"]["mouse_look"], "quick")
        rows = UI.__new__(UI)._settings_rows(session.state)
        self.assertEqual(rows[13], ("Mouse look", "Quick"))
        self.assertEqual(rows[-1][0], "Keyboard controls")
        self.assertEqual(len(rows), SETTINGS_ROW_COUNT)

    def test_the_saved_level_defaults_to_normal_and_rejects_unknown_values(self):
        self.assertEqual(merge_v2_defaults(None, {})["settings"]["mouse_look"], "normal")
        gentle = merge_v2_defaults(None, {"settings": {"mouse_look": "gentle"}})
        self.assertEqual(gentle["settings"]["mouse_look"], "gentle")
        wild = merge_v2_defaults(None, {"settings": {"mouse_look": "wild"}})
        self.assertEqual(wild["settings"]["mouse_look"], "normal")


class MouseLookCamera(PlaySession):
    """The camera _camera builds from the turn: the view moves, the hull and paws do not."""

    def setUp(self):
        self.renderer = Renderer(self.world, 160, 90, software=True)
        self.addCleanup(self.renderer.close)

    def test_a_turned_view_moves_the_eye_direction_but_keeps_the_hull_on_the_unturned_eye(self):
        session = self.make_session()
        session.look_yaw, session.look_pitch = 0.3, -0.1
        own = self.renderer.camera_for(session.state)
        cam = _camera(self.renderer, session)
        self.assertAlmostEqual(cam.yaw, own.yaw + 0.3)
        self.assertAlmostEqual(cam.pitch, own.pitch - 0.1)
        np.testing.assert_allclose(cam.eye, own.eye)
        # Setting `boat` would draw the whole Skipper at the helm and drop the paws.
        self.assertIsNone(cam.boat)
        frame = cam.boat_frame()
        self.assertAlmostEqual(frame.yaw, own.yaw)
        self.assertAlmostEqual(frame.pitch, own.pitch)
        np.testing.assert_allclose(frame.eye, own.eye)

    def test_a_centred_look_leaves_the_camera_as_it_was(self):
        session = self.make_session()
        cam = _camera(self.renderer, session)
        self.assertIsNone(cam.hull)
        self.assertIs(cam.boat_frame(), cam)

    def test_pitch_is_clamped_to_the_keyboard_look_bounds_in_the_rendered_view(self):
        session = self.make_session()
        session.state.look = 0.5
        session.look_pitch = 5.0
        cam = _camera(self.renderer, session)
        self.assertAlmostEqual(cam.pitch, BASE_PITCH + mouselook.KEY_LOOK_MAX)

    def test_third_person_orbits_by_the_turn_and_keeps_the_boat_on_the_unturned_eye(self):
        session = self.make_session()
        session.state.v2["settings"]["third_person"] = True
        session.look_yaw = 0.3
        state = session.state
        own = self.renderer.camera_for(state)
        cam = _camera(self.renderer, session)
        self.assertAlmostEqual(cam.yaw, state.yaw + 0.3)
        self.assertAlmostEqual(cam.x, state.x - math.sin(state.yaw + 0.3) * THIRD_PERSON_DISTANCE)
        self.assertAlmostEqual(cam.z, state.z - math.cos(state.yaw + 0.3) * THIRD_PERSON_DISTANCE)
        self.assertIsNotNone(cam.boat)
        self.assertAlmostEqual(cam.boat.yaw, own.yaw)

    def test_a_staged_story_view_is_never_turned(self):
        session = self.make_session()
        session.look_yaw = 0.3
        staged = self.renderer.camera_for(session.state)
        staged.boat = self.renderer.camera_for(session.state)
        with patch("fishing.staging.staged_camera", return_value=staged):
            self.assertIs(_camera(self.renderer, session), staged)

    def test_a_turned_view_renders_a_full_frame(self):
        session = self.make_session()
        session.look_yaw, session.look_pitch = 0.2, 0.1
        cam = _camera(self.renderer, session)
        self.assertEqual(self.renderer.render(session.state, cam).shape, (90, 160, 3))

    def test_world_to_eye_inverts_eye_to_world_and_pitch_leaves_the_level_frame_alone(self):
        own = self.renderer.camera_for(self.make_session().state)
        pts = np.array([[0.3, -0.4, 2.0]], dtype=np.float32)
        np.testing.assert_allclose(own.world_to_eye(own.eye_to_world(pts)), pts, atol=1e-5)
        pitched = own.turned(0.0, 0.2)
        np.testing.assert_allclose(pitched.world_to_eye(own.eye_to_world(pts)), pts, atol=1e-5)
        yawed = own.turned(0.2, 0.0)
        self.assertFalse(np.allclose(yawed.world_to_eye(own.eye_to_world(pts)), pts, atol=1e-3))

    @staticmethod
    def screen_of(cam, world):
        """Where a world point lands on screen for this camera, by the software paw mapping."""
        sx, sy, _ = cam.cam_to_screen(cam.world_to_eye(world))
        return np.array([sx[0], sy[0]])

    def paw_centre(self, cam, state):
        """Screen centroid of the pixels the Skipper's paws cover when drawn for this camera."""
        light = lighting_at(state.game_minutes + state.minute_acc, state)
        self.renderer.col[:] = 0.0
        self.renderer.z[:] = 1e6
        self.renderer._paws(cam, state, light)
        ys, xs = np.nonzero(self.renderer.col.any(axis=2))
        self.assertGreater(len(xs), 20, "the paws must be on screen for this check to mean anything")
        return np.array([xs.mean(), ys.mean()])

    def test_the_paws_stay_on_the_hull_when_the_view_turns(self):
        """A turned view moves the paws across the screen as the boat would, not with the view.

        Compares shifts, not absolute centres: a coverage centroid and a projected vertex mean
        are both approximate, but their error cancels between the two cameras.
        """
        session = self.make_session()
        state = session.state
        own = self.renderer.camera_for(state)
        local = paw_mesh(state, False)[0]
        world = own.eye_to_world(local.mean(axis=0, keepdims=True))
        still = self.paw_centre(own, state)
        for yaw in (0.1, -0.1):
            turned = own.turned(yaw, 0.0)
            shift = self.paw_centre(turned, state) - still
            expected = self.screen_of(turned, world) - self.screen_of(own, world)
            self.assertGreater(abs(shift[0]), 5)
            np.testing.assert_allclose(shift, expected, atol=2.5)
