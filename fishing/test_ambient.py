"""Bounded, world-anchored wildlife without save or simulation side effects."""

import copy
import math
import unittest
from unittest.mock import patch

import numpy as np

from . import ambient
from .camera import Camera
from .sim import State
from .software import SoftwareRenderer, _legacy_birds_visible
from .weather import lighting_at
from .world import World


def geometry(faces):
    return np.concatenate([np.concatenate((face.pts.ravel(), face.normal, face.color))
                           for face in faces]) if faces else np.empty(0, np.float32)


class AmbientChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worlds = {lake: World(lake) for lake in ('briar', 'cedar')}

    def check_geometry(self, faces):
        self.assertLessEqual(len(faces), ambient.MAX_FACES)
        self.assertLessEqual(ambient.MAX_FACES, 256)
        for face in faces:
            self.assertEqual(face.space, 'world')
            self.assertEqual(face.pts.shape, (4, 3))
            self.assertEqual(face.normal.shape, (3,))
            self.assertEqual(face.color.shape, (3,))
            for values in (face.pts, face.normal, face.color):
                self.assertEqual(values.dtype, np.float32)
                self.assertTrue(np.isfinite(values).all())
            self.assertAlmostEqual(float(np.linalg.norm(face.normal)), 1.0, places=5)
            self.assertTrue(((face.color >= 0) & (face.color <= 1)).all())
        # Six packed mesh vertices, ten float channels each. The renderer
        # streams wildlife into the existing 500 KB dynamic mesh buffer.
        self.assertLessEqual(len(faces) * 6 * 10 * 4, 500_000)

    def test_both_lakes_remain_finite_and_bounded_across_64_conditions(self):
        conditions = ((0, 0, 0), (37, 0, 0), (3, 1, 0), (37, 1, 0),
                      (12, .4, 0), (43, 0, .7), (60, 0, 1), (1200, 1, 1))
        for lake, world in self.worlds.items():
            state = State.new(world, seed=37)
            positions = ((state.x, state.z), world.dock,
                         tuple(world.zones[1][1:3]), (world.bounds[2] + 1000, world.bounds[3] + 1000))
            for position in positions:
                state.x, state.z = position
                for anim, night, rain in conditions:
                    with self.subTest(lake=lake, position=position, anim=anim, night=night, rain=rain):
                        state.anim = anim
                        self.check_geometry(ambient.faces(state, world, {'night': night, 'rain': rain}))

    def test_same_time_and_world_produce_same_geometry_without_state_changes(self):
        for world in self.worlds.values():
            state = State.new(world, seed=41)
            state.anim, state.game_minutes, state.minute_acc = 12.75, 720, .35
            state.x, state.z = world.dock
            fields = set(vars(state))
            before_clock = (state.anim, state.minute_acc, state.x, state.z, state.yaw)
            before_toasts = copy.deepcopy(state.toasts)
            with patch('fishing.sim.time.time', return_value=1234):
                before = state.to_json()
                first = ambient.faces(state, world)
                second = ambient.faces(state, world)
                explicit = ambient.faces(state, world, lighting_at(state.game_minutes + state.minute_acc, state))
                np.testing.assert_array_equal(geometry(first), geometry(second))
                np.testing.assert_array_equal(geometry(first), geometry(explicit))
                self.assertEqual(state.to_json(), before)
            self.assertEqual(set(vars(state)), fields)
            self.assertEqual((state.anim, state.minute_acc, state.x, state.z, state.yaw), before_clock)
            self.assertEqual(state.toasts, before_toasts)

    def test_day_has_distinct_birds_and_dragonflies_night_has_fireflies(self):
        for world in self.worlds.values():
            state = State.new(world, seed=41)
            state.anim = 3
            day = ambient.faces(state, world, {'night': 0, 'rain': 0})
            birds_only = ambient.faces(state, world, {'night': 0, 'rain': .7})
            night = ambient.faces(state, world, {'night': 1, 'rain': 0})
            self.assertTrue(birds_only, world.id)
            self.assertGreater(len(day), len(birds_only), world.id)
            self.assertTrue(night, world.id)
            # Firefly geometry stays near the bank rather than in bird orbits.
            for face in night:
                self.assertTrue(np.all(face.pts[:, 1] < 4), world.id)
            state.anim = 4
            self.assertFalse(np.array_equal(geometry(day), geometry(
                ambient.faces(state, world, {'night': 0, 'rain': 0}))))
            self.assertFalse(np.array_equal(geometry(night), geometry(
                ambient.faces(state, world, {'night': 1, 'rain': 0}))))
            self.assertEqual(ambient.faces(state, world, {'night': 0, 'rain': 1}), [])
            self.assertEqual(ambient.faces(state, world, {'night': 1, 'rain': 1}), [])

    def test_bird_species_have_distinct_silhouettes(self):
        shapes = []
        self.assertGreaterEqual(len(ambient.BIRD_SPECIES), 3)
        for species in ambient.BIRD_SPECIES:
            faces = []
            ambient._bird(faces, 0, 8, 0, .4, species, 3, .5)
            self.assertTrue(faces)
            self.check_geometry(faces)
            shapes.append(geometry(faces))
        for i, first in enumerate(shapes):
            for second in shapes[i + 1:]:
                self.assertFalse(np.array_equal(first, second))

    def test_cpu_renderer_draws_ambient_bird_faces_from_both_sides(self):
        world = self.worlds['briar']
        renderer = SoftwareRenderer(world, 128, 96)
        camera = Camera(0, 1.22, 0, 0, -0.055, 0, math.radians(74), 128, 96,
                        build_rays=False)
        birds = []
        ambient._bird(birds, 0, 5, 8, 0, 'gull', 3, .5)
        light = {
            'sun': np.array([0, 1, 0], np.float32),
            'night': 0.0,
            'moon_i': 0.0,
            'sun_i': 1.0,
        }

        renderer._faces(camera, birds, light, boat=False)
        self.assertFalse(np.any(renderer.col))
        renderer._faces(camera, birds, light, boat=False, two_sided=True)
        self.assertTrue(np.any(renderer.col))

    def test_legacy_cpu_birds_follow_daylight_and_heavy_rain_gates(self):
        self.assertTrue(_legacy_birds_visible({'night': 0.0, 'rain': 0.0}))
        self.assertTrue(_legacy_birds_visible({'night': 0.64, 'rain': 0.79}))
        self.assertFalse(_legacy_birds_visible({'night': 0.65, 'rain': 0.0}))
        self.assertFalse(_legacy_birds_visible({'night': 0.0, 'rain': 0.8}))

    def test_camera_turns_and_small_boat_moves_do_not_drag_wildlife(self):
        for world in self.worlds.values():
            state = State.new(world, seed=41)
            state.anim = 3
            for light in ({'night': 0, 'rain': .7}, {'night': 1, 'rain': 0}):
                first = ambient.faces(state, world, light)
                self.assertTrue(first, (world.id, light))
                state.x += .00001
                state.z += .00001
                state.yaw += 1.5
                state.look = .4
                np.testing.assert_array_equal(geometry(first), geometry(ambient.faces(state, world, light)))
            first = ambient.faces(state, world, {'night': 1, 'rain': 0})
            state.x += 64
            state.z += 64
            moved = ambient.faces(state, world, {'night': 1, 'rain': 0})
            self.check_geometry(moved)
            self.assertFalse(np.array_equal(geometry(first), geometry(moved)))


if __name__ == '__main__':
    unittest.main()
