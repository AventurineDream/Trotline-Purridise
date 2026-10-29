"""V1-22: generated family meshes, paint, NPC placement, handling archetypes and the lineup."""

import math
import unittest

import numpy as np

from . import boatfamilies
from .boat import BOATS, COAST_RATE
from .boatshots import studio
from .data import paint_rgb
from .sim import State
from .software import SoftwareRenderer
from .world import World

GENERATED = [model for model in BOATS.values() if not model.handcrafted]
BOAT_BUFFER_BYTES = 500000  # glrender's dynamic boat buffer, shared with Bot
BYTES_PER_QUAD = 6 * 10 * 4  # six vertices of position, normal, colour and material
LARGEST_BOT_QUADS = 802


class FamilyMeshes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World("briar")
        cls.renderer = SoftwareRenderer.__new__(SoftwareRenderer)

    def faces(self, boat_id, **state_fields):
        state = State.new(self.world, seed=101)
        state.boat_id = boat_id
        for key, value in state_fields.items():
            setattr(state, key, value)
        return self.renderer._boat_faces(state)

    def test_every_family_has_a_generator_and_every_generated_boat_a_hull(self):
        self.assertEqual(set(boatfamilies.FAMILIES), {model.family for model in GENERATED}
                         | {"pioneer", "rowed", "jon", "utility", "runabout", "sail_trawler", "pontoon", "cosmic"})
        self.assertEqual(set(boatfamilies.SPECS), {model.id for model in GENERATED})
        self.assertEqual(len(GENERATED), 20)

    def test_generated_meshes_are_finite_fit_their_hull_and_the_gpu_budget(self):
        for model in GENERATED:
            for light in (False, True):
                with self.subTest(boat=model.id, light=light):
                    faces = self.faces(model.id, light=light, sail_raised=model.power == "sail")
                    points = np.concatenate([face.pts for face in faces])
                    self.assertTrue(np.isfinite(points).all())
                    self.assertTrue(all(face.space == "cam" for face in faces))
                    self.assertLessEqual((len(faces) + LARGEST_BOT_QUADS) * BYTES_PER_QUAD, BOAT_BUFFER_BYTES)
                    # The hull runs the footprint's length; oars, poles and an
                    # outboard's leg may reach a little beyond it.
                    self.assertLessEqual(points[:, 2].min(), model.stern + 0.05)
                    self.assertGreaterEqual(points[:, 2].max(), model.bow - 0.05)
                    self.assertLess(points[:, 2].max(), model.bow + 0.7)
                    self.assertGreater(points[:, 2].min(), model.stern - 0.6)
                    # Some of every boat sits above the water and some below it.
                    self.assertGreater(points[:, 1].max(), -model.eye_height)
                    self.assertLess(points[:, 1].min(), -model.eye_height + 0.05)

    def test_paint_reaches_generated_hulls_and_unpainted_hulls_keep_their_material(self):
        for model in GENERATED:
            with self.subTest(boat=model.id):
                plain = {tuple(np.round(face.color, 4)) for face in self.faces(model.id)}
                painted = self.faces(model.id, look_paint={"hull": "red", "deck": "wood", "motor": "white", "buoy": "orange"})
                colours = {tuple(np.round(face.color, 4)) for face in painted}
                red = tuple(np.round(np.asarray(paint_rgb("hull", "red"), np.float32), 4))
                self.assertIn(red, colours)
                self.assertNotEqual(plain, colours)
                self.assertIn(tuple(np.round(np.asarray(boatfamilies.SPECS[model.id].hull, np.float32), 4)), plain)

    def test_starlight_fittings_glow_and_glow_hulls_emit(self):
        for model in GENERATED:
            emission = {face.emissive for face in self.faces(model.id)}
            with self.subTest(boat=model.id):
                if model.family == "cosmic":
                    self.assertIn(boatfamilies.STAR, emission)
                if "glow" in model.traits:
                    self.assertNotIn(None, emission)

    def test_bot_perches_on_the_foredeck_of_every_generated_boat(self):
        for model in GENERATED:
            x, y, z = boatfamilies.perch(model)
            with self.subTest(boat=model.id):
                self.assertEqual(x, 0.0)
                self.assertGreater(z, 0.0)
                self.assertLess(z, model.bow - 0.5)
                self.assertGreater(y, -model.eye_height)


class NpcBoats(unittest.TestCase):
    def test_npc_boats_use_the_same_generators_placed_in_the_world(self):
        for boat_id in ("party_barge", "dory", "steam_barge"):
            model = BOATS[boat_id]
            faces = boatfamilies.npc_faces(boat_id, 40.0, -25.0, math.pi / 2)
            points = np.concatenate([face.pts for face in faces])
            with self.subTest(boat=boat_id):
                self.assertTrue(all(face.space == "world" for face in faces))
                self.assertTrue(np.isfinite(points).all())
                self.assertLess(points[:, 1].min(), 0.05)
                self.assertGreater(points[:, 1].max(), 0.2)
                # Heading east, the boat's length lies along +x around its position.
                self.assertGreater(points[:, 0].max() - points[:, 0].min(), model.length * 0.95)
                self.assertLess(abs(float(np.median(points[:, 2])) + 25.0), model.half_beam * 1.5 + 1.5)
        with self.assertRaises(ValueError):
            boatfamilies.npc_faces("jon", 0.0, 0.0, 0.0)


class HandlingArchetypes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World("briar")

    def coasted(self, boat_id):
        state = State.new(self.world, seed=102)
        state.boat_id = boat_id
        state.fuel = state.boat.tank
        state.x, state.z, state.yaw = 0.0, 0.0, 0.0
        state.anchored = False
        state.speed, state.throttle, state.throttle_setting = 3.0, 0.0, 0.0
        for _ in range(20):
            state.drive(0.1, 0.0, 0.0, self.world)
        return state.speed

    def test_paddles_stop_short_inboards_carry_way_and_starlight_glides(self):
        paddle, console = self.coasted("birch_skiff"), self.coasted("marsh_runner")
        tiller, inboard = self.coasted("jon"), self.coasted("lake_taxi")
        glide = self.coasted("nebula_cruiser")
        self.assertLess(paddle, console)
        self.assertLess(console, tiller)
        self.assertLess(tiller, inboard)
        self.assertLess(inboard, glide)

    def test_the_four_older_boats_keep_the_original_coast(self):
        for boat_id in ("jon", "rowboat", "sail", "pontoon"):
            self.assertEqual(COAST_RATE[BOATS[boat_id].power], 0.65)
        # 3 m/s decays by (1 - 0.1*0.65) each tenth of a second.
        self.assertAlmostEqual(self.coasted("jon"), 3.0 * (1 - 0.065) ** 20, places=6)


class Lineup(unittest.TestCase):
    def test_studio_views_show_a_boat_on_the_water(self):
        world = World("briar")
        for boat_id in ("houseboat", "log_raft", "small_sloop"):
            state = State.new(world, seed=103)
            state.boat_id = boat_id
            state.sail_raised = BOATS[boat_id].power == "sail"
            image = studio(state, size=128)
            with self.subTest(boat=boat_id):
                self.assertEqual(image.shape, (128, 128, 3))
                self.assertGreater(float(image.std()), 12.0)


if __name__ == "__main__":
    unittest.main()
