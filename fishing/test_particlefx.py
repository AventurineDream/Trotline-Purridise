"""Consumer-visible invariants of the GPU particle layer (`fishing.particlefx`).

The layer draws fireflies, mist, rain, snow, motes and the Nebula's star dust
over every lake frame, so it must not break what the rest of the game relies
on: frames are reproducible, Reduced Motion holds the air still, the scene
depth (pinned by `verify.graphics_checks`) never changes, no GL object is
created per frame, and every tier's seed buffers fit its particle budget.

Needs headless OpenGL; the tests skip where only the CPU renderer exists.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

import numpy as np

from . import calendar
from .detail import TIERS
from .particlefx import FIREFLY, MOTES, RAIN, ParticleFx
from .sim import State
from .weather import lighting_at
from .world import World

# Small frames keep the module quick; the particle path is resolution-free.
WIDTH, HEIGHT = 320, 180
# Game minutes on day 2 for a dusk (fireflies, insects, wisps) and a rain frame.
DUSK = 1440.0 + 13.5 * 60.0
RAIN_AFTERNOON = 1440.0 + 10.0 * 60.0


def _renderer(world):
    """A GL lake renderer, or None where headless GL is unavailable."""
    try:
        from .glrender import LakeRenderer
        return LakeRenderer(world, WIDTH, HEIGHT)
    except (ImportError, RuntimeError):
        return None


class ParticleFxChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World("briar")
        cls.renderer = _renderer(cls.world)
        if cls.renderer is None:
            raise unittest.SkipTest("headless OpenGL unavailable")
        cls.fx = next(layer for layer in cls.renderer.fx if isinstance(layer, ParticleFx))

    @classmethod
    def tearDownClass(cls):
        if getattr(cls, "renderer", None) is not None:
            cls.renderer.close()

    def state(self, minutes=DUSK, *, reduced=False):
        state = State.new(self.world, seed=2)
        state.game_minutes = minutes
        state.anchored = True
        state.tutorial = 4
        state.v2.setdefault("settings", {})["reduced_motion"] = reduced
        return state

    def render(self, state, anim, weather="fair"):
        state.anim = anim
        with patch.object(calendar, "weather_at", lambda _state, _minutes: weather):
            return self.renderer.render(state)

    def active(self, state, weather):
        with patch.object(calendar, "weather_at", lambda _state, _minutes: weather):
            light = lighting_at(state.game_minutes + state.minute_acc, state)
            self.fx.uniforms(state, light, self.renderer.camera_for(state))
        return {kind for kind, _strength in self.fx._active}

    def test_weather_and_time_choose_the_systems(self):
        self.assertIn(FIREFLY, self.active(self.state(), "fair"))
        self.assertNotIn(RAIN, self.active(self.state(), "fair"))
        rainy = self.active(self.state(RAIN_AFTERNOON), "drizzle")
        self.assertIn(RAIN, rainy)
        self.assertNotIn(MOTES, rainy)
        self.assertNotIn(FIREFLY, rainy)

    def test_same_state_gives_the_same_frame(self):
        for weather in ("fair", "drizzle"):
            first = self.render(self.state(), 12.5, weather)
            again = self.render(self.state(), 12.5, weather)
            np.testing.assert_array_equal(first, again)

    def test_reduced_motion_holds_the_particles_still(self):
        state = self.state(reduced=True)
        light = lighting_at(state.game_minutes, state)
        cam = self.renderer.camera_for(state)
        times = set()
        for anim in (0.0, 3.0, 37.0, 900.5):
            state.anim = anim
            times.add(self.fx.uniforms(state, light, cam)["p_time"])
        self.assertEqual(len(times), 1)
        # The frame holds still, and so does the particles' own share of it.
        a = self.render(self.state(reduced=True), 3.0).astype(int)
        b = self.render(self.state(reduced=True), 37.0).astype(int)
        np.testing.assert_array_equal(a, b)
        np.testing.assert_array_equal(a - self._without_particles(self.state(reduced=True), 3.0),
                                      b - self._without_particles(self.state(reduced=True), 37.0))
        live = self.render(self.state(), 37.0).astype(int)
        self.assertFalse(np.array_equal(live, self._without_particles(self.state(), 37.0)),
                         "particles should be visible at dusk")

    def _without_particles(self, state, anim):
        with patch.object(self.fx, "draw", lambda *a, **k: None):
            return self.render(state, anim).astype(int)

    def test_depth_is_unchanged_with_particles_on(self):
        for weather in ("fair", "drizzle"):
            state = self.state()
            self.render(state, 0.0, weather)
            with_particles = self.renderer.read_depth()
            self.render(state, 37.0, weather)
            self.assertEqual(with_particles, self.renderer.read_depth())
            with patch.object(self.fx, "draw", lambda *a, **k: None):
                self.render(state, 0.0, weather)
            self.assertEqual(with_particles, self.renderer.read_depth())

    def test_no_gl_objects_are_created_per_frame(self):
        state = self.state()
        self.render(state, 1.0)
        objects = len(self.renderer._objects)
        for anim, weather in ((2.0, "fair"), (3.0, "drizzle"), (4.0, "mist"), (5.0, "clear")):
            self.render(state, anim, weather)
        self.assertEqual(len(self.renderer._objects), objects)

    def test_every_tier_fits_its_budget(self):
        for name, tier in TIERS.items():
            for lake in ("briar", "flathead", "nebula"):
                world = self.world if lake == "briar" else World(lake)
                saved = self.renderer.world
                self.renderer.world = world
                before = len(self.renderer._objects)
                try:
                    with self.renderer.ctx:
                        fx = ParticleFx(self.renderer, tier)
                        seeds = sum(count for kind, (_vao, count) in fx.systems.items()
                                    if kind not in fx.shared)
                        self.assertLessEqual(seeds, tier.particles * 1000, (name, lake))
                        self.assertLessEqual(fx.memory_bytes(), 50 * 1024 * 1024, (name, lake))
                        for obj in self.renderer._objects[before:]:
                            obj.release()
                        del self.renderer._objects[before:]
                finally:
                    self.renderer.world = saved


if __name__ == "__main__":
    unittest.main()
