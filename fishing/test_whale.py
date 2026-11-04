"""V1-37 part 2: the Star-Whale comes back after the finale (02 §7.2)."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from . import calendar, staging, whale
from .content import load_content
from .game import Keys, Session, _camera
from .lakes import place
from .render import Renderer
from .sim import State
from .world import World


def _settled(world, *, finale=True, seed=21):
    state = State.new(world, seed=seed)
    row = place("nebula:calm_reflection")[1]
    state.x, state.z, state.anchored, state.speed = row["x"], row["z"], True, 0.0
    state.v2["story"]["completed_chapters"] = [1, 2, 3, 4, 5]
    if finale:
        state.set_scene_status("story_c5_whale", "done")
    start, _end = calendar.next_legendary_window(calendar.forecast_seed(state), "star_whale", 1440.0)
    state.game_minutes = int(start) + 10
    return state


def _records(state):
    return state.v2["legendaries"].get("star_whale", {}).get("records", [])


class Stage(unittest.TestCase):
    def test_it_rises_as_the_finale_did_holds_and_sinks(self):
        stage = staging.PLAY_STAGES["whale_return"]
        self.assertNotIn("whale_return", staging.STAGES)  # not a scene's staging
        rise = [staging.sample(staging.Clock("whale_return", t=t))["whale"] for t in (0.0, 1.5, 6.0, whale.RISEN_S)]
        self.assertEqual(rise, sorted(rise))
        self.assertEqual(rise[-1], 1.0)
        self.assertEqual(staging.sample(staging.Clock("whale_return", t=12.5))["whale"], 1.0)
        self.assertLess(staging.sample(staging.Clock("whale_return", t=16.5))["whale"], 0.6)
        self.assertTrue(staging.Clock("whale_return", t=stage.duration).over)
        # Reduced Motion: risen and still throughout, and the view holds.
        self.assertEqual(staging.sample(staging.Clock("whale_return", t=0.5), reduced=True)["whale"], 1.0)


class InPlay(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / "save.json"
        self.content = load_content()
        self.world = World("nebula")

    def session(self, state):
        with patch("fishing.game.load_content", return_value=self.content):
            session = Session(self.world, self.path, state, True)
        session.ui.mode = "play"
        return session

    def run_for(self, session, seconds, dt=0.1, keys=None):
        for _ in range(int(round(seconds / dt))):
            session.tick(keys or Keys(), dt)

    def test_it_comes_back_to_a_still_skipper_and_is_recorded_once_a_week(self):
        session = self.session(_settled(self.world))
        self.assertTrue(whale.can_return(session.state, self.world))
        self.run_for(session, whale.WAIT_S - 0.5)
        self.assertIsNone(session.whale_clock)
        self.run_for(session, 1.0)
        self.assertIsNotNone(session.whale_clock)
        self.assertTrue(session.ui.whale_return)
        self.run_for(session, whale.RISEN_S + 0.2)
        self.assertGreater(session.state.stage_light["whale"], 0.9)
        self.assertEqual(len(_records(session.state)), 1)
        self.assertTrue(_records(session.state)[0]["witnessed"])
        self.run_for(session, staging.PLAY_STAGES["whale_return"].duration)
        self.assertIsNone(session.whale_clock)
        self.assertIsNone(session.state.stage_light)
        self.run_for(session, whale.WAIT_S + 2)  # seen this week: it doesn't come again
        self.assertIsNone(session.whale_clock)
        self.assertEqual(len(_records(session.state)), 1)

    def test_not_before_the_finale_and_not_unless_still(self):
        self.assertFalse(whale.can_return(_settled(self.world, finale=False), self.world))
        state = _settled(self.world)
        state.anchored = False
        self.assertFalse(whale.can_return(state, self.world))
        state = _settled(self.world)
        state.game_minutes += 12 * 60  # half a day on: outside its 20:00–04:00 window
        self.assertFalse(whale.can_return(state, self.world))
        # Moving resets the wait.
        session = self.session(_settled(self.world))
        self.run_for(session, whale.WAIT_S - 2)
        session.state.anchored = False
        self.run_for(session, 0.2)
        session.state.anchored = True
        self.run_for(session, 3.0)
        self.assertIsNone(session.whale_clock)

    def test_leaving_before_it_has_risen_lets_it_sink_unrecorded(self):
        session = self.session(_settled(self.world))
        self.run_for(session, whale.WAIT_S + 0.2)
        self.assertIsNotNone(session.whale_clock)
        session.state.anchored = False
        self.run_for(session, staging.PLAY_STAGES["whale_return"].duration / staging.RELEASE + 0.5)
        self.assertIsNone(session.whale_clock)
        self.assertEqual(_records(session.state), [])

    def test_esc_skips_it_and_it_is_still_recorded(self):
        session = self.session(_settled(self.world))
        self.run_for(session, whale.WAIT_S + 0.2)
        session.tick(Keys(pressed={"esc"}), 0.05)
        self.assertEqual(session.ui.mode, "play")  # not the pause menu
        self.assertIsNone(session.whale_clock)
        self.assertEqual(len(_records(session.state)), 1)

    def test_the_view_lifts_with_it(self):
        session = self.session(_settled(self.world))
        renderer = Renderer(self.world, 160, 90, software=True)
        self.addCleanup(renderer.close)
        own = renderer.camera_for(session.state)
        self.run_for(session, whale.WAIT_S + 6.2)
        self.assertGreater(_camera(renderer, session).pitch, own.pitch + 0.05)


if __name__ == "__main__":
    unittest.main()
