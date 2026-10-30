"""V1-35: the story's staging, its clock in the session, and what it may and may not change."""
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from . import staging
from .content import load_content
from .game import Keys, Session, _camera
from .quests import scene_state
from .render import Renderer
from .savepaths import load_game_save
from .sim import State
from .weather import lighting_at
from .world import World


class Timeline(unittest.TestCase):
    def test_every_stage_starts_at_zero_and_runs_forward(self):
        for stage_id, stage in staging.STAGES.items():
            times = [key.t for key in stage.keys]
            self.assertEqual(times[0], 0.0, stage_id)
            self.assertEqual(times, sorted(set(times)), stage_id)
        for scene, stage_id in staging.CONTINUES.items():
            self.assertIn(stage_id, staging.STAGES, scene)
        content = load_content()
        for scene_id in list(staging.STAGES) + list(staging.CONTINUES):
            self.assertTrue(scene_id == "credits" or scene_id in content.scenes, scene_id)

    def test_the_prologue_fades_in_and_hands_the_view_back(self):
        clock = staging.Clock("pro_01")
        start = staging.sample(clock)
        self.assertEqual((start["fade"], start["bars"]), (1.0, 1.0))
        clock.t = 2.4
        self.assertEqual(staging.sample(clock)["fade"], 0.0)
        clock.t = staging.STAGES["pro_01"].duration
        self.assertIsNone(staging.sample(clock))  # over: the Skipper's own view and HUD return
        self.assertTrue(clock.over)

    def test_the_fog_lifts_off_the_marker(self):
        clock = staging.Clock("story_c4_clear")
        self.assertEqual(staging.light_overrides(clock), {"mist": 1.0})
        clock.t = 5.5
        self.assertEqual(staging.light_overrides(clock), {"mist": 0.0})
        world = World("crater")
        state = State.new(world, seed=4)
        state.game_minutes = 4 * 1440 + 360  # a clear noon
        clear = lighting_at(state.game_minutes, state)
        state.stage_light = {"mist": 1.0}
        foggy = lighting_at(state.game_minutes, state)
        self.assertEqual(foggy["mist"], 1.0)
        self.assertGreater(foggy["overcast"], clear["overcast"])
        # The view faces the survey marker from wherever the boat waits.
        own = (state.x, 1.22, state.z, state.yaw, 0.0)
        pose = staging.camera_pose(staging.Clock("story_c4_clear"), state, own)
        self.assertAlmostEqual(pose[3], math.atan2(60.0 - state.x, 252.0 - state.z), places=5)

    def test_the_credits_hold_their_dawn_and_rise_into_place(self):
        clock = staging.Clock("credits", t=100.0)
        self.assertFalse(clock.over)  # held until the credits are dismissed
        self.assertAlmostEqual(staging.light_overrides(clock)["hour"], 6.6)
        self.assertEqual(staging.credits_rise(staging.Clock("credits", t=2.0)), 2.0 * staging.CREDITS_SPEED)
        self.assertEqual(staging.credits_rise(clock, reduced=True), math.inf)  # at rest at once

    def test_reduced_motion_never_moves_the_camera(self):
        state = State.new(World("briar"), seed=1)
        own = (state.x, 1.22, state.z, state.yaw, -0.05)
        for stage_id, stage in staging.STAGES.items():
            poses = {staging.camera_pose(staging.Clock(stage_id, t=t), state, own, reduced=True)
                     for t in np.linspace(0.0, stage.duration * 0.99, 9)}
            self.assertEqual(len(poses), 1, stage_id)  # one framing throughout
        # The fade is not motion, and stays.
        self.assertEqual(staging.sample(staging.Clock("pro_01"), reduced=True)["fade"], 1.0)


class InTheSession(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "save.json"
        self.content = load_content()
        self.world = World("briar")
        with patch("fishing.game.load_content", return_value=self.content):
            self.session = Session(self.world, self.path, State.new(self.world, seed=35), False)
        self.renderer = Renderer(self.world, 160, 90, software=True)
        self.addCleanup(self.renderer.close)

    def new_morning(self):
        self.session.ui.mode, self.session.ui.new_mode_i = "new_mode", 0
        self.session.tick(Keys(pressed={"return"}), 0.05)

    def test_a_new_game_stages_the_arrival_then_returns_the_view(self):
        self.new_morning()
        stage = self.session.stage
        self.assertEqual((stage.stage_id, stage.repeat), ("pro_01", False))
        cam = _camera(self.renderer, self.session)
        own = self.renderer.camera_for(self.session.state)
        self.assertEqual((cam.boat.x, cam.boat.z, cam.boat.yaw), (own.x, own.z, own.yaw))  # the boat stays put
        self.assertLess(cam.pitch, own.pitch)  # looking down to the water and the tiller
        self.assertEqual(self.session.ui.stage_fx["fade"], 1.0)
        for _ in range(100):
            self.session.tick(Keys(), 0.05)
        self.assertTrue(self.session.stage.over)  # the staging has ended (and won't restart); the scene waits
        self.assertIsNone(self.session.ui.stage_fx)
        self.assertEqual(self.session.conversation.node_id, "scene:pro_01")
        self.assertEqual(_camera(self.renderer, self.session).pitch, own.pitch)
        self.assertIsNone(self.session.state.stage_light)

    def test_a_replayed_scene_can_skip_its_staging_with_esc_but_not_its_bubbles(self):
        self.new_morning()
        self.session.tick(Keys(quit=True), 0.05)
        world, state, _ = load_game_save(self.path, State, World)
        with patch("fishing.game.load_content", return_value=self.content):
            session = Session(world, self.path, state, True)
        session.ui.mode = "play"
        session.tick(Keys(pressed={"x"}), 0.05)
        self.assertEqual(session.conversation.node_id, "scene:pro_01")
        self.assertTrue(session.stage.repeat)
        self.assertTrue(session.ui.stage_skip)
        session.tick(Keys(pressed={"esc"}), 0.05)
        self.assertTrue(session.stage.over)  # skipped to its end
        self.assertEqual(session.conversation.node_id, "scene:pro_01")  # the bubble waits to be read
        self.assertEqual(scene_state(session.state, "pro_01"), "pending")
        session.tick(Keys(pressed={"esc"}), 0.05)
        self.assertEqual(session.ui.mode, "dialogue")  # and Esc still can't leave the scene

    def test_a_first_showing_cannot_be_skipped(self):
        self.new_morning()
        self.assertFalse(self.session.ui.stage_skip)
        self.session.tick(Keys(pressed={"esc"}), 0.05)
        self.assertEqual(self.session.stage.stage_id, "pro_01")
        self.assertGreater(self.session.stage.t, 0.0)

    def test_a_scene_read_early_lets_its_staging_play_out_quickly(self):
        world = World("crater")
        with patch("fishing.game.load_content", return_value=self.content):
            session = Session(world, self.path, State.new(world, seed=4), False)
        session.ui.mode = "play"
        from .story import scene_conversation
        session._show_conversation(scene_conversation(session.state, self.content, "story_c4_clear"))
        session.tick(Keys(), 0.05)
        self.assertEqual(session.state.stage_light, {"mist": 1.0})
        session.tick(Keys(pressed={"c"}), 0.05)  # read at once: the scene closes
        self.assertEqual(session.ui.mode, "play")
        session.tick(Keys(), 0.25)
        self.assertLess(session.state.stage_light["mist"], 1.0)  # still thinning, not cut
        for _ in range(10):
            session.tick(Keys(), 0.25)
        self.assertIsNone(session.stage)  # 7 s of staging, played out in under 2
        self.assertIsNone(session.state.stage_light)

    def test_help_pauses_the_staging(self):
        self.new_morning()
        self.session.tick(Keys(), 0.5)
        t = self.session.stage.t
        self.session.tick(Keys(pressed={"h"}), 0.05)
        self.assertEqual(self.session.ui.mode, "help")
        for _ in range(10):
            self.session.tick(Keys(), 0.5)
        self.assertEqual(self.session.stage.t, t)

    def test_an_unstaged_frame_draws_exactly_as_before(self):
        # Outside a staged scene the camera is the Skipper's own, holding no boat, so the
        # renderers take their old path and the frame is the same picture.
        state = self.session.state
        state.game_minutes = 300
        self.session.ui.mode = "play"
        cam = _camera(self.renderer, self.session)
        self.assertIsNone(cam.boat)
        self.assertTrue(np.array_equal(self.renderer.render(state), self.renderer.render(state, cam)))

    def test_a_pulled_back_view_still_sees_the_boat_where_it_floats(self):
        state = self.session.state
        state.game_minutes = 300
        clock = staging.Clock("credits", t=1.6)
        cam = staging.staged_camera(self.renderer, state, clock)
        self.assertGreater(math.hypot(cam.x - state.x, cam.z - state.z), 4.0)
        bow = cam.project_world(*cam.boat.eye_to_world(np.array([0.0, -0.8, 2.0], np.float32)))
        self.assertIsNotNone(bow)  # the bow, ahead of the Skipper, is in front of the staged camera
        self.assertTrue(0 <= bow[0] <= cam.w and 0 <= bow[1] <= cam.h, bow)


if __name__ == "__main__":
    unittest.main()
