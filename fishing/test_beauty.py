"""V1-42: the second graphics pass. Key-art review frames, and the defects it fixed stay fixed."""

from __future__ import annotations

import math
from pathlib import Path
import tempfile
import unittest

import numpy as np

from . import beautyshots, calendar
from .lakes import LAKES
from .pngsave import read_png, write_png
from .render import Renderer
from .sim import State
from .skipper import silhouette_rgb
from .weather import lighting_at
from .world import World


def _software_frame(lake, minute, turn=0.0):
    world = World(lake)
    renderer = Renderer(world, 480, 270, software=True)
    try:
        state = State.new(world, seed=beautyshots.SEED)
        state.v2.setdefault("calendar", {})["seed"] = calendar.forecast_seed(state)
        state.game_minutes = minute
        state.anim = 2.0
        state.yaw = (state.yaw + turn + math.pi) % math.tau - math.pi
        return renderer.render(state).astype(np.float32) / 255.0
    finally:
        renderer.close()


class BeautyMatrix(unittest.TestCase):
    def test_png_round_trip(self):
        image = (np.arange(4 * 5 * 3) % 256).astype(np.uint8).reshape(4, 5, 3)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "frame.png"
            write_png(path, image)
            self.assertTrue(np.array_equal(read_png(path), image))

    def test_every_lake_has_its_times_of_day_and_signature_weather(self):
        seed = State.new(World("briar"), seed=beautyshots.SEED).rng.s
        for lake in LAKES:
            rows = beautyshots.moments(seed, lake)
            names = [name for name, _minute, _weather in rows]
            signature = beautyshots.SIGNATURE[lake][0]
            self.assertIn(signature, names, lake)
            self.assertGreaterEqual(len(rows), 4, lake)
            for name, minute, weather in rows:
                self.assertEqual(calendar.planned_weather(seed, lake, minute), weather, (lake, name))
                if name != signature:
                    self.assertIn(weather, beautyshots.CALM, (lake, name))


class SecondPassFixes(unittest.TestCase):
    def test_the_skippers_reflection_is_the_coat_in_shadow_not_black(self):
        state = State.new(World("briar"), seed=3)
        shade = silhouette_rgb(state)
        self.assertGreater(float(shade.mean()), 0.2)
        ratios = shade / np.asarray(state.v2["skipper"]["colors"]["base"], np.float32)
        self.assertTrue(np.allclose(ratios, ratios[0]))

    def test_the_night_horizon_is_lighter_than_the_night_zenith(self):
        light = lighting_at(1050.0)
        self.assertGreater(light["night"], 0.9)
        self.assertGreater(float(np.mean(light["horizon"])), 0.09)
        self.assertGreater(float(np.mean(light["horizon"])), float(np.mean(light["zenith"])) * 2.0)

    def test_software_water_by_the_slip_is_not_blown_out(self):
        # The water each side of the docked boat once swirled white with shore foam.
        for lake, minute in (("briar", 1830), ("crater", 1470)):
            with self.subTest(lake=lake):
                frame = _software_frame(lake, minute)
                h, w = frame.shape[:2]
                rows = slice(int(h * .70), int(h * .92))
                sides = np.concatenate([frame[rows, :int(w * .12)].reshape(-1, 3),
                                        frame[rows, int(w * .88):].reshape(-1, 3)])
                self.assertLess(float(np.percentile(sides.mean(axis=1), 95)), 0.6)

    def test_software_caldera_walls_read_in_horizontal_strata(self):
        # Facing the landing, the caldera wall above the roofline once showed grey columns.
        frame = _software_frame("crater", 1830, turn=math.pi).mean(axis=2)
        h, w = frame.shape
        wall = frame[int(h * .02):int(h * .20), int(w * .05):int(w * .95)]
        down = float(np.abs(np.diff(wall, axis=0)).mean())
        across = float(np.abs(np.diff(wall, axis=1)).mean())
        self.assertGreater(down, across)


if __name__ == "__main__":
    unittest.main()
