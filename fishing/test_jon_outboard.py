"""The starter jon boat has a closed transom and a tiller outboard on it (issue #160).

The tiller arm, knuckle, rod and grip (issue #192) hang from the outboard's swivel and end at
the grip the Skipper's paw holds. Both renderers draw them from `boatmesh.tiller_faces`.

The jon's cockpit faces come from `SoftwareRenderer._boat_faces`; the GL renderer draws
them too, adding its own jon detail in `LakeRenderer._detailed_boat`. Collision uses
`boat.footprint`, and GL boat lighting uses `landfx._jon_boxes`; each must agree with
the outboard as drawn.
"""

import math
import unittest
from collections import namedtuple
from types import SimpleNamespace

import numpy as np

from . import skipper
from .boat import (BOATS, HULL_HALF_BEAM, HULL_INNER_BEAM, HULL_STERN, JON_OUTBOARD_AFT,
                   JON_OUTBOARD_HALF_WIDTH, hits_round_props, hull_samples)
from .boatmesh import (OUTBOARD_PIVOT, OUTBOARD_YAW, TILLER_ARM_HALF, TILLER_GRIP_HALF, TILLER_GRIP_LENGTH,
                       TILLER_KNUCKLE_HALF, TILLER_ROD_HALF, outboard_faces, tiller_faces, tiller_joints,
                       tiller_parts)
from .camera import Camera
from .data import paint_rgb
from .sim import State
from .software import FOV, SoftwareRenderer
from .test_boatfamilies import BOAT_BUFFER_BYTES, BYTES_PER_QUAD, LARGEST_BOT_QUADS
from .world import World

WATERLINE = -1.22  # the jon's eye height above the water, in its eye frame
COCKPIT_FLOOR, RAIL_TOP = -0.96, -0.465
STEERS = (-1.0, -0.5, 0.0, 0.5, 1.0)
# The sweep: 0.1 s steps over 22 s, plus the wave forearm's exact peaks. The forearm swings at 1.5 Hz,
# too fast for that grid: sin(2 pi 1.5 t) is +1 at t = (k + 1/4) / 1.5 and -1 at t = (k + 3/4) / 1.5.
# The 22 s window spans several idle periods (glances every 3-6 s, tail flicks every 6-10 s), sampled every 0.1 s.
# Every temporal check here holds at these sampled times only, not continuously. The 0.02 s comparison in
# test_the_sweep_grid_resolves_the_least_rest_clearance is the one check of the grid's resolution.
WAVE_SWEEP = np.union1d(np.arange(0.0, 22.0, 0.1),
                        np.concatenate([np.arange(33) + 0.25, np.arange(33) + 0.75]) / 1.5)
WAVE_SWEEP = WAVE_SWEEP[WAVE_SWEEP < 22.0]
WAVE_FOREARM = 0.45  # radians: catmotion.wave's amplitude
# Cat distances across the blend from tiller to wave: skipperview.SkipperFigure.params fades the wave from
# 14 m (blend 1) to 20 m (blend 0), so these are mid-blend.
MID_BLEND_M = np.arange(15.0, 19.01, 0.5)
# Asserted limits, metres. WALL_MARGIN bounds the figure's distance inside the hull's walls and above the
# floor; those planar bounds are exact on the posed vertices, since a planar function's least over a
# triangle is at a corner. TILLER_CLEARANCE bounds the least distance from the figure's surface to the
# tiller's solids, certified by _surface_clearance. SURFACE_TOLERANCE is the triangle radius, metres (the
# largest centroid-to-vertex distance), at which _settle gives up: a floor it cannot decide is refused.
WALL_MARGIN = 0.03
TILLER_CLEARANCE = 0.02
SURFACE_TOLERANCE = 0.0005
# The grip paw is held to the grip, not to a clearance floor: PAW_CONTACT is the most its surface may sit from the
# grip solid (the first-person grip's own bound, test_the_paw_holds_the_grip_at_every_steer), PAW_FLOOR the least
# (no penetration). BENCH_CLEARANCE is the figure's clearance short of the bench's front face at z 1.44 m: the grip
# is at z 1.14-1.20 m, so the paw's top reaches z 1.19 m and the helm figure's old 0.50 m clearance cannot hold.
PAW_CONTACT = 0.02
PAW_FLOOR = 0.001
BENCH_CLEARANCE = 0.24
# A posed figure: `body` the posed vertices in the eye frame (k, n, 3); `faces` the triangles (m, 3); `forearm`
# and `blend` at each sweep time; `paw` the grip paw's triangles, `wave` the waving paw's, `rest` every other one.
Posed = namedtuple("Posed", "body faces forearm blend paw wave rest")


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
        """Vertices of every face wholly astern of the transom: the outboard, plus the tiller
        arm's root cap, which sinks into the cowl and so lies astern too."""
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
        # plane depth-fight into speckle. Checked on every axis over the stern and outboard as
        # drawn, and over every tiller part (arm, knuckle, rod, grip) at every steer, because the
        # outboard and the tiller both swing with it. The drawn arm is the tiller's own geometry,
        # so it is taken from the parts and not counted twice.
        for steer in STEERS:
            tiller = [f for part in tiller_parts(steer, TILLER_PAINT).values() for f in part]
            drawn = [f for f in self.faces(steer) if f.pts[:, 2].min() < HULL_STERN + 0.05
                     and not any(np.allclose(f.pts, t.pts) for t in tiller)]
            faces = drawn + tiller
            for axis in range(3):
                others = [k for k in range(3) if k != axis]
                flat = [(f, float(f.pts[0, axis])) for f in faces
                        if abs(f.normal[axis]) > 0.99 and np.ptp(f.pts[:, axis]) < 1e-5]
                for i, (a, pa) in enumerate(flat):
                    for b, pb in flat[i + 1:]:
                        if a.normal[axis] * b.normal[axis] > 0 or abs(pa - pb) > 1e-3:
                            continue
                        overlap = all(min(a.pts[:, k].max(), b.pts[:, k].max())
                                      > max(a.pts[:, k].min(), b.pts[:, k].min()) + 1e-4 for k in others)
                        self.assertFalse(overlap, f"back-to-back quads in plane {'xyz'[axis]}={pa:.3f} "
                                                  f"at steer {steer}")

    def test_the_transom_shades_the_cockpit_in_gl_lighting(self):
        from .landfx import _jon_boxes
        walls = [(c, h) for c, h in _jon_boxes(self.state())
                 if c[2] - h[2] <= HULL_STERN <= c[2] + h[2] and h[0] >= HULL_INNER_BEAM - 1e-4]
        self.assertEqual(len(walls), 1, "no occluder box spans the transom wall")
        (cx, cy, cz), (hx, hy, hz) = walls[0]
        self.assertLessEqual(cy - hy, COCKPIT_FLOOR + 1e-4)
        self.assertGreaterEqual(cy + hy, RAIL_TOP - 0.04)
        self.assertLessEqual(cz + hz, HULL_STERN + 1e-4, "the transom box intrudes into the cockpit")

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


TILLER_PAINT = (0.9, 0.1, 0.1)  # a paint no other part wears, so the arm's faces are easy to find
COWL_BAND = (-0.40, -0.08)  # the cowl's height in the eye frame, metres
# The bench's top and back, with room ahead of it for a seated Skipper's legs.
SEAT = ((-HULL_INNER_BEAM, HULL_INNER_BEAM), (-0.74, -0.10), (1.44, 1.84))


def _points(faces):
    """Every vertex of `faces` as one (n, 3) array."""
    return np.concatenate([f.pts for f in faces])


def _unit(v):
    return v / np.linalg.norm(v)


def _turn_about_pivot(points, steer):
    """Eye-frame `points` after the motor yaws by `steer` about its steering axis.

    Written from the motor's yaw rather than from `boatmesh._outboard_frame`, so the rigid-motion
    check does not reuse the code it tests. A positive yaw carries an aft point toward +x.
    """
    yaw = steer * OUTBOARD_YAW
    c, s = math.cos(yaw), math.sin(yaw)
    rel_x = points[:, 0] - OUTBOARD_PIVOT[0]
    rel_z = points[:, 2] - OUTBOARD_PIVOT[1]
    out = np.array(points, np.float64)
    out[:, 0] = OUTBOARD_PIVOT[0] + c * rel_x - s * rel_z
    out[:, 2] = OUTBOARD_PIVOT[1] + s * rel_x + c * rel_z
    return out


def _same_face(a, b):
    return (a.pts.shape == b.pts.shape and np.allclose(a.pts, b.pts) and np.allclose(a.normal, b.normal)
            and np.allclose(a.color, b.color))


def _cat_ahead(actor, distance, state):
    """A cat `distance` metres ahead of the Skipper's figure `actor`, in the lake `state` is on."""
    anchor = SimpleNamespace(x=actor.x + math.sin(actor.yaw) * distance, z=actor.z + math.cos(actor.yaw) * distance,
                             lake_id=getattr(state, "lake_id", None))
    return SimpleNamespace(anchor=anchor)


def _solid(faces):
    """The box a tiller part's built faces enclose, as (centre, axes, half sizes), metres.

    The axes are the faces' own normals (a bar's sides and caps, or a cube's faces), and the half sizes are
    the part's vertex extents along them. The box is read from the built geometry, so no size or corner
    factor is typed here.

    Args:
        faces: one tiller part's faces from boatmesh.tiller_parts.

    Returns:
        (centre, axes, half): the centre (3,), the orthonormal axes as columns (3, 3), and the half sizes (3,).

    Raises:
        ValueError: the faces' normals are not the axes of a box.
    """
    normals = []
    for face in faces:
        n = np.asarray(face.normal, np.float64)
        if not any(abs(n @ m) > 1 - 1e-6 for m in normals):
            normals.append(n)
    a, b = normals[0], normals[1]
    if abs(a @ b) > 1e-6:
        raise ValueError("the part's face normals are not the axes of a box")
    axes = np.stack([a, b, np.cross(a, b)], axis=1)
    local = _points(faces).astype(np.float64) @ axes
    low, high = local.min(axis=0), local.max(axis=0)
    return axes @ ((low + high) / 2), axes, (high - low) / 2


def _tiller_solids(steer):
    """The arm, knuckle, rod and grip boxes of the tiller at `steer` (see `_solid`)."""
    parts = tiller_parts(steer, TILLER_PAINT)
    return [_solid(parts[name]) for name in ("arm", "knuckle", "rod", "grip")]


def _reach(solid):
    """A bar's corner reach from its centre line, metres: the norm of its two short half sizes."""
    return float(np.linalg.norm(np.sort(solid[2])[:2]))


def _long_ends(solid):
    """The two end-face centres along a bar's long axis, (2, 3) metres."""
    centre, axes, half = solid
    i = int(np.argmax(half))
    return np.array([centre - axes[:, i] * half[i], centre + axes[:, i] * half[i]])


def _distance_to_solids(points, solids):
    """Distance from each row of `points` (n, 3) to the nearest solid, metres; zero inside one.

    Exact for oriented boxes: the outside part of a point's offset, measured on the box's own axes.
    """
    best = np.full(len(points), np.inf)
    for centre, axes, half in solids:
        local = (points - centre) @ axes
        best = np.minimum(best, np.linalg.norm(np.maximum(np.abs(local) - half, 0.0), axis=1))
    return best


def _settle(tris, solids, floor, upper):
    """Branch-and-bound over one time's triangles still under `floor`; returns (ok, value) as `_surface_clearance`.

    `upper` is the least vertex distance so far, an upper bound on the least clearance. An open triangle's
    radius is its largest centroid-to-vertex distance, and its bound is its centroid's distance minus that
    radius: every point of a triangle is a convex combination of its vertices, so lies within the radius of the
    centroid. (The circumradius would not do: it is measured from the circumcentre.) Splitting a triangle at its
    edge midpoints gives four copies similar to it at half scale, so their radii halve and their bounds tighten;
    the new vertices can lower `upper`. Stops when no bound is under `floor` (ok), when a vertex comes under
    `floor` (fail, with that distance), or when every open radius is within SURFACE_TOLERANCE while a bound is
    still under `floor` (fail, with the lowest such bound: the check cannot decide at that triangle size).
    """
    while True:
        centre = tris.mean(axis=1)
        radius = np.linalg.norm(tris - centre[:, None], axis=2).max(axis=1)
        bound = _distance_to_solids(centre, solids) - radius
        open_ = bound < floor
        if not open_.any():
            return True, floor
        tris, bound, radius = tris[open_], bound[open_], radius[open_]
        if radius.max() <= SURFACE_TOLERANCE:
            return False, float(bound.min())
        a, b, c = tris[:, 0], tris[:, 1], tris[:, 2]
        ab, bc, ca = (a + b) / 2, (b + c) / 2, (c + a) / 2
        tris = np.concatenate([np.stack(corner, axis=1)
                               for corner in ((a, ab, ca), (ab, b, bc), (ca, bc, c), (ab, bc, ca))])
        upper = min(upper, float(_distance_to_solids(tris.reshape(-1, 3), solids).min()))
        if upper < floor:
            return False, upper


def _surface_clearance(body, faces, solids, floor):
    """Whether the posed figure keeps `floor` metres from `solids` at every sweep time, certified over the surface.

    Args:
        body: (k, n, 3) float64 posed vertices in the eye frame, one row per sweep time.
        faces: (m, 3) triangle indices into the vertices, the same at every time.
        solids: the boxes from `_solid`.
        floor: the clearance to assert, metres.

    Returns:
        (ok, value): when ok, every surface point is at least `floor` from the solids and value is `floor`.
        Otherwise value bounds the failure: the least vertex distance at the first failing time (vertices lie on
        the surface), or the bound `_settle` could not tighten.

    Stage 1 bounds every triangle at once: its centroid's distance to the solids minus its radius (the largest
    centroid-to-vertex distance). That lower-bounds the triangle's clearance, since distance is 1-Lipschitz and
    every point of a triangle lies within that radius of the centroid. A time whose bounds all clear `floor` is
    done; the rest go to `_settle`, which refines only the triangles still under `floor`. Times are processed in
    chunks to bound the (k, m, 3, 3) corner array.
    """
    for start in range(0, len(body), 64):
        chunk = body[start:start + 64]
        tri = chunk[:, faces]
        centre = tri.mean(axis=2)
        radius = np.linalg.norm(tri - centre[:, :, None], axis=3).max(axis=2)
        bound = _distance_to_solids(centre.reshape(-1, 3), solids).reshape(centre.shape[:2]) - radius
        for k in range(len(chunk)):
            if bound[k].min() >= floor:
                continue
            upper = float(_distance_to_solids(tri[k].reshape(-1, 3), solids).min())
            if upper < floor:
                return False, upper
            ok, value = _settle(tri[k][bound[k] < floor], solids, floor, upper)
            if not ok:
                return False, value
    return True, floor


def _least_clearance(body, faces, solids, low, high, tolerance):
    """A certified lower bound on the least surface clearance, by bisecting the floor `_surface_clearance` asserts.

    Args:
        low: a floor the figure passes, metres.
        high: a floor it fails, metres.
        tolerance: the bracket width to stop at, metres.

    Returns:
        The largest floor certified in the bisection, metres: a lower bound on the least clearance. When every failure
        was a vertex under the floor, the least lies below this plus `tolerance`. A `_settle` refusal (a triangle it
        could not decide once its open radii were at most SURFACE_TOLERANCE) counts as a failure without proving a
        violation, so it can leave the bound further below the least.
    """
    while high - low > tolerance:
        mid = (low + high) / 2
        if _surface_clearance(body, faces, solids, mid)[0]:
            low = mid
        else:
            high = mid
    return low


def _sampled_least(body, faces, solids, spacing):
    """The least clearance over a dense barycentric sampling of each triangle at `body[0]`, metres.

    Each triangle is sampled on a barycentric grid of n = ceil(longest edge / spacing) divisions a side. Its
    sub-triangles have diameter longest edge / n, at most `spacing`, so every point of the triangle lies within that
    step of a sample. The sample minimum is therefore an upper bound on the least clearance, and the least clearance
    is at least the sample minimum minus `spacing`. Used to validate `_surface_clearance`.
    """
    best = np.inf
    for t in body[0][faces]:
        longest = max(float(np.linalg.norm(t[i] - t[j])) for i, j in ((0, 1), (1, 2), (2, 0)))
        n = math.ceil(longest / spacing)
        i, j = np.meshgrid(np.arange(n + 1), np.arange(n + 1), indexing="ij")
        keep = i + j <= n
        w = np.stack([(n - i[keep] - j[keep]) / n, i[keep] / n, j[keep] / n], axis=1)
        best = min(best, float(_distance_to_solids(w @ t, solids).min()))
    return best


class JonTiller(unittest.TestCase):
    """Issue #192: the tiller arm swings from the outboard's swivel and ends in a grip the paw holds."""

    @classmethod
    def setUpClass(cls):
        cls.world = World("briar")
        cls.renderer = SoftwareRenderer.__new__(SoftwareRenderer)

    def state(self, steer=0.0):
        state = State.new(self.world, seed=192)
        state.boat_id = "jon"
        state.steer = steer
        return state

    def parts(self, steer):
        return tiller_parts(steer, TILLER_PAINT)

    def test_the_arm_hangs_from_the_swivel_and_turns_rigidly_with_the_motor(self):
        rest = _points(self.parts(0.0)["arm"])
        cowl_rest = _points(outboard_faces(0.0, TILLER_PAINT)[6:12])  # the cowl, second of the parts
        for steer in STEERS:
            swivel, knuckle, _grip = tiller_joints(steer)
            with self.subTest(steer=steer):
                np.testing.assert_allclose([swivel[0], swivel[2]], OUTBOARD_PIVOT, atol=1e-6)
                self.assertLess(COWL_BAND[0], float(swivel[1]), "the swivel sits below the cowl")
                self.assertLess(float(swivel[1]), COWL_BAND[1], "the swivel sits above the cowl")
                self.assertTrue(0.55 <= float(np.linalg.norm(knuckle - swivel)) <= 0.65)
                arm = self.parts(steer)["arm"]
                np.testing.assert_allclose(_points(arm), _turn_about_pivot(rest, steer), atol=1e-5)
                np.testing.assert_allclose(_points(outboard_faces(steer, TILLER_PAINT)[6:12]),
                                           _turn_about_pivot(cowl_rest, steer), atol=1e-5)
                for face in arm:
                    np.testing.assert_allclose(face.color, TILLER_PAINT, atol=1e-6)
        # The motor's aft end swings to starboard at positive steer, so its forward tiller tip swings to port.
        self.assertLess(float(tiller_joints(1.0)[1][0]), -0.2)
        self.assertGreater(float(tiller_joints(-1.0)[1][0]), 0.2)

    def test_the_arm_root_sinks_into_the_cowl_so_it_meets_the_motor_without_a_gap(self):
        # The root is the arm's points at the lowest z, astern of the steering axis. The cowl's
        # front face lies at z -0.86, so the root must be inside the cowl box and at least 5 mm
        # behind that face to be hidden where the arm joins the motor.
        arm = _points(self.parts(0.0)["arm"])
        root = arm[arm[:, 2] <= arm[:, 2].min() + 1e-6]
        cowl = _points(outboard_faces(0.0, TILLER_PAINT)[6:12])
        lo, hi = cowl.min(axis=0), cowl.max(axis=0)
        self.assertTrue(np.all(root >= lo - 1e-5), "the arm root lies outside the cowl's box")
        self.assertTrue(np.all(root[:, :2] <= hi[:2] + 1e-5), "the arm root shows past the cowl's top or starboard")
        self.assertLessEqual(float(root[:, 2].max()), float(hi[2]) - 0.005,
                             "the arm root is not 5 mm inside the cowl's front face")

    def test_the_rod_hinges_on_the_arm_tip_without_a_gap_and_stays_straight(self):
        for steer in STEERS:
            swivel, knuckle, grip = tiller_joints(steer)
            arm = _points(self.parts(steer)["arm"])
            along_arm = (arm - swivel) @ _unit(knuckle - swivel)
            tip = arm[along_arm > along_arm.max() - 1e-4]
            parts = self.parts(steer)
            rod = _points(parts["rod"])
            axis = _unit(grip - knuckle)
            along = (rod - knuckle) @ axis
            root = rod[along < along.min() + 1e-4]
            with self.subTest(steer=steer):
                gap = float(np.linalg.norm(tip.mean(axis=0) - root.mean(axis=0)))
                self.assertLess(gap, 0.01, "the rod does not meet the arm's tip")
            with self.subTest(steer=steer, straight=True):
                # Each bar is a square section, so every vertex lies within its corner reach of the bar's centre
                # line. The rod runs from the knuckle to the sleeve and the grip from the sleeve to the grip, both
                # on the knuckle-grip line.
                for name in ("rod", "grip"):
                    pts = _points(parts[name])
                    along_pts = (pts - knuckle) @ axis
                    off = np.linalg.norm(pts - knuckle - along_pts[:, None] * axis, axis=1)
                    self.assertLess(float(off.max()), _reach(_solid(parts[name])) + 1e-6,
                                    f"the {name} is bent off its straight line")

    def test_the_paw_holds_the_grip_at_every_steer(self):
        for steer in STEERS:
            _swivel, knuckle, grip = tiller_joints(steer)
            pts = _points(self.parts(steer)["grip"])
            along = (pts - knuckle) @ _unit(grip - knuckle)
            far_end = pts[along > along.max() - 1e-4].mean(axis=0)
            pivot = skipper._tiller_pivot(SimpleNamespace(boat_id="jon", steer=steer))
            with self.subTest(steer=steer):
                self.assertLess(float(np.linalg.norm(pivot - far_end)), 0.02)

    def test_the_grip_is_on_screen_at_every_steer_and_the_near_plane_cuts_the_rod_off_screen(self):
        # The first-person view is the boat's own camera space at 74 degrees across and 16:9.
        camera = Camera(0.0, 1.22, 0.0, yaw=0.0, pitch=0.0, roll=0.0, fov_x=FOV, w=1280, h=720,
                        build_rays=False)
        tany = math.tan(FOV / 2) * 720 / 1280
        for steer in STEERS:
            grip = skipper._tiller_pivot(SimpleNamespace(boat_id="jon", steer=steer))
            sx, sy, depth = camera.cam_to_screen(grip[None])
            with self.subTest(steer=steer):
                self.assertGreater(float(depth[0]), 0.22)
                self.assertTrue(0.05 * 1280 <= float(sx[0]) <= 0.95 * 1280, f"grip at x={sx[0]:.0f}")
                self.assertTrue(0.05 * 720 <= float(sy[0]) <= 0.95 * 720, f"grip at y={sy[0]:.0f}")
            # The boat is clipped at the near plane (0.22 m), so the rod's cut must fall below the frame.
            _swivel, knuckle, grip = tiller_joints(steer)
            t = (0.22 - knuckle[2]) / (grip[2] - knuckle[2])
            cut = knuckle + t * (grip - knuckle)
            with self.subTest(steer=steer, near_plane=True):
                self.assertLess(float(cut[1]) / 0.22, -tany)

    def test_the_detached_forward_mount_is_gone_from_both_renderers(self):
        from .glrender import LakeRenderer
        from .landfx import _jon_boxes
        gl = LakeRenderer.__new__(LakeRenderer)
        for steer in STEERS:
            state = self.state(steer)
            for name, faces in (("software", self.renderer._boat_faces(state)), ("gl", gl._detailed_boat(state))):
                centres = np.array([f.pts.mean(axis=0) for f in faces])
                in_band = ((centres[:, 0] >= 0.2) & (centres[:, 0] <= 0.42)
                           & (centres[:, 2] >= 1.52) & (centres[:, 2] <= 1.72))
                with self.subTest(steer=steer, renderer=name):
                    self.assertFalse(in_band.any(), centres[in_band][:3])
        for centre, _half in _jon_boxes(self.state()):
            with self.subTest(centre=centre):
                self.assertFalse(0.2 <= centre[0] <= 0.42 and 1.52 <= centre[2] <= 1.72,
                                 "an occluder box sits where the mount was")

    def test_software_and_gl_draw_the_same_tiller(self):
        from .glrender import LakeRenderer
        gl = LakeRenderer.__new__(LakeRenderer)
        state = self.state(0.6)
        motor = np.asarray(paint_rgb("motor", state.look_paint["motor"]), np.float32)
        drawn = {"software": self.renderer._boat_faces(state), "gl": gl._detailed_boat(state)}
        for face in tiller_faces(0.6, motor):
            for name, faces in drawn.items():
                with self.subTest(renderer=name):
                    self.assertTrue(any(_same_face(face, other) for other in faces), "a tiller face is missing")

    def test_the_tiller_keeps_clear_of_the_sitting_space_and_the_cockpit_occluders(self):
        from .landfx import _jon_boxes
        for steer in STEERS:
            parts = self.parts(steer)
            pts = np.concatenate([_points(parts[name]) for name in ("arm", "knuckle", "rod", "grip")])
            (x0, x1), (y0, y1), (z0, z1) = SEAT
            seat = ((pts[:, 0] >= x0) & (pts[:, 0] <= x1) & (pts[:, 1] >= y0) & (pts[:, 1] <= y1)
                    & (pts[:, 2] >= z0) & (pts[:, 2] <= z1))
            with self.subTest(steer=steer):
                self.assertFalse(seat.any(), "the tiller reaches into the bench's sitting space")
                # The last two boxes wrap the motor itself, which the arm joins, so they are not checked.
                for centre, half in _jon_boxes(self.state(steer))[:-2]:
                    inside = np.all(np.abs(pts - centre) <= half, axis=1)
                    self.assertFalse(inside.any(), f"the tiller passes through the occluder at {centre}")

    def test_the_jon_figure_rides_the_grip_and_the_other_figures_keep_the_helm_on_the_centreline(self):
        # The jon's figure takes the tiller pose and stands JON_TILLER_X/Z from the eye at steer 0, plus the grip's
        # movement with steer (skipperview.SkipperFigure.place). Every other boat keeps the helm pose on the centreline.
        from .boatmesh import tiller_grip
        from .skipperview import JON_TILLER_X, JON_TILLER_Z, SkipperFigure, _floor_offset
        camera = Camera(0.0, 1.22, 0.0, yaw=0.0, pitch=0.0, roll=0.0, fov_x=FOV, w=1280, h=720, build_rays=False)
        for steer in STEERS:
            for boat_id in ("jon", "rowboat", "sail", "pontoon"):
                state = self.state(steer)
                state.boat_id = boat_id
                actor = SkipperFigure().place(state, camera)
                base = camera.eye_to_world(np.array([0.0, _floor_offset(state), 0.0], np.float32)).astype(np.float64)
                offset = np.array([actor.x, actor.y, actor.z]) - base
                jon = boat_id == "jon"
                ride = tiller_grip(steer) - tiller_grip(0.0) if jon else np.zeros(3)
                with self.subTest(boat=boat_id, steer=steer):
                    self.assertAlmostEqual(float(offset @ camera.right),
                                           (JON_TILLER_X if jon else 0.0) + float(ride[0]), places=5)
                    self.assertAlmostEqual(float(offset @ camera.forward),
                                           (JON_TILLER_Z if jon else 0.0) + float(ride[2]), places=5)
                    self.assertAlmostEqual(float(offset[1]), 0.0, places=5)
                    self.assertEqual(actor.look["pose"], "tiller" if jon else "helm")

    def posed(self, steer, cat_distance=None, sweep=WAVE_SWEEP):
        """The Skipper's rig at the jon's helm over `sweep`, placed as the game places it, default look only.

        A cat `cat_distance` metres ahead, at speed 0, turns on the wave gesture (blend 1 within 14 m, 0 beyond
        20 m); None leaves the figure on the tiller pose with no cat near. Other looks change the silhouette (ears,
        tail, coat, attire) and are not swept here, so the claims below cover the default look only.

        Returns:
            A `Posed` (see the module constants).
        """
        from . import actors, catmesh
        from .skipperview import SkipperFigure, _floor_offset
        camera = Camera(0.0, 1.22, 0.0, yaw=0.0, pitch=0.0, roll=0.0, fov_x=FOV, w=1280, h=720, build_rays=False)
        state = self.state(steer)
        figure = SkipperFigure()
        actor = figure.place(state, camera)
        if cat_distance is not None:
            state.npcs = (_cat_ahead(actor, cat_distance, state),)
        floor = _floor_offset(state)
        base = camera.eye_to_world(np.array([0.0, floor, 0.0], np.float32)).astype(np.float64)
        offset = np.array([actor.x, actor.y, actor.z]) - base
        shift = np.array([float(offset @ camera.right), floor, float(offset @ camera.forward)])
        mesh = actor.mesh(catmesh.LOD0)
        body, forearm, blend = [], [], []
        for t in sweep:
            state.anim = float(t)
            params = figure.params(state, False)
            pos, _normals = actors.animate(mesh, params)
            body.append(pos.astype(np.float64) + shift)
            forearm.append(params["forearm"])
            blend.append(params["blend"])
        faces = mesh.triangles.astype(np.int64)
        part = mesh.part[faces]
        grip_paw = np.all(part == catmesh.PAW, axis=1)
        if np.any(np.any(part == catmesh.PAW, axis=1) & ~grip_paw):
            raise AssertionError("a triangle joins the grip paw to another part")
        wave = np.all(part == catmesh.PAW_WAVE, axis=1)
        return Posed(np.array(body), faces, np.array(forearm), np.array(blend),
                     faces[grip_paw], faces[wave], faces[~grip_paw])

    def hull_breaches(self, p, steer):
        """The hull, bench and rest-of-figure limits the posed figure breaks at `steer`: messages, none if it keeps them.

        The vertex bounds are exact for these planar limits: WALL_MARGIN inside the hull's inner walls, 0.2 m clear of
        the transom, BENCH_CLEARANCE short of the bench, and on or above the floor. Every triangle except the grip
        paw's keeps TILLER_CLEARANCE from every tiller solid (`_surface_clearance`, which covers the surface between
        vertices).
        """
        from .skipperview import _floor_offset
        floor = _floor_offset(self.state(steer))
        flat = p.body.reshape(-1, 3)
        out = []
        if flat[:, 0].min() < -HULL_INNER_BEAM + WALL_MARGIN:
            out.append("the figure's port side meets the hull wall")
        if flat[:, 0].max() > HULL_INNER_BEAM - WALL_MARGIN:
            out.append("the figure's starboard side meets the hull wall")
        if flat[:, 2].min() < HULL_STERN + 0.2:
            out.append("the figure reaches the transom")
        if flat[:, 2].max() > SEAT[2][0] - BENCH_CLEARANCE:
            out.append(f"the figure reaches the bench (z {float(flat[:, 2].max()):.3f} m)")
        if flat[:, 1].min() < floor:
            out.append("the figure sinks below the floor")
        ok, value = _surface_clearance(p.body, p.rest, _tiller_solids(steer), TILLER_CLEARANCE)
        if not ok:
            out.append(f"the figure's rest is {value * 100:.2f} cm from the tiller, under {TILLER_CLEARANCE * 100:.0f} cm")
        return out

    def paw_breaches(self, p, steer):
        """The grip paw's breaches at `steer`: messages, none if it keeps them.

        Its vertices come within PAW_CONTACT of the grip solid. Each vertex lies on the surface, so the surface reaches
        within PAW_CONTACT of the grip too. Its surface stays PAW_FLOOR outside the grip (certified by
        `_surface_clearance`, so the mitt does not pass through the grip) and TILLER_CLEARANCE from the arm, knuckle
        and rod.
        """
        arm, knuckle, rod, grip = _tiller_solids(steer)
        out = []
        vertices = np.unique(p.paw)
        contact = float(_distance_to_solids(p.body[:, vertices].reshape(-1, 3), [grip]).min())
        if contact > PAW_CONTACT:
            out.append(f"the grip paw is {contact * 100:.2f} cm from the grip, over {PAW_CONTACT * 100:.0f} cm")
        ok, value = _surface_clearance(p.body, p.paw, [grip], PAW_FLOOR)
        if not ok:
            out.append(f"the grip paw's surface comes within {PAW_FLOOR * 1000:.0f} mm of the grip "
                       f"(bound {value * 1000:.2f} mm)")
        ok, value = _surface_clearance(p.body, p.paw, [arm, knuckle, rod], TILLER_CLEARANCE)
        if not ok:
            out.append(f"the grip paw is not {TILLER_CLEARANCE * 100:.0f} cm clear of the arm and rod "
                       f"(bound {value * 100:.2f} cm)")
        return out

    def check_figure(self, p, steer, pose):
        """The figure keeps every hull, bench, rest and grip limit at `steer` for the pose named (default look only)."""
        with self.subTest(steer=steer, pose=pose):
            self.assertEqual(self.hull_breaches(p, steer) + self.paw_breaches(p, steer), [])

    def test_the_tiller_figure_stays_in_the_cockpit_and_holds_the_grip_at_every_steer(self):
        # No cat near: the tiller pose at blend 0 over the whole sweep, default look.
        for steer in STEERS:
            p = self.posed(steer)
            with self.subTest(steer=steer):
                self.assertEqual(float(p.blend.max()), 0.0, "a figure with no cat near is on the wave gesture")
            self.check_figure(p, steer, "tiller")

    def test_the_waving_figure_stays_in_the_cockpit_and_holds_the_grip_at_every_steer(self):
        # A cat 5 m ahead at speed 0 turns on the tiller_wave gesture at blend 1, and the waving forearm reaches both
        # extremes. Default look only.
        for steer in STEERS:
            p = self.posed(steer, cat_distance=5.0)
            with self.subTest(steer=steer, pose="wave"):
                self.assertEqual(float(p.blend.min()), 1.0, "the wave gesture is not fully on")
                self.assertAlmostEqual(float(p.forearm.max()), WAVE_FOREARM, places=6)
                self.assertAlmostEqual(float(p.forearm.min()), -WAVE_FOREARM, places=6)
            self.check_figure(p, steer, "wave")

    def test_the_figure_stays_in_the_cockpit_and_holds_the_grip_across_the_blend(self):
        # Cats 15, 17 and 19 m ahead put the blend strictly between tiller and wave, at every steer. Default look only.
        for steer in STEERS:
            for distance in MID_BLEND_M[::4]:
                p = self.posed(steer, cat_distance=float(distance))
                with self.subTest(steer=steer, distance=float(distance)):
                    self.assertTrue(0.0 < float(p.blend.min()) and float(p.blend.max()) < 1.0,
                                    "the blend is not mid-way between tiller and wave")
                self.check_figure(p, steer, f"{float(distance):g} m")

    def test_the_waving_paw_sweeps_while_the_grip_paw_stays_on_the_grip(self):
        # Full wave: the waving paw's centre travels on the forearm's arc (radius about 0.14 m, +-0.45 rad: a chord
        # of about 0.12 m, required 0.10 m), while the grip paw's centre stays within 1 cm (its only motion is the idle
        # rise, which the contact check allows for).
        for steer in (0.0, 1.0):
            p = self.posed(steer, cat_distance=5.0)
            wave_centre = p.body[:, np.unique(p.wave)].mean(axis=1)
            grip_centre = p.body[:, np.unique(p.paw)].mean(axis=1)
            with self.subTest(steer=steer):
                self.assertGreater(float(np.linalg.norm(wave_centre.max(axis=0) - wave_centre.min(axis=0))), 0.10)
                self.assertLess(float(np.linalg.norm(grip_centre.max(axis=0) - grip_centre.min(axis=0))), 0.01)

    def test_the_jon_takes_no_steer_swing_at_any_blend_and_the_other_boats_keep_theirs(self):
        # The wheel turns the arm 0.55 rad per unit steer on the helm pose (actors.pose_state). The jon's tiller pose
        # has no wheel, so its arm stays put at every steer and blend: the figure rides the grip instead. The other
        # boats keep the full swing at every blend.
        from .skipperview import SkipperFigure
        camera = Camera(0.0, 1.22, 0.0, yaw=0.0, pitch=0.0, roll=0.0, fov_x=FOV, w=1280, h=720, build_rays=False)
        for distance in (None, 5.0, *MID_BLEND_M[::4]):
            for boat_id in ("jon", "rowboat", "sail", "pontoon"):
                swing_at = {}
                for steer in (0.0, 1.0):
                    state = self.state(steer)
                    state.boat_id = boat_id
                    figure = SkipperFigure()
                    actor = figure.place(state, camera)
                    if distance is not None:
                        state.npcs = (_cat_ahead(actor, float(distance), state),)
                    values, blends = [], []
                    for t in WAVE_SWEEP[::11]:
                        state.anim = float(t)
                        params = figure.params(state, False)
                        values.append(params["arm"])
                        blends.append(params["blend"])
                    swing_at[steer] = (np.array(values), np.array(blends))
                swing = swing_at[1.0][0] - swing_at[0.0][0]
                blend = swing_at[1.0][1]
                law = np.zeros_like(blend) if boat_id == "jon" else np.full_like(blend, 0.55)
                with self.subTest(boat=boat_id, distance=None if distance is None else float(distance)):
                    np.testing.assert_allclose(swing, law, atol=1e-9)

    def test_the_rig_arm_channel_ignores_steer_at_both_blends(self):
        # The tiller pose has no steer term, so the rig's arm channel (catmesh.RIG_ARM: both upper arms and the left
        # forearm and paw) is the same at every steer, at blend 0 (no cat) and at blend 1 (a cat 5 m ahead), at t = 4.2 s.
        # Idle motion still moves it over time, so only the steer is compared. Default look only.
        from . import actors, catmesh
        from .skipperview import SkipperFigure
        camera = Camera(0.0, 1.22, 0.0, yaw=0.0, pitch=0.0, roll=0.0, fov_x=FOV, w=1280, h=720, build_rays=False)

        def arm_channel(steer, cat_distance, t):
            state = self.state(steer)
            figure = SkipperFigure()
            actor = figure.place(state, camera)
            if cat_distance is not None:
                state.npcs = (_cat_ahead(actor, cat_distance, state),)
            state.anim = t
            params = figure.params(state, False)
            mesh = actor.mesh(catmesh.LOD0)
            channel = np.rint(mesh.rig - catmesh.RIG_STRIDE * np.floor((mesh.rig + 0.5) / catmesh.RIG_STRIDE))
            arm = channel == catmesh.RIG_ARM
            pos, _normals = actors.animate(mesh, params)
            return pos[arm], arm, mesh, float(params["blend"])

        _pos, arm, mesh, blend = arm_channel(1.0, 5.0, 4.2)
        self.assertEqual(blend, 1.0)
        self.assertTrue(np.any(arm & (mesh.part == catmesh.PAW)), "the grip paw is not on the arm channel")
        for cat_distance in (None, 5.0):
            rest = arm_channel(0.0, cat_distance, 4.2)[0]
            for steer in STEERS:
                with self.subTest(steer=steer, cat_distance=cat_distance):
                    np.testing.assert_allclose(arm_channel(steer, cat_distance, 4.2)[0], rest, atol=1e-6)

    def test_the_sweep_grid_resolves_the_least_rest_clearance(self):
        # The rest's least clearance from the tiller was measured once, at 2.91 cm: steer 0, no cat (blend 0). This test
        # measures that pose only; no other steer or blend is asserted to that figure. The 0.1 s sweep's certified least
        # must agree with a 0.02 s sweep's to within 1 mm, since a dip between samples could hide. Each certificate sits
        # at most `tolerance` below its least when its failures were vertex violations (see _least_clearance).
        fine = np.union1d(np.arange(0.0, 22.0, 0.02),
                          np.concatenate([np.arange(33) + 0.25, np.arange(33) + 0.75]) / 1.5)
        fine = fine[fine < 22.0]
        solids = _tiller_solids(0.0)
        coarse_p = self.posed(0.0)
        fine_p = self.posed(0.0, sweep=fine)
        coarse = _least_clearance(coarse_p.body, coarse_p.rest, solids, 0.015, 0.035, 0.0002)
        fine_least = _least_clearance(fine_p.body, fine_p.rest, solids, 0.015, 0.035, 0.0002)
        self.assertGreater(coarse, 0.015)
        self.assertLess(abs(coarse - fine_least), 0.001)

    def test_a_figure_frozen_at_steer_zero_loses_the_grip_when_the_tiller_steers(self):
        # Mutant: placement ignores steer, so the figure never rides the grip. The paw's contact must break.
        from unittest import mock
        from . import boatmesh, skipperview
        frozen = SimpleNamespace(tiller_grip=lambda steer: boatmesh.tiller_grip(0.0))
        with mock.patch.object(skipperview, "boatmesh", frozen):
            for steer in (-1.0, 1.0):
                p = self.posed(steer, sweep=WAVE_SWEEP[::20])
                self.assertTrue(self.paw_breaches(p, steer), f"the frozen figure held the grip at steer {steer}")

    def test_a_wrong_steer_sign_moves_the_figure_off_the_grip(self):
        # Mutant: the figure rides the grip's movement mirrored about steer 0. The paw's contact must break.
        from unittest import mock
        from . import boatmesh, skipperview
        mirrored = SimpleNamespace(tiller_grip=lambda steer: 2 * boatmesh.tiller_grip(0.0) - boatmesh.tiller_grip(steer))
        with mock.patch.object(skipperview, "boatmesh", mirrored):
            for steer in (-1.0, 1.0):
                p = self.posed(steer, sweep=WAVE_SWEEP[::20])
                self.assertTrue(self.paw_breaches(p, steer), f"the mirrored figure held the grip at steer {steer}")

    def test_without_the_tiller_pose_the_grip_paw_misses_the_grip(self):
        # Mutant: the Skipper keeps the helm pose, so its left paw stays at the wheel and never reaches the grip.
        from unittest import mock
        from . import skipperlook, skipperview
        helm_only = SimpleNamespace(saved=skipperlook.saved,
                                    appearance=lambda look, pose: skipperlook.appearance(look, "helm"))
        with mock.patch.object(skipperview, "skipperlook", helm_only):
            p = self.posed(0.0, sweep=WAVE_SWEEP[::20])
        self.assertTrue(self.paw_breaches(p, 0.0), "the helm pose's paw met the grip")

    def test_a_wave_pose_that_moves_the_grip_arm_loses_the_grip(self):
        # Mutant: the tiller wave takes the helm_wave's left arm, so the wave displaces the grip hand.
        from unittest import mock
        from . import catmesh
        moved = dict(catmesh.POSE_JOINTS["tiller_wave"])
        moved.update(elbow_l=catmesh.POSE_JOINTS["helm_wave"]["elbow_l"],
                     wrist_l=catmesh.POSE_JOINTS["helm_wave"]["wrist_l"])
        try:
            with mock.patch.dict(catmesh.POSE_JOINTS, {"tiller_wave": moved}):
                catmesh.clear_caches()
                p = self.posed(0.0, cat_distance=5.0, sweep=WAVE_SWEEP[::20])
        finally:
            catmesh.clear_caches()
        self.assertTrue(self.paw_breaches(p, 0.0), "the waving pose kept the grip paw on the grip")

    def test_a_figure_placed_across_the_hull_puts_the_grip_paw_through_the_wall(self):
        # Mutant: the figure is set 0.45 m to starboard, so the grip paw leaves the hull.
        from unittest import mock
        from . import skipperview
        with mock.patch.object(skipperview, "JON_TILLER_X", 0.45):
            p = self.posed(0.0, sweep=WAVE_SWEEP[::20])
        self.assertGreater(float(p.body[:, np.unique(p.paw), 0].max()), HULL_INNER_BEAM - WALL_MARGIN,
                           "the grip paw stayed inside the hull")

    def test_the_surface_clearance_agrees_with_dense_sampling_on_random_boxes(self):
        # Checks the bound machinery away from the figure: the exact box distance, then random triangles against two
        # random boxes. Sampling at SPACING bounds the least clearance to within SPACING, and MARGIN is well over
        # SPACING, so a floor MARGIN under the sampled least must pass.
        spacing, margin = 0.0005, 0.002
        unit = [(np.zeros(3), np.eye(3), np.full(3, 0.01))]
        np.testing.assert_allclose(_distance_to_solids(np.array([[0.05, 0.0, 0.0], [0.03, 0.03, 0.0]]), unit),
                                   [0.04, math.hypot(0.02, 0.02)], atol=1e-12)
        rng = np.random.default_rng(192)
        for trial in range(100):
            solids = []
            for _ in range(2):
                q, _r = np.linalg.qr(rng.normal(size=(3, 3)))
                solids.append((rng.normal(scale=0.03, size=3), q, rng.uniform(0.005, 0.02, size=3)))
            body = rng.normal(scale=0.04, size=(6, 3, 3)).reshape(1, -1, 3)
            faces = np.arange(18).reshape(6, 3)
            least = _sampled_least(body, faces, solids, spacing)
            with self.subTest(trial=trial):
                # _surface_clearance may refuse a lower floor when _settle reaches SURFACE_TOLERANCE.
                if least > margin:
                    self.assertTrue(_surface_clearance(body, faces, solids, least - margin)[0],
                                    "a floor under the sampled least was refused")
                # The sampled least upper-bounds the true least, so a floor above it must never be certified.
                self.assertFalse(_surface_clearance(body, faces, solids, least + 1e-9)[0],
                                 "a floor over the sampled least was certified")

    def test_the_tiller_solids_are_the_built_bars_at_their_declared_sizes(self):
        # The solids come from the built faces, so these pin each bar to its declared size and each end to its joint:
        # the arm meets the knuckle, the rod runs from the knuckle to the sleeve, and the grip from the sleeve to the grip.
        declared = {"arm": TILLER_ARM_HALF, "knuckle": TILLER_KNUCKLE_HALF, "rod": TILLER_ROD_HALF,
                    "grip": TILLER_GRIP_HALF}
        for steer in STEERS:
            parts = self.parts(steer)
            _swivel, knuckle, grip = tiller_joints(steer)
            sleeve = grip - _unit(grip - knuckle) * TILLER_GRIP_LENGTH
            solids = {name: _solid(parts[name]) for name in declared}
            for name, side in declared.items():
                with self.subTest(steer=steer, part=name):
                    np.testing.assert_allclose(np.sort(solids[name][2])[:2], side, atol=1e-6)

            def meets(name, point):
                return float(np.min(np.linalg.norm(_long_ends(solids[name]) - point, axis=1))) < 1e-5

            with self.subTest(steer=steer, joint="arm to knuckle"):
                self.assertTrue(meets("arm", knuckle))
            with self.subTest(steer=steer, joint="rod"):
                self.assertTrue(meets("rod", knuckle) and meets("rod", sleeve))
                self.assertAlmostEqual(float(np.max(solids["rod"][2])),
                                       float(np.linalg.norm(sleeve - knuckle)) / 2, places=6)
            with self.subTest(steer=steer, joint="grip"):
                self.assertTrue(meets("grip", sleeve) and meets("grip", grip))
                self.assertAlmostEqual(float(np.max(solids["grip"][2])), TILLER_GRIP_LENGTH / 2, places=6)

    def test_the_outboard_clamp_and_the_tiller_knuckle_share_one_steel(self):
        from .boatmesh import _STEEL
        clamp = outboard_faces(0.0, TILLER_PAINT)[0]
        knuckle = self.parts(0.0)["knuckle"][0]
        np.testing.assert_allclose(clamp.color, _STEEL, atol=1e-6)
        np.testing.assert_allclose(knuckle.color, _STEEL, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
