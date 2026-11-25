"""Corner-chart zoom: the window follows the boat, markers stay on the cropped chart's
pixels and inside its panel, the zoom key cycles levels, and old key bindings keep
their key."""

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from .game import Keys, Session
from .gamepad import DEFAULT_KEY_BINDINGS, normalize_key_bindings, remap_keyboard
from .platform import Text
from .savepaths import load_game_save
from .sim import State
from .ui import CHART_ZOOMS, UI, chart_window
from .world import World


def _physical(key):
    """One frame with `key` pressed on the keyboard, before the binding remap."""
    keys = Keys()
    keys.device = "keyboard"
    keys.keyboard_pressed, keys.keyboard_held = {key}, {key}
    return keys


class ChartWindow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worlds = [World("briar"), World("cedar")]

    def boat_positions(self, world):
        """The lake's centre and a spot just inside each corner, in world metres."""
        x0, z0, x1, z1 = world.bounds
        inset_x, inset_z = (x1 - x0) * 0.02, (z1 - z0) * 0.02
        return [((x0 + x1) / 2, (z0 + z1) / 2),
                (x0 + inset_x, z0 + inset_z), (x1 - inset_x, z0 + inset_z),
                (x0 + inset_x, z1 - inset_z), (x1 - inset_x, z1 - inset_z)]

    def test_1x_is_the_whole_lake(self):
        for world in self.worlds:
            rows, cols = world.map_rgb.shape[:2]
            crop, view = chart_window(world.bounds, world.map_rgb.shape, 0.0, 0.0, 1)
            self.assertEqual(crop, (0, rows, 0, cols))
            np.testing.assert_allclose(view, world.bounds)

    def test_zoomed_markers_land_on_the_cropped_chart_pixels(self):
        rng = np.random.default_rng(165)
        for world in self.worlds:
            rows, cols = world.map_rgb.shape[:2]
            for zoom in CHART_ZOOMS[1:]:
                for bx, bz in self.boat_positions(world):
                    (r0, r1, c0, c1), view = chart_window(world.bounds, world.map_rgb.shape, bx, bz, zoom)
                    with self.subTest(lake=world.id, zoom=zoom, boat=(round(bx), round(bz))):
                        self.assertTrue(0 <= r0 < r1 <= rows and 0 <= c0 < c1 <= cols)
                        self.assertEqual((r1 - r0, c1 - c0), (round(rows / zoom), round(cols / zoom)))
                        # The boat is always on the window, even against the shore.
                        bu, bv = world.map_pixel(bx, bz, c1 - c0, r1 - r0, view)
                        self.assertTrue(0 <= bu < c1 - c0 and 0 <= bv < r1 - r0, (bu, bv))
                        # Any point in the window falls on the crop pixel showing that
                        # spot of the whole-lake chart.
                        vx0, vz0, vx1, vz1 = view
                        for px, pz in zip(rng.uniform(vx0, vx1, 40), rng.uniform(vz0, vz1, 40)):
                            fu, fv = world.map_pixel(px, pz, cols, rows)
                            u, v = world.map_pixel(px, pz, c1 - c0, r1 - r0, view)
                            self.assertLessEqual(abs(u - (fu - c0)), 1)
                            self.assertLessEqual(abs(v - (fv - r0)), 1)

    def test_the_window_follows_the_boat_without_jumping(self):
        world = self.worlds[0]
        x0, z0, x1, z1 = world.bounds
        metres_per_pixel = (x1 - x0) / (world.map_rgb.shape[1] - 1)
        z = (z0 + z1) / 2
        previous = None
        for x in np.linspace(x0, x1, 400):
            (_r0, _r1, c0, _c1), _view = chart_window(world.bounds, world.map_rgb.shape, x, z, 4)
            if previous is not None:
                step = (x1 - x0) / 399 / metres_per_pixel
                self.assertGreaterEqual(c0, previous)
                self.assertLessEqual(c0 - previous, int(np.ceil(step)) + 1)
            previous = c0


class ZoomedCornerChart(unittest.TestCase):
    def setUp(self):
        self.world = World("briar")
        self.text = Text()
        self.addCleanup(self.text.close)
        self.painter = UI(self.text, self.world)
        self.addCleanup(self.painter.close)
        self.state = State.new(self.world, seed=165)
        x0, z0, x1, z1 = self.world.bounds
        self.state.x, self.state.z = x0 + 30.0, z1 - 30.0  # the north-west corner
        # Two markers across the lake: Bot out on the water, and an invitation mark.
        self.state.bot_phase, self.state.bot_x, self.state.bot_z = "out", x1 - 30.0, z0 + 30.0
        self.state.v2.setdefault("calendar", {})["invitation_mark"] = {
            "lake_id": self.world.id, "x": x1 - 60.0, "z": (z0 + z1) / 2,
            "until_game_minutes": self.state.game_minutes + 600}

    def draw(self, zoom):
        frame = np.zeros((720, 1280, 3), np.uint8)
        height = self.painter._minimap(frame, self.state, 20, 700, "keyboard", zoom)
        return frame, height

    def test_markers_beyond_the_window_stay_inside_the_chart_panel(self):
        for zoom in CHART_ZOOMS:
            frame, height = self.draw(zoom)
            with self.subTest(zoom=zoom):
                mw = max(96, int(1280 * 0.14))
                top, left, right = 700 - height, 20, 20 + mw + 16 + 2  # +2, +4: the panel's shadow
                outside = frame.copy()
                outside[top:700 + 4, left:right] = 0
                self.assertEqual(int(np.count_nonzero(outside)), 0)

    def test_each_level_draws_a_different_view_and_the_zoom_resets(self):
        frames = [self.draw(zoom)[0] for zoom in CHART_ZOOMS]
        for a, b in zip(frames, frames[1:]):
            self.assertFalse(np.array_equal(a, b))
        self.assertIsNone(self.painter._chart_view)  # the full chart is never left zoomed
        np.testing.assert_array_equal(self.draw(1)[0], frames[0])

    def test_a_zoomed_chart_draws_the_boat_where_the_window_puts_it(self):
        # 30% across the lake: the 4x window centres on the boat there without
        # meeting the shore, while the whole-lake chart would draw it 30% across.
        x0, z0, x1, z1 = self.world.bounds
        self.state.x, self.state.z = x0 + 0.3 * (x1 - x0), (z0 + z1) / 2
        self.state.bot_phase = "home"
        del self.state.v2["calendar"]["invitation_mark"]
        frame, _height = self.draw(4)
        rows, cols = np.nonzero(np.all(frame == (236, 224, 180), axis=2))  # the boat disc
        self.assertGreater(len(rows), 20)
        mw = max(96, int(1280 * 0.14))
        mh = max(64, int(mw * self.world.map_small.shape[0] / self.world.map_small.shape[1]))
        chart_left, chart_top = 20 + 8, 700 - mh - 7
        self.assertLessEqual(abs(cols.mean() - (chart_left + (mw - 1) / 2)), 2)
        self.assertLessEqual(abs(rows.mean() - (chart_top + (mh - 1) / 2)), 2)


class ZoomKey(unittest.TestCase):
    def session(self, bindings=None):
        world = World("briar")
        temp = tempfile.TemporaryDirectory(prefix="trotline-chart-zoom-")
        self.addCleanup(temp.cleanup)
        state = State.new(world, seed=165)
        if bindings is not None:
            state.v2["settings"]["key_bindings"] = bindings
        session = Session(world, Path(temp.name) / "save.json", state, False)
        session.ui.mode = "play"
        return session

    def test_x_cycles_the_corner_chart_through_its_levels(self):
        session = self.session()
        seen = [session.ui.chart_zoom]
        for _ in CHART_ZOOMS:
            session.tick(_physical("x"), 0.05)
            seen.append(session.ui.chart_zoom)
        self.assertEqual(seen, [*CHART_ZOOMS, CHART_ZOOMS[0]])
        self.assertEqual(session.ui.mode, "play")

    def test_the_right_stick_zooms_even_when_x_naps_on_the_keyboard(self):
        # RS click arrives as the canonical zoom symbol; keyboard bindings never remap it.
        session = self.session(dict(DEFAULT_KEY_BINDINGS, catnap="x", chart_zoom="l"))
        pad = Keys({"x"})
        pad.device = "gamepad"
        session.tick(pad, 0.05)
        self.assertEqual(session.ui.chart_zoom, CHART_ZOOMS[1])

    def test_a_save_that_already_bound_x_keeps_it(self):
        # Settings saved before the zoom existed: a full map without it, catnap on X.
        old = {action: key for action, key in DEFAULT_KEY_BINDINGS.items() if action != "chart_zoom"}
        old["catnap"] = "x"
        pressed, _held = remap_keyboard({"x"}, {"x"}, old)
        self.assertIn("z", pressed)  # the catnap action
        self.assertNotIn("x", pressed)  # and nothing else
        bindings = normalize_key_bindings(old)
        self.assertEqual(len(set(bindings.values()) - {bindings["hail"], bindings["pause"], bindings["anchor"]}),
                         len(bindings) - 6)  # every key but the three alias pairs is unique
        session = self.session(old)
        session.tick(_physical(bindings["chart_zoom"]), 0.05)
        self.assertEqual(session.ui.chart_zoom, CHART_ZOOMS[1])

    def test_loading_an_old_save_with_x_bound_does_not_double_fire(self):
        old = {action: key for action, key in DEFAULT_KEY_BINDINGS.items() if action != "chart_zoom"}
        old["catnap"] = "x"
        session = self.session()
        session.save()
        # Rewrite the settings as a save from before the zoom existed would hold them.
        saved = json.loads(session.save_path.read_text())
        saved["v2"]["settings"]["key_bindings"] = old
        session.save_path.write_text(json.dumps(saved))
        _world, loaded, _has_save = load_game_save(session.save_path, State, World)
        bindings = loaded.v2["settings"]["key_bindings"]
        self.assertEqual(bindings["catnap"], "x")
        self.assertNotEqual(bindings["chart_zoom"], "x")
        pressed, _held = remap_keyboard({"x"}, {"x"}, bindings)
        self.assertEqual(pressed, {"z"})  # X still naps, and only naps

    def test_loading_keeps_bindings_for_actions_from_a_newer_build(self):
        session = self.session()
        session.save()
        saved = json.loads(session.save_path.read_text())
        saved["v2"]["settings"]["key_bindings"]["future_action"] = "p"
        session.save_path.write_text(json.dumps(saved))
        _world, loaded, _has_save = load_game_save(session.save_path, State, World)
        bindings = loaded.v2["settings"]["key_bindings"]
        self.assertEqual(bindings["future_action"], "p")
        self.assertEqual(normalize_key_bindings(bindings), normalize_key_bindings(None))


if __name__ == "__main__":
    unittest.main()
