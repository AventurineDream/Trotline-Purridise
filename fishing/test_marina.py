"""Marina placement, shared collision and unchanged landing access."""

import math
import unittest

import numpy as np

from .boat import BOATS
from .marina import build_marina, footprint_samples
from .sim import State
from .world import World


class MarinaChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.worlds = {lake:World(lake) for lake in ("briar","cedar")}

    def test_moored_hulls_are_wet_and_buildings_are_dry(self):
        for lake,world in self.worlds.items():
            marina = world.marina
            boats = [p for p in marina.footprints if p.kind=="boat"]
            self.assertGreaterEqual(len(boats),4 if lake=="briar" else 6)
            for footprint in boats:
                for a,s in footprint_samples(footprint):
                    self.assertLess(float(world.shore_sd(*world.slip.world(a,s))),-1.0,
                                    (lake,footprint.name,a,s))
            for footprint in marina.shore_buildings:
                for a,s in footprint_samples(footprint):
                    self.assertGreaterEqual(float(world.shore_sd(*world.slip.world(a,s))),1.0,
                                            (lake,footprint.name,a,s))

    def test_every_new_pier_and_hull_is_solid_for_every_player_boat(self):
        for world in self.worlds.values():
            self.assertEqual(len(world.dock_barriers),3+len(world.marina.footprints))
            for footprint in world.marina.footprints:
                x,z = world.slip.world(footprint.a,footprint.s)
                for boat in BOATS:
                    self.assertFalse(world.hull_clear(x,z,0.0,boat),
                                     (world.id,footprint.name,boat))

    def test_service_slip_spawn_tow_and_wide_open_launch_lane(self):
        for world in self.worlds.values():
            yaw = math.atan2(-world.slip.ix,-world.slip.iz)
            for boat in BOATS:
                for a in np.linspace(4,-65,139):
                    self.assertTrue(world.hull_clear(*world.slip.world(float(a),0),yaw,boat),
                                    (world.id,boat,a))
                # Past the original slip, keep a genuinely wide approach,
                # including the largest hull's beam and stern corners.
                for s in (-6.0,6.0):
                    for a in np.linspace(-20,-60,21):
                        self.assertTrue(world.hull_clear(*world.slip.world(float(a),s),yaw,boat),
                                        (world.id,boat,a,s))
            state = State.new(world,seed=31)
            self.assertEqual(state.slip_status(world),"docked")
            self.assertEqual((state.x,state.z),world.slip.world(4.0,0.0))
            self.assertEqual(world.clear_boat_position(state.x,state.z,state.yaw),
                             (state.x,state.z,state.yaw))

    def test_actual_movement_stops_at_added_marina_pier(self):
        for world in self.worlds.values():
            for boat in BOATS:
                state = State.new(world,seed=31)
                state.boat_id = boat
                state.x,state.z = world.slip.world(-27.0,8.0)
                state.yaw = math.atan2(world.slip.sx,world.slip.sz)
                state.anchored = False
                state.motor = 2
                state.speed = state.max_speed()
                state.throttle = state.throttle_setting = 1.0
                for _ in range(100):
                    state.drive(.1,0,0,world)
                    self.assertTrue(world.hull_clear(state.x,state.z,state.yaw,boat),
                                    (world.id,boat))
                _,side = world.slip.local(state.x,state.z)
                self.assertGreater(float(side),10.0,(world.id,boat))
                self.assertLess(float(side),16.925,(world.id,boat))

    def test_geometry_is_static_finite_and_bounded(self):
        for world in self.worlds.values():
            self.assertLess(len(world.faces),10000)
            self.assertLess(len(world.marina.footprints),40)
            self.assertGreater(len(world.marina.faces),1800)
            vertices = np.concatenate([f.pts for f in world.marina.faces])
            self.assertTrue(np.isfinite(vertices).all())
            again = build_marina(world)
            self.assertEqual(world.marina.footprints,again.footprints)
            self.assertTrue(np.array_equal(vertices,np.concatenate([f.pts for f in again.faces])))


if __name__=="__main__":
    unittest.main()
