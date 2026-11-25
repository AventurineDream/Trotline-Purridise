"""The starter jon boat has a closed transom and a tiller outboard on it (issue #160).

The jon's cockpit faces come from `SoftwareRenderer._boat_faces`; the GL renderer draws
them too, adding its own jon detail in `LakeRenderer._detailed_boat`. Collision uses
`boat.footprint`, and GL boat lighting uses `landfx._jon_boxes`; each must agree with
the outboard as drawn.
"""

import unittest

import numpy as np

from .boat import (BOATS, HULL_HALF_BEAM, HULL_INNER_BEAM, HULL_STERN, JON_OUTBOARD_AFT,
                   JON_OUTBOARD_HALF_WIDTH, hits_round_props, hull_samples)
from .boatmesh import OUTBOARD_PIVOT, outboard_faces
from .sim import State
from .software import SoftwareRenderer
from .test_boatfamilies import BOAT_BUFFER_BYTES, BYTES_PER_QUAD, LARGEST_BOT_QUADS
from .world import World

WATERLINE = -1.22  # the jon's eye height above the water, in its eye frame
COCKPIT_FLOOR, RAIL_TOP = -0.96, -0.465
STEERS = (-1.0, -0.5, 0.0, 0.5, 1.0)


class JonStern(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World("briar")
        cls.renderer = SoftwareRenderer.__new__(SoftwareRenderer)

    def state(self, steer=0.0):
        state = State.new(self.world, seed=160)
        state.boat_id = "jon"
        state.steer = steer
        return state

    def faces(self, steer=0.0):
        return self.renderer._boat_faces(self.state(steer))

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
                 if np.allclose(f.pts[:, 2], HULL_STERN, atol=0.01) and f.normal[2] > 0.9]
        self.assertTrue(inner, "the cockpit sees no transom wall from inside")

    def test_no_back_to_back_skins_share_a_plane(self):
        # The GL pass draws both sides of every face, so two opposite-facing quads in one
        # plane depth-fight into speckle. Checked across the transom and the outboard.
        faces = [f for f in self.faces(0.0) if f.pts[:, 2].min() < HULL_STERN + 0.05]
        flat = [(f, float(f.pts[0, 2])) for f in faces
                if abs(f.normal[2]) > 0.99 and np.ptp(f.pts[:, 2]) < 1e-5]
        for i, (a, za) in enumerate(flat):
            for b, zb in flat[i + 1:]:
                if a.normal[2] * b.normal[2] > 0 or abs(za - zb) > 1e-3:
                    continue
                overlap = all(min(a.pts[:, k].max(), b.pts[:, k].max())
                              > max(a.pts[:, k].min(), b.pts[:, k].min()) + 1e-4 for k in (0, 1))
                self.assertFalse(overlap, f"back-to-back quads at z={za:.3f}")

    def test_outboard_hangs_astern_with_cowl_above_and_prop_below_the_water(self):
        pts = self.aft()
        self.assertGreater(pts[:, 1].max(), RAIL_TOP + 0.15, "no powerhead above the rail")
        self.assertLess(pts[:, 1].min(), WATERLINE - 0.3, "no lower unit in the water")
        self.assertLess(pts[:, 2].min(), HULL_STERN - 0.4)
        self.assertAlmostEqual(float(pts[:, 0].mean()), OUTBOARD_PIVOT[0], delta=0.02)

    def test_the_lower_unit_stays_inside_the_jons_draft(self):
        # Navigation only allows water deeper than the boat's draft, so a skeg reaching
        # further down would visibly cut through the lake bed in the shallowest water.
        for steer in STEERS:
            with self.subTest(steer=steer):
                self.assertGreaterEqual(self.aft(steer)[:, 1].min(), WATERLINE - BOATS["jon"].draft)

    def test_steering_swings_the_lower_unit_to_the_turn_side(self):
        # Turning to starboard (steer > 0) pushes the underwater lower unit to starboard,
        # symmetric in steer, and its mean lateral offset is zero at zero steer.
        def lower_unit_x(steer):
            pts = self.aft(steer)
            return float(pts[pts[:, 1] < WATERLINE - 0.1][:, 0].mean())
        self.assertAlmostEqual(lower_unit_x(0.0), 0.0, delta=0.01)
        self.assertGreater(lower_unit_x(1.0), 0.05)
        self.assertLess(lower_unit_x(-1.0), -0.05)
        self.assertAlmostEqual(lower_unit_x(0.3), -lower_unit_x(-0.3), delta=1e-4)

    def test_outboard_never_reaches_into_the_cockpit_at_any_steer(self):
        for steer in STEERS:
            pts = np.concatenate([f.pts for f in outboard_faces(steer, (0.2, 0.2, 0.2))])
            inside = ((np.abs(pts[:, 0]) < HULL_INNER_BEAM) & (pts[:, 2] > HULL_STERN)
                      & (pts[:, 1] > COCKPIT_FLOOR) & (pts[:, 1] < RAIL_TOP))
            with self.subTest(steer=steer):
                self.assertFalse(inside.any(), pts[inside][:3])

    def test_the_collision_footprint_covers_the_outboard_at_every_steer(self):
        samples = hull_samples(0.0, 0.0, 0.0, "jon")  # yaw 0: x is starboard, z is forward
        for steer in STEERS:
            pts = np.concatenate([f.pts for f in outboard_faces(steer, (0.2, 0.2, 0.2))])
            with self.subTest(steer=steer):
                self.assertGreaterEqual(pts[:, 2].min(), JON_OUTBOARD_AFT)
                self.assertLessEqual(np.abs(pts[:, 0]).max(), JON_OUTBOARD_HALF_WIDTH)
        self.assertLessEqual(samples[:, 1].min(), JON_OUTBOARD_AFT)

    def test_a_post_behind_the_transom_stops_the_motor_but_not_open_water_beside_it(self):
        post = lambda x, z: np.array([[x, z, 0.05]])  # noqa: E731 - (x, z, radius) in metres
        self.assertTrue(hits_round_props(0.0, 0.0, 0.0, post(0.0, -1.2), "jon"),
                        "the outboard passed through a post")
        self.assertFalse(hits_round_props(0.0, 0.0, 0.0, post(0.62, -1.2), "jon"),
                         "open water beside the motor counts as hull")

    def test_occluder_boxes_follow_the_drawn_outboard(self):
        from .landfx import MAX_BOXES, _jon_boxes
        for steer in STEERS:
            faces = outboard_faces(steer, (0.2, 0.2, 0.2))
            boxes = _jon_boxes(self.state(steer))
            # Bot's perch takes one more slot when it is home.
            self.assertLessEqual(len(boxes) + 1, MAX_BOXES)
            # Six faces per cuboid: the cowl is the second part, the midsection the fourth.
            for (centre, half), first in zip(boxes[-2:], (6, 18)):
                pts = np.concatenate([f.pts for f in faces[first:first + 6]])
                lo, hi = pts.min(axis=0), pts.max(axis=0)
                with self.subTest(steer=steer, part=first):
                    np.testing.assert_allclose(centre, (lo + hi) / 2, atol=1e-4)
                    np.testing.assert_allclose(half, (hi - lo) / 2, atol=1e-4)

    def test_the_gl_jon_and_largest_bot_still_fit_the_boat_buffer(self):
        from .glrender import LakeRenderer
        renderer = LakeRenderer.__new__(LakeRenderer)
        quads = len(renderer._detailed_boat(self.state())) + LARGEST_BOT_QUADS
        self.assertLessEqual(quads * BYTES_PER_QUAD, BOAT_BUFFER_BYTES)


if __name__ == "__main__":
    unittest.main()
