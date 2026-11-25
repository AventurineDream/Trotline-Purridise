"""Issue #160: the starter jon boat has a closed transom and a tiller outboard on it.

The jon's cockpit faces come from `SoftwareRenderer._boat_faces`, which the GL renderer
also draws (`LakeRenderer._detailed_boat`), so these checks cover both render paths.
"""

import unittest

import numpy as np

from .boat import HULL_HALF_BEAM, HULL_INNER_BEAM, HULL_STERN
from .boatmesh import OUTBOARD_PIVOT
from .sim import State
from .software import SoftwareRenderer
from .test_boatfamilies import BOAT_BUFFER_BYTES, BYTES_PER_QUAD, LARGEST_BOT_QUADS
from .world import World

WATERLINE = -1.22  # the jon's eye height above the water, in its eye frame
COCKPIT_FLOOR, RAIL_TOP = -0.96, -0.465


class JonStern(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World("briar")
        cls.renderer = SoftwareRenderer.__new__(SoftwareRenderer)

    def faces(self, steer=0.0):
        state = State.new(self.world, seed=160)
        state.boat_id = "jon"
        state.steer = steer
        return self.renderer._boat_faces(state)

    def aft(self, steer=0.0):
        """Vertices of every face that lies wholly astern of the transom: the outboard."""
        faces = [f for f in self.faces(steer) if f.pts[:, 2].max() < HULL_STERN - 0.02]
        return np.concatenate([f.pts for f in faces])

    def test_transom_closes_the_stern_from_rail_to_below_the_waterline(self):
        outer = [f for f in self.faces()
                 if np.allclose(f.pts[:, 2], HULL_STERN) and f.normal[2] < -0.9]
        self.assertTrue(outer, "no aft-facing transom skin at the stern")
        pts = np.concatenate([f.pts for f in outer])
        self.assertLessEqual(pts[:, 0].min(), -HULL_HALF_BEAM + 1e-4)
        self.assertGreaterEqual(pts[:, 0].max(), HULL_HALF_BEAM - 1e-4)
        self.assertLess(pts[:, 1].min(), WATERLINE)
        inner = [f for f in self.faces()
                 if np.allclose(f.pts[:, 2], HULL_STERN) and f.normal[2] > 0.9]
        self.assertTrue(inner, "the cockpit sees no transom wall from inside")

    def test_outboard_hangs_astern_with_cowl_above_and_prop_below_the_water(self):
        pts = self.aft()
        self.assertGreater(pts[:, 1].max(), RAIL_TOP + 0.15, "no powerhead above the rail")
        self.assertLess(pts[:, 1].min(), WATERLINE - 0.3, "no lower unit in the water")
        self.assertLess(pts[:, 2].min(), HULL_STERN - 0.4)
        self.assertGreater(pts[:, 2].min(), HULL_STERN - 0.8, "outboard floats off the stern")
        self.assertAlmostEqual(float(pts[:, 0].mean()), OUTBOARD_PIVOT[0], delta=0.02)

    def test_steering_swings_the_lower_unit_to_the_turn_side(self):
        # Turning to starboard (steer > 0) pushes the underwater lower unit to starboard,
        # symmetrically, and it rests on the centreline with no jitter at zero steer.
        def lower_unit_x(steer):
            pts = self.aft(steer)
            return float(pts[pts[:, 1] < WATERLINE - 0.2][:, 0].mean())
        self.assertAlmostEqual(lower_unit_x(0.0), 0.0, delta=0.01)
        self.assertGreater(lower_unit_x(1.0), 0.05)
        self.assertLess(lower_unit_x(-1.0), -0.05)
        self.assertAlmostEqual(lower_unit_x(0.3), -lower_unit_x(-0.3), delta=1e-4)

    def test_outboard_never_reaches_into_the_cockpit_at_any_steer(self):
        for steer in (-1.0, -0.5, 0.0, 0.5, 1.0):
            from .boatmesh import outboard_faces
            pts = np.concatenate([f.pts for f in outboard_faces(steer, (0.2, 0.2, 0.2))])
            inside = ((np.abs(pts[:, 0]) < HULL_INNER_BEAM) & (pts[:, 2] > HULL_STERN)
                      & (pts[:, 1] > COCKPIT_FLOOR) & (pts[:, 1] < RAIL_TOP))
            with self.subTest(steer=steer):
                self.assertFalse(inside.any(), pts[inside][:3])

    def test_the_jon_and_largest_bot_still_fit_the_boat_buffer(self):
        quads = len(self.faces()) + LARGEST_BOT_QUADS
        self.assertLessEqual(quads * BYTES_PER_QUAD, BOAT_BUFFER_BYTES)


if __name__ == "__main__":
    unittest.main()
