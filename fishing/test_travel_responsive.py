"""A lake change keeps the window answering while the new lake is built.

The windowed loop defers a trip: the World builds on a worker thread behind the travel
card while the GL thread keeps servicing window events, and only then is the trip
committed. These tests drive `_enter_lake` with a fake platform. Each worker blocks
until the platform has been polled a set number of times, so the checks depend on
events rather than timing. Covered: events during the build, an all-or-nothing commit,
a quit mid-load, a failed build, the worker's World matching a synchronous one, and
the GL renderer pumping between its build stages.
"""
import io
import random
import tempfile
import threading
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

import numpy as np

from . import game
from .game import Session, _enter_lake
from .lakes import LoadingQuips
from .platform import Text
from .render import Renderer
from .sim import State, saved_lake
from .ui import UI
from .world import World


class FakePlatform:
    """Records polls and presents; reports a quit from poll number `quit_at` on."""

    context = None

    def __init__(self, session, quit_at=None):
        self.session, self.quit_at = session, quit_at
        self.polls, self.presented, self.seen = 0, 0, []
        self.polled = threading.Condition()
        self.now = 0

    def poll(self, _dt):
        with self.polled:
            self.polls += 1
            # What the game showed the world while the lake was still loading.
            self.seen.append((self.session.world.id, self.session.state.lake_id, self.session.ui.mode))
            self.polled.notify_all()
        return type("Input", (), {"quit": self.quit_at is not None and self.polls >= self.quit_at})()

    def wait_for_polls(self, count):
        with self.polled:
            self.polled.wait_for(lambda: self.polls >= count, timeout=30)

    def present(self, _frame):
        self.presented += 1

    def ticks(self):
        self.now += 100
        return self.now

    def delay(self, _ms):
        pass

    def make_current(self):
        pass


class DeferredTravel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = Text()

    @classmethod
    def tearDownClass(cls):
        cls.text.close()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="travel-")
        self.addCleanup(self.temp.cleanup)
        self.save_path = Path(self.temp.name) / "save.json"
        world = World("flathead")
        state = State.new(world, seed=164)
        state.v2["story"]["chapter"] = 5  # every lake open
        self.session = Session(world, self.save_path, state, False)
        self.session.defer_travel = True
        self.session.ui.mode = "shop"
        self.renderer = Renderer(world, 160, 90, software=True)
        self.ui = UI(self.text, world)

    def enter(self, platform):
        loading = np.empty((90, 160, 3), np.uint8)
        return _enter_lake(platform, self.session, self.renderer, self.ui, self.text, loading,
                           True, True, None, quips=LoadingQuips(random.Random(1)))

    def slow_world(self, platform, polls, fail=False):
        """A World factory that finishes only after `polls` polls (or raises)."""
        real = World

        def build(lake_id):
            platform.wait_for_polls(polls)
            if fail:
                raise RuntimeError("terrain exploded")
            return real(lake_id)
        return build

    def test_window_events_are_serviced_while_the_lake_builds(self):
        self.assertIsNone(self.session.change_lake("crater"))
        self.assertEqual(self.session.pending_lake, "crater")
        self.assertEqual(self.session.world.id, "flathead")  # nothing moves until it is built
        platform = FakePlatform(self.session)
        with patch("fishing.game.World", self.slow_world(platform, 3)):
            renderer, ui = self.enter(platform)
        self.addCleanup(renderer.close)
        self.addCleanup(ui.close)
        self.assertGreaterEqual(platform.polls, 3)
        self.assertGreaterEqual(platform.presented, 3)  # the travel card stays up meanwhile
        # While loading, the game still showed the old lake and the shop, never a half trip.
        self.assertTrue(all(seen == ("flathead", "flathead", "shop") for seen in platform.seen[:3]))
        self.assertEqual(self.session.world.id, "crater")
        self.assertIs(renderer.world, self.session.world)
        self.assertIsNone(self.session.pending_lake)
        self.assertEqual(self.session.ui.mode, "play")
        self.assertEqual(saved_lake(self.save_path), "crater")

    def test_quitting_mid_load_leaves_the_old_lake_and_save_alone(self):
        self.session.change_lake("crater")
        platform = FakePlatform(self.session, quit_at=2)
        release = threading.Event()

        def build(lake_id):
            release.wait(30)
            return World(lake_id)
        with patch("fishing.game.World", build):
            renderer, ui = self.enter(platform)
        release.set()
        self.assertTrue(self.session.quit)
        self.assertIs(renderer, self.renderer)
        self.assertIs(ui, self.ui)
        self.assertEqual((self.session.world.id, self.session.state.lake_id), ("flathead", "flathead"))
        self.assertIsNone(self.session.pending_lake)
        self.assertEqual(self.session.ui.mode, "shop")
        self.assertFalse(self.save_path.exists())

    def test_a_failed_build_keeps_the_player_at_the_old_landing(self):
        self.session.change_lake("crater")
        platform = FakePlatform(self.session)
        stderr = io.StringIO()
        with patch("fishing.game.World", self.slow_world(platform, 1, fail=True)), redirect_stderr(stderr):
            renderer, ui = self.enter(platform)
        self.assertIs(renderer, self.renderer)
        self.assertEqual(self.session.world.id, "flathead")
        self.assertIsNone(self.session.pending_lake)
        self.assertFalse(self.session.quit)
        self.assertIn("terrain exploded", stderr.getvalue())
        toasts = [text for text, _ in self.session.state.toasts]
        self.assertIn("Crater Caldera would not open. You're still at Flathead Alpine Lake.", toasts)
        self.assertFalse(self.save_path.exists())


class WorkerWorld(unittest.TestCase):
    def test_a_lake_built_on_the_worker_matches_a_synchronous_build(self):
        load = game._WorldLoad("briar")  # the heaviest authored lake
        self.assertTrue(load.done.wait(120))
        self.assertIsNone(load.error)
        built, direct = load.world, World("briar")
        self.assertEqual(built.bounds, direct.bounds)
        arrays = [key for key, value in vars(direct).items() if isinstance(value, np.ndarray)]
        self.assertTrue(arrays)
        self.assertEqual(arrays, [key for key, value in vars(built).items() if isinstance(value, np.ndarray)])
        for key in arrays:
            np.testing.assert_array_equal(getattr(built, key), getattr(direct, key), err_msg=key)
        self.assertEqual(len(built.faces), len(direct.faces))
        for ours, theirs in zip(built.faces, direct.faces):
            np.testing.assert_array_equal(ours.pts, theirs.pts)
            np.testing.assert_array_equal(ours.color, theirs.color)


class GLBuildPumps(unittest.TestCase):
    def test_the_gl_renderer_pumps_between_its_build_stages(self):
        try:
            import moderngl
            ctx = moderngl.create_standalone_context(require=330, backend="egl")
        except Exception as exc:
            self.skipTest(f"Standalone EGL unavailable: {exc}")
        from .glrender import FX_LAYERS, LakeRenderer
        calls = []
        try:
            with ctx:
                renderer = LakeRenderer(World("briar"), 320, 180, context=ctx,
                                        progress=lambda: calls.append(threading.get_ident()))
                renderer.close()
        finally:
            ctx.release()
        # Shaders, terrain, flora bakes, props, then each effect layer.
        self.assertEqual(len(calls), 4 + len(FX_LAYERS))
        self.assertEqual(set(calls), {threading.get_ident()})  # GL work stays on this thread


if __name__ == "__main__":
    unittest.main()
