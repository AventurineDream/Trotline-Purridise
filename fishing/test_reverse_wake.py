"""The boat's wake trails its actual travel, forward and in reverse, on both renderers.

The software wake is sampled directly on a grid of water points; the GL wake is rendered
broadside from a camera off the beam, so astern and ahead fall on opposite halves of the
frame. Both compare against the same scene at rest, so only the wake differs.
"""
import math
import unittest

import numpy as np

from .boat import BOATS
from .sim import State
from .software import SoftwareRenderer
from .world import World

FULL = 2.5  # m/s, a brisk jon speed in either direction
CREEP = 0.02  # m/s, drifting through zero


def _open_water(world, boat_id="jon"):
    """A deep, clear spot well away from shore, deterministic for the lake."""
    spots = [(x, z) for x in range(-150, 150, 6) for z in range(-150, 150, 6)
             if world.hull_clear(x, z, 0.0, boat_id) and world.depth(x, z) > 2]
    return spots[len(spots) // 2]


class SoftwareReverseWake(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World("briar")
        cls.renderer = SoftwareRenderer(cls.world, 32, 18)

    @classmethod
    def tearDownClass(cls):
        cls.renderer.close()

    def wake(self, speed, along, side, boat_id="jon"):
        """Wake light added at points `along` ahead / `side` to starboard of the boat's position."""
        state = State.new(self.world, seed=3)
        state.boat_id = boat_id
        state.x, state.z = _open_water(self.world, boat_id)
        state.yaw, state.speed, state.lines = 0.7, 0.0, []
        fx, fz = math.sin(state.yaw), math.cos(state.yaw)
        rx, rz = math.cos(state.yaw), -math.sin(state.yaw)
        hx = (state.x + along * fx + side * rx).astype(np.float32)
        hz = (state.z + along * fz + side * rz).astype(np.float32)
        dist = np.full_like(hx, 10.0)
        light = {"night": 0.0}
        base = np.zeros((hx.size, 3), np.float32)
        still = self.renderer._wake_rope_light(base.copy(), hx, hz, dist, state, None, light)
        state.speed = speed
        moving = self.renderer._wake_rope_light(base.copy(), hx, hz, dist, state, None, light)
        return (moving - still).sum(1)

    def grid(self):
        along, side = np.meshgrid(np.linspace(-14, 16, 241), np.linspace(-3, 3, 25))
        return along.ravel(), side.ravel()

    def test_forward_wake_trails_astern(self):
        along, side = self.grid()
        wake = self.wake(FULL, along, side)
        self.assertGreater(wake[along < BOATS["jon"].stern].sum(), 50 * max(wake[along > 0].sum(), 1e-6))

    def test_reverse_wake_is_the_forward_wake_mirrored_about_the_hull(self):
        for boat_id in ("jon", "pontoon"):
            model = BOATS[boat_id]
            along, side = self.grid()
            mirrored = model.stern + model.bow - along
            with self.subTest(boat=boat_id):
                reverse = self.wake(-FULL, along, side, boat_id)
                # The hit points are float32, so mirrored positions round slightly apart.
                np.testing.assert_allclose(reverse, self.wake(FULL, mirrored, side, boat_id), atol=1e-4)
                self.assertGreater(reverse[along > model.bow].sum(),
                                   50 * max(reverse[along < 0].sum(), 1e-6))

    def test_creeping_through_zero_barely_marks_the_water(self):
        along, side = self.grid()
        full = self.wake(FULL, along, side).sum()
        for speed in (CREEP, -CREEP):
            with self.subTest(speed=speed):
                self.assertLess(self.wake(speed, along, side).sum(), 0.02 * full)


class GLReverseWake(unittest.TestCase):
    """The water shader's wake, seen broadside: astern is the frame's left half."""

    @classmethod
    def setUpClass(cls):
        try:
            import moderngl
            cls.ctx = moderngl.create_standalone_context(require=330, backend="egl")
        except Exception as error:
            raise unittest.SkipTest("Standalone EGL unavailable: " + str(error))
        from .glrender import LakeRenderer
        world = World("briar")
        state = State.new(world, seed=3)
        state.x, state.z = _open_water(world)
        state.yaw, state.game_minutes = 0.3, 12 * 60
        rx, rz = math.cos(state.yaw), -math.sin(state.yaw)
        cls.frames = {}
        with cls.ctx:
            renderer = LakeRenderer(world, 320, 180, context=cls.ctx)
            try:
                # 9 m to starboard looking to port: the bow points to screen right.
                cam = renderer.camera_for(state, yaw=state.yaw - math.pi / 2, pitch=-0.5,
                                          x=state.x + rx * 9, z=state.z + rz * 9)
                for speed in (0.0, FULL, -FULL, CREEP, -CREEP):
                    state.speed = speed
                    cls.frames[speed] = renderer.render(state, cam).astype(np.float64)
                # The shader mirrors about each hull's own ends: a stale or unset uniform
                # would mirror every boat about the jon's middle, or about the eye.
                cls.ends = {}
                for boat_id in ("jon", "houseboat"):
                    state.boat_id, state.speed = boat_id, -FULL
                    renderer.render(state, cam)
                    cls.ends[boat_id] = tuple(renderer.water_p["boat_ends"].value)
            finally:
                renderer.close()

    @classmethod
    def tearDownClass(cls):
        cls.ctx.release()

    def halves(self, speed):
        """Summed change from the resting frame on the (astern, ahead) halves."""
        change = np.abs(self.frames[speed] - self.frames[0.0]).sum(2)
        half = change.shape[1] // 2
        return change[:, :half].sum(), change[:, half:].sum()

    def test_forward_wake_is_astern(self):
        astern, ahead = self.halves(FULL)
        self.assertGreater(astern, 5 * ahead)

    def test_reverse_wake_is_ahead(self):
        astern, ahead = self.halves(-FULL)
        self.assertGreater(ahead, 5 * astern)

    def test_each_hull_mirrors_about_its_own_ends(self):
        for boat_id, ends in self.ends.items():
            with self.subTest(boat=boat_id):
                np.testing.assert_allclose(ends, (BOATS[boat_id].stern, BOATS[boat_id].bow), atol=1e-6)

    def test_creeping_through_zero_barely_marks_the_water(self):
        # A flipped full-strength wake at creep speed would score near 1; today's fade
        # measures about 0.03, so 0.1 leaves room for retuning it.
        full = sum(self.halves(FULL))
        for speed in (CREEP, -CREEP):
            with self.subTest(speed=speed):
                self.assertLess(sum(self.halves(speed)), 0.1 * full)


if __name__ == "__main__":
    unittest.main()
