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


class Finale(unittest.TestCase):
    """Settle In's cues on the water, the Star-Whale and the drawing (02 §13.5, 05 §2.5)."""

    def setUp(self):
        from .lakes import place
        self.world = World("nebula")
        self.state = State.new(self.world, seed=35)
        row = place("nebula:calm_reflection")[1]
        self.centre = (row["x"], row["z"])
        self.state.x, self.state.z = self.centre
        self.state.narrative.quest("story_c5_s2").status = "active"

    def settle(self, seconds):
        self.state.v2["story"]["settle"] = {"seconds": seconds, "cues": sum(seconds >= c for c in (15, 30, 45)),
                                            "together": False}
        from .finale import settle_look
        return settle_look(self.state)

    def test_each_cue_shows_on_the_water_when_it_is_reached(self):
        self.assertEqual(self.settle(5.0), {"still": 0.0, "lilies": 0.0, "glow": 0.0})
        look = self.settle(15.0)
        self.assertEqual(look["still"], 1.0)  # the stars stop rippling
        self.assertEqual(look["glow"], 0.0)
        look = self.settle(30.0)
        self.assertEqual((look["lilies"], look["glow"]), (1.0, 0.0))  # the lilies have drifted in
        self.assertEqual(self.settle(45.0)["glow"], 1.0)  # the deep glow has risen

    def test_the_cues_belong_to_the_reflection_and_the_step(self):
        self.state.x += 300.0  # sailed off
        self.assertEqual(self.settle(45.0), {"still": 0.0, "lilies": 0.0, "glow": 0.0})
        self.state.x, self.state.z = self.centre
        self.state.narrative.quests["story_c5_s2"].status = "ready"  # the whale's scenes
        self.assertEqual(self.settle(0.0), {"still": 1.0, "lilies": 1.0, "glow": 1.0})
        self.state.narrative.quests["story_c5_s2"].status = "completed"  # drawn: the Lagoon is itself again
        self.assertEqual(self.settle(45.0)["still"], 0.0)

    def test_the_first_cue_stills_the_water_in_both_renderers(self):
        from .caldera import reflection_strength
        light = lighting_at(self.state.game_minutes, self.state)
        self.settle(5.0)
        self.assertEqual(reflection_strength(self.state, light), 0.0)
        self.settle(20.0)
        self.assertEqual(reflection_strength(self.state, light), 1.0)
        crater = State.new(World("crater"), seed=4)
        self.assertEqual(reflection_strength(crater, light), float(np.clip(
            light["night"] * (1 - light["cloud_shade"]) * (1 - light["rain"]) * (1 - light["mist"]), 0, 1)))

    def test_the_whole_finale_stays_inside_the_ambient_face_budget(self):
        from . import ambient
        from .finale import faces
        self.settle(45.0)
        self.state.narrative.quests["story_c5_s2"].status = "ready"
        self.state.stage_light = {"whale": 1.0}  # every cue and the whale at once
        finale = faces(self.state, self.world)
        self.assertLessEqual(len(finale), 89)
        motes = 2 * 25  # the most the 5x5 mote neighbourhood can hold
        self.assertLessEqual(len(finale) + motes, ambient.MAX_FACES)
        self.assertLessEqual(len(ambient.faces(self.state, self.world)), ambient.MAX_FACES)

    def test_lilies_glow_and_whale_are_drawn_on_the_lagoon_only(self):
        from .finale import faces
        self.settle(5.0)
        self.assertEqual(faces(self.state, self.world), [])
        self.settle(30.0)
        lilies = faces(self.state, self.world)
        self.assertEqual(len(lilies), 8 * (2 + 1))  # eight pads, each with a star at its heart
        self.settle(45.0)
        with_glow = faces(self.state, self.world)
        self.assertGreater(len(with_glow), len(lilies))
        self.state.stage_light = {"whale": 1.0}
        whale = faces(self.state, self.world)
        self.assertGreater(len(whale), len(with_glow) + 50)
        self.assertGreater(max(float(f.pts[:, 1].max()) for f in whale), 2.0)  # risen over the water
        self.assertTrue(all(f.emissive for f in whale))
        self.assertEqual(faces(State.new(World("briar"), seed=1), World("briar")), [])

    def test_the_whale_rises_holds_and_the_drawing_is_made_stroke_by_stroke(self):
        from .finale import SKETCH, sketch_strokes
        rise = [staging.sample(staging.Clock("story_c5_whale", t=t))["whale"] for t in (0.0, 2.0, 6.5, 9.0, 60.0)]
        self.assertEqual(rise, sorted(rise))
        self.assertEqual((rise[0], rise[-1]), (0.0, 1.0))  # held, risen, until it is drawn
        drawn = staging.Clock("story_c5_drawn", t=3.0)
        self.assertEqual(staging.sample(drawn)["sketch"], 1.0)
        self.assertEqual(sketch_strokes(0.0), [])
        self.assertEqual(sketch_strokes(1.0), [list(s) for s in SKETCH])
        counts = [sum(len(s) for s in sketch_strokes(k / 10)) for k in range(11)]
        self.assertEqual(counts, sorted(counts))  # the pencil only adds
        # Reduced Motion: the whale is simply there, and the drawing complete.
        self.assertEqual(staging.sample(staging.Clock("story_c5_whale"), reduced=True)["whale"], 1.0)
        self.assertEqual(staging.sample(staging.Clock("story_c5_drawn"), reduced=True)["sketch"], 1.0)

    def test_the_whale_scene_stages_in_play_and_a_trip_home_leaves_it_behind(self):
        from .test_story import StoryPlay

        class Play(StoryPlay):
            def runTest(inner):
                inner.play_chapter_one(); inner.play_chapter_two(); inner.play_chapter_three(); inner.play_chapter_four()
                inner.travel("nebula"); inner.scene(); inner.talk("astra_9", "turn_in")
                inner.settle_by_the_reflection(); inner.press("c"); inner.wait(15); inner.press("1"); inner.wait(30)
                inner.press("x")
                session = inner.session
                inner.assertEqual(session.stage.stage_id, "story_c5_whale")
                session.tick(Keys(), 3.0)
                inner.assertGreater(session.state.stage_light["whale"], 0.1)
                inner.press("c"); inner.press("1")  # read the whale, and draw it
                inner.assertEqual(session.stage.stage_id, "story_c5_drawn")
                inner.assertIn("sketch", session.ui.stage_fx)
                inner.press("1")  # go home to Briar Landing
                inner.assertEqual(session.world.id, "briar")
                inner.assertNotEqual(getattr(session.stage, "stage_id", None), "story_c5_drawn")
        result = unittest.TestResult()
        Play().run(result)
        self.assertEqual((result.errors, result.failures), ([], []))

    def test_staying_before_the_drawing_is_done_keeps_the_page_until_it_is(self):
        from .platform import Text
        from .test_story import StoryPlay
        from .ui import UI

        class Play(StoryPlay):
            def runTest(inner):
                inner.play_chapter_one(); inner.play_chapter_two(); inner.play_chapter_three(); inner.play_chapter_four()
                inner.travel("nebula"); inner.scene(); inner.talk("astra_9", "turn_in")
                inner.settle_by_the_reflection(); inner.press("c"); inner.wait(15); inner.press("1"); inner.wait(30)
                inner.press("x"); inner.press("c"); inner.press("1")  # read the whale, and draw it
                session = inner.session
                inner.press("2")  # "Stay a while", read at once
                inner.assertEqual(session.ui.mode, "play")
                text = Text()
                inner.addCleanup(text.close)
                ui, drawn = UI(text, session.world), []
                ui._sketch = lambda frame, progress: drawn.append(progress)
                ui.draw(np.zeros((180, 320, 3), np.uint8), session.state, session.ui)
                inner.assertTrue(drawn and drawn[-1] < 1.0, drawn)  # still being drawn, in play
                for _ in range(4):
                    session.tick(Keys(), 0.25)
                ui.draw(np.zeros((180, 320, 3), np.uint8), session.state, session.ui)
                inner.assertEqual(drawn[-1], 1.0)  # and finished
        result = unittest.TestResult()
        Play().run(result)
        self.assertEqual((result.errors, result.failures), ([], []))


class Vignettes(unittest.TestCase):
    """The story's small moments beside the dialogue: the book, the collar, the knot."""

    @classmethod
    def setUpClass(cls):
        cls.content = load_content()
        cls.world = World("briar")

    def node(self, chat):
        return chat.node(self.content)

    def test_each_moment_has_its_card(self):
        from .dialogue import Conversation
        from .story import scene_conversation
        from .vignettes import vignette_for
        state = State.new(self.world, seed=2)
        for scene in ("pro_05", "pro_05b", "pro_06"):
            chat = scene_conversation(state, self.content, scene)
            self.assertEqual(vignette_for(self.node(chat), chat, state), ("book", None), scene)
        knit = Conversation("grandmother_whiskers", "story_c1_s3", "story_c1_s3:dialogue:done")
        self.assertEqual(vignette_for(self.node(knit), knit, state), ("knit", None))
        slip = Conversation("captain_huckleberry", "story_c3_s3", "story_c3_s3:dialogue:ready:3")
        self.assertEqual(vignette_for(self.node(slip), slip, state), ("slip", None))
        knot = scene_conversation(state, self.content, "story_c4_knot")
        for index, expected in enumerate(("square", "bow", "sailors_hitch")):
            knot.selected = index
            self.assertEqual(vignette_for(self.node(knot), knot, state), ("knot", expected))
        other = Conversation("captain_huckleberry", "story_c3_s3", "story_c3_s3:dialogue:ready")
        self.assertIsNone(vignette_for(self.node(other), other, state))

    def test_the_collar_is_knitted_on_and_reduced_motion_shows_it_done(self):
        from .vignettes import bot_card, bot_image
        state = State.new(self.world, seed=2)
        bare, collared = bot_card("tin", "none", None, 64), bot_card("tin", "received", None, 64)
        self.assertFalse(np.array_equal(bare, collared))
        self.assertTrue(np.array_equal(bot_image("knit", None, 0.0, state, 64, reduced=False), bare))
        self.assertTrue(np.array_equal(bot_image("knit", None, 99.0, state, 64, reduced=False), collared))
        self.assertTrue(np.array_equal(bot_image("knit", None, 0.0, state, 64, reduced=True), collared))
        changed = [int((bot_image("knit", None, t, state, 64, reduced=False) != bare).any(axis=2).sum())
                   for t in (0.0, 0.6, 1.2, 1.8, 2.5)]
        self.assertEqual(changed, sorted(changed))  # stitch by stitch, never unravelling
        knots = {k: bot_card("tin", "retied", k, 64) for k in ("square", "bow", "sailors_hitch")}
        self.assertFalse(np.array_equal(knots["square"], knots["bow"]))
        self.assertFalse(np.array_equal(knots["bow"], knots["sailors_hitch"]))

    def test_the_knot_card_follows_the_highlight_in_play(self):
        from .test_story import StoryPlay

        class Play(StoryPlay):
            def runTest(inner):
                inner.play_chapter_one(); inner.play_chapter_two(); inner.play_chapter_three()
                inner.travel("crater")
                inner.state.narrative.quest("story_c4_s1")
                inner.state.narrative.quests["story_c4_s3"].status = "ready"
                inner.press("x")
                session = inner.session
                inner.assertEqual(session.conversation.node_id, "scene:story_c4_knot")
                inner.assertEqual((session.ui.vignette["kind"], session.ui.vignette["detail"]), ("knot", "square"))
                session.tick(Keys(), 0.5)
                inner.press("down")
                inner.assertEqual(session.ui.vignette["detail"], "bow")
                inner.assertGreater(session.ui.vignette["t"], 0.0)  # the same card, not restarted
                inner.press("2")
                inner.assertEqual(session.conversation.node_id, "scene:story_c4_tied")
                inner.assertEqual(session.ui.vignette["detail"], "bow")  # the one chosen
                inner.press("c")
                inner.assertIsNone(session.ui.vignette)
        result = unittest.TestResult()
        Play().run(result)
        self.assertEqual((result.errors, result.failures), ([], []))

    def test_the_first_trip_onto_the_sky_looks_up(self):
        clock = staging.Clock("story_c5_arrive", t=3.2)
        state = State.new(World("nebula"), seed=1)
        own = (state.x, 1.22, state.z, state.yaw, -0.05)
        self.assertGreater(staging.camera_pose(clock, state, own)[4], 0.3)
        clock.t = staging.STAGES["story_c5_arrive"].duration
        self.assertIsNone(staging.camera_pose(clock, state, own))  # handed back
