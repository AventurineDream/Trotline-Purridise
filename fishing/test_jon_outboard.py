"""The starter jon boat has a closed transom and a tiller outboard on it (issue #160).

The tiller arm, knuckle and extension (issue #192) hang from the outboard's swivel and end at
the grip the Skipper's paw holds. Both renderers draw them from `boatmesh.tiller_faces`.

The jon's cockpit faces come from `SoftwareRenderer._boat_faces`; the GL renderer draws
them too, adding its own jon detail in `LakeRenderer._detailed_boat`. Collision uses
`boat.footprint`, and GL boat lighting uses `landfx._jon_boxes`; each must agree with
the outboard as drawn.
"""

import math
import unittest
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
# The Skipper's figure is swept over 22 s, two periods of the helm sway (catmotion._helm: 11 s and 4.3 s),
# at 0.1 s steps. The wave forearm swings at 1.5 Hz, too quick for that grid, so its exact peaks are added:
# sin(2 pi 1.5 t) is +1 at t = (k + 1/4) / 1.5 and -1 at t = (k + 3/4) / 1.5.
WAVE_SWEEP = np.union1d(np.arange(0.0, 22.0, 0.1),
                        np.concatenate([np.arange(33) + 0.25, np.arange(33) + 0.75]) / 1.5)
WAVE_SWEEP = WAVE_SWEEP[WAVE_SWEEP < 22.0]
WAVE_FOREARM = 0.45  # radians: catmotion.wave's amplitude
# Asserted limits, metres, vertex-based (see _clearances). WALL_MARGIN: the figure's least distance to an
# inner wall, measured 3.4 cm at full wave (4.1 cm at the helm). TILLER_CLEARANCE: the tiller's least,
# measured 2.4 cm, the extension at steer +1 mid-blend. The figure's lowest vertex is 3.5 mm above the floor.
WALL_MARGIN = 0.03
TILLER_CLEARANCE = 0.02


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
        # drawn, and over every tiller part (arm, knuckle, extension) at every steer, because the
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


def _segment_distance(points, a, b):
    """Distance from each row of `points` (n, 3) to the segment from `a` to `b`, metres."""
    d = b - a
    t = np.clip((points - a) @ d / (d @ d), 0.0, 1.0)
    return np.linalg.norm(points - (a + t[:, None] * d), axis=1)


def _clearances(body, steer):
    """Each tiller part's clearance from the figure's vertices `body` (n, 3), metres, at `steer`.

    Vertex-based: the figure's mesh vertices stand in for its skin, so this estimates the surface
    clearance rather than measuring a face distance. Each part is measured from its centre line, less its
    section's corner reach (half side * sqrt 2 for the square arm and extension, sqrt 3 for the knuckle box),
    so it clears the solid rather than only its axis.

    Returns:
        {part: (n,) array} for the arm, knuckle, extension and grip sleeve.
    """
    swivel, knuckle, grip = (np.asarray(v, np.float64) for v in tiller_joints(steer))
    sleeve = grip - _unit(grip - knuckle) * TILLER_GRIP_LENGTH
    return {
        "arm": _segment_distance(body, swivel, knuckle) - TILLER_ARM_HALF * math.sqrt(2),
        "knuckle": np.linalg.norm(body - knuckle, axis=1) - TILLER_KNUCKLE_HALF * math.sqrt(3),
        "extension": _segment_distance(body, knuckle, sleeve) - TILLER_ROD_HALF * math.sqrt(2),
        "grip": _segment_distance(body, sleeve, grip) - TILLER_GRIP_HALF * math.sqrt(2),
    }


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

    def test_the_extension_hinges_on_the_arm_tip_without_a_gap_and_stays_straight(self):
        for steer in STEERS:
            swivel, knuckle, grip = tiller_joints(steer)
            arm = _points(self.parts(steer)["arm"])
            along_arm = (arm - swivel) @ _unit(knuckle - swivel)
            tip = arm[along_arm > along_arm.max() - 1e-4]
            rod = _points(self.parts(steer)["extension"])
            axis = _unit(grip - knuckle)
            along = (rod - knuckle) @ axis
            root = rod[along < along.min() + 1e-4]
            with self.subTest(steer=steer):
                gap = float(np.linalg.norm(tip.mean(axis=0) - root.mean(axis=0)))
                self.assertLess(gap, 0.01, "the extension does not meet the arm's tip")
            with self.subTest(steer=steer, straight=True):
                # Each bar is a square section whose corners lie h * sqrt(2) from its centre line.
                # The rod is the bar from the knuckle to the sleeve, and the grip sleeve the bar from
                # the sleeve to the grip. The joint ring belongs to both, so it gets the looser bound.
                # Its own subtest: a tilted rod also shifts the root ring that the gap check selects.
                sleeve_start = float(np.linalg.norm(grip - knuckle)) - TILLER_GRIP_LENGTH
                off = np.linalg.norm(rod - knuckle - along[:, None] * axis, axis=1)
                rod_only = along < sleeve_start - 1e-3
                self.assertLess(float(off[rod_only].max()), TILLER_ROD_HALF * math.sqrt(2) + 1e-6,
                                "the rod is bent off its straight line")
                self.assertLess(float(off[~rod_only].max()), TILLER_GRIP_HALF * math.sqrt(2) + 1e-6,
                                "the grip sleeve is bent off its straight line")

    def test_the_paw_holds_the_extensions_grip_at_every_steer(self):
        for steer in STEERS:
            _swivel, knuckle, grip = tiller_joints(steer)
            rod = _points(self.parts(steer)["extension"])
            along = (rod - knuckle) @ _unit(grip - knuckle)
            far_end = rod[along > along.max() - 1e-4].mean(axis=0)
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
            pts = np.concatenate([_points(parts[name]) for name in ("arm", "knuckle", "extension")])
            (x0, x1), (y0, y1), (z0, z1) = SEAT
            seat = ((pts[:, 0] >= x0) & (pts[:, 0] <= x1) & (pts[:, 1] >= y0) & (pts[:, 1] <= y1)
                    & (pts[:, 2] >= z0) & (pts[:, 2] <= z1))
            with self.subTest(steer=steer):
                self.assertFalse(seat.any(), "the tiller reaches into the bench's sitting space")
                # The last two boxes wrap the motor itself, which the arm joins, so they are not checked.
                for centre, half in _jon_boxes(self.state(steer))[:-2]:
                    inside = np.all(np.abs(pts - centre) <= half, axis=1)
                    self.assertFalse(inside.any(), f"the tiller passes through the occluder at {centre}")

    def test_the_helm_figure_stands_to_port_for_the_jon_and_on_the_centreline_elsewhere(self):
        # Only the jon's helm figure moves off the centreline (skipperview.JON_HELM_X); every other
        # boat's stays on it. Offsets are measured in the boat camera's own axes.
        from .skipperview import JON_HELM_X, SkipperFigure, _floor_offset
        camera = Camera(0.0, 1.22, 0.0, yaw=0.0, pitch=0.0, roll=0.0, fov_x=FOV, w=1280, h=720, build_rays=False)
        for boat_id, expect in (("jon", JON_HELM_X), ("rowboat", 0.0), ("sail", 0.0), ("pontoon", 0.0)):
            state = self.state(0.0)
            state.boat_id = boat_id
            actor = SkipperFigure().place(state, camera)
            base = camera.eye_to_world(np.array([0.0, _floor_offset(state), 0.0], np.float32)).astype(np.float64)
            offset = np.array([actor.x, actor.y, actor.z]) - base
            with self.subTest(boat=boat_id):
                self.assertAlmostEqual(float(offset @ camera.right), expect, places=5)
                self.assertAlmostEqual(float(offset @ camera.forward), 0.0, places=5)
                self.assertAlmostEqual(float(offset[1]), 0.0, places=5)

    def posed(self, steer, cat_distance=None):
        """The Skipper's rig at the jon's helm over WAVE_SWEEP, placed as the game places it.

        A cat `cat_distance` metres ahead, at speed 0, turns on the wave gesture (blend 1 within 14 m);
        None leaves the figure on the helm pose with no cat near.

        Returns:
            (body, forearm, blend): the posed vertices in the eye frame, (n, 3) float64 metres, and the
            forearm angle (radians) and gesture blend (0-1) at each sweep time.
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
        ox = float((np.array([actor.x, actor.y, actor.z]) - base) @ camera.right)
        mesh = actor.mesh(catmesh.LOD0)
        body, forearm, blend = [], [], []
        for t in WAVE_SWEEP:
            state.anim = float(t)
            params = figure.params(state, False)
            pos, _normals = actors.animate(mesh, params)
            body.append(pos.astype(np.float64) + np.array([ox, floor, 0.0]))
            forearm.append(params["forearm"])
            blend.append(params["blend"])
        return np.concatenate(body), np.array(forearm), np.array(blend)

    def check_figure(self, body, steer, pose):
        """The posed figure stays WALL_MARGIN inside the hull's inner walls, off the transom and the bench,
        on or above the floor, and TILLER_CLEARANCE from every tiller part (see _clearances)."""
        from .skipperview import _floor_offset
        floor = _floor_offset(self.state(steer))
        with self.subTest(steer=steer, pose=pose):
            self.assertGreaterEqual(float(body[:, 0].min()), -HULL_INNER_BEAM + WALL_MARGIN,
                                    "the figure's port side meets the hull wall")
            self.assertLessEqual(float(body[:, 0].max()), HULL_INNER_BEAM - WALL_MARGIN,
                                 "the figure's starboard side meets the hull wall")
            self.assertGreaterEqual(float(body[:, 2].min()), HULL_STERN + 0.2, "the figure reaches the transom")
            self.assertLessEqual(float(body[:, 2].max()), SEAT[2][0] - 0.5, "the figure reaches the bench")
            self.assertGreaterEqual(float(body[:, 1].min()), floor, "the figure sinks below the floor")
        for part, distance in _clearances(body, steer).items():
            with self.subTest(steer=steer, pose=pose, part=part):
                self.assertGreaterEqual(float(distance.min()), TILLER_CLEARANCE,
                                        f"the figure comes within {TILLER_CLEARANCE} m of the tiller's {part}")

    def test_the_helm_figure_stays_in_the_cockpit_and_clear_of_the_tiller_at_every_steer(self):
        # No cat near: the helm pose. The figure keeps inside the hull, off the transom and the bench,
        # on or above the floor, and clear of every tiller part, at every steer and sweep time.
        for steer in STEERS:
            body, _forearm, blend = self.posed(steer)
            with self.subTest(steer=steer):
                self.assertEqual(float(blend.max()), 0.0, "a figure with no cat near is on the wave gesture")
            self.check_figure(body, steer, "helm")

    def test_the_waving_helm_figure_keeps_its_wrist_inside_the_port_wall_at_every_steer(self):
        # A cat 5 m ahead at speed 0 activates the real helm_wave gesture (blend 1), and the forearm reaches
        # both extremes. Cats at 16 m and 17 m give blends near 0.8 and 0.5, where the helm and wave poses
        # are mid-blend and the steer swing is partly on.
        for steer in STEERS:
            body, forearm, blend = self.posed(steer, cat_distance=5.0)
            with self.subTest(steer=steer, pose="wave"):
                self.assertEqual(float(blend.min()), 1.0, "the wave gesture is not fully on")
                self.assertAlmostEqual(float(forearm.max()), WAVE_FOREARM, places=6)
                self.assertAlmostEqual(float(forearm.min()), -WAVE_FOREARM, places=6)
            self.check_figure(body, steer, "wave")
        for steer in (-1.0, 0.0, 1.0):
            for distance in (16.0, 17.0):
                body, _forearm, blend = self.posed(steer, cat_distance=distance)
                with self.subTest(steer=steer, distance=distance):
                    self.assertTrue(0.0 < float(blend.min()) and float(blend.max()) < 1.0,
                                    "the blend is not mid-way between helm and wave")
                self.check_figure(body, steer, f"blend {float(blend.mean()):.2f}")

    def test_only_the_jon_figure_fades_its_steer_swing_as_it_waves(self):
        # The steer swing fades with the wave for the jon alone (skipperview.SkipperFigure.params): its
        # tiller turns the arm that waves. Other boats' figures keep the full 0.55 rad swing at steer 1.
        from .skipperview import SkipperFigure
        camera = Camera(0.0, 1.22, 0.0, yaw=0.0, pitch=0.0, roll=0.0, fov_x=FOV, w=1280, h=720, build_rays=False)
        for boat_id, swing in (("jon", 0.0), ("rowboat", 0.55), ("sail", 0.55), ("pontoon", 0.55)):
            state = self.state(1.0)
            state.boat_id = boat_id
            figure = SkipperFigure()
            actor = figure.place(state, camera)
            state.npcs = (_cat_ahead(actor, 5.0, state),)
            params = figure.params(state, False)
            with self.subTest(boat=boat_id):
                self.assertEqual(float(params["blend"]), 1.0)
                self.assertAlmostEqual(float(params["arm"]), swing, places=9)

    def test_the_outboard_clamp_and_the_tiller_knuckle_share_one_steel(self):
        from .boatmesh import _STEEL
        clamp = outboard_faces(0.0, TILLER_PAINT)[0]
        knuckle = self.parts(0.0)["knuckle"][0]
        np.testing.assert_allclose(clamp.color, _STEEL, atol=1e-6)
        np.testing.assert_allclose(knuckle.color, _STEEL, atol=1e-6)


if __name__ == "__main__":
    unittest.main()
