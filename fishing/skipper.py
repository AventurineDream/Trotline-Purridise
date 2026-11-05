"""The Skipper in first person (V1-29): two paws and a calm-water self-reflection.

Paws are a small mesh in the boat's eye frame (x to starboard, y up, z ahead), as
the cockpit meshes are. They hold the boat's tiller, oars or paddle, and the line
hand over hand while the haul screen is up. Where a boat's own control sits out of
view, the paws hold its in-view end: a tiller extension, the oar looms or the
paddle shaft. Wheel-steered boats show paws only for the haul.

The head is never drawn in the scene. Only the reflection pass sees its
silhouette, placed so its mirror image lies on the water just past the bow, and
only when the boat sits idle on calm water.
"""

from __future__ import annotations

import math

import numpy as np

from .catmesh import _ellipsoid, _rot, _tube

# The fixed Skipper palette: a dusk-brown tabby with cream mitts.
COAT = np.array((0.66, 0.54, 0.40), np.float32)
STRIPE = np.array((0.33, 0.25, 0.17), np.float32)
MITT = np.array((0.93, 0.90, 0.84), np.float32)
PAD = np.array((0.78, 0.52, 0.52), np.float32)
WOOD = np.array((0.58, 0.42, 0.26), np.float32)
LINE = np.array((0.86, 0.82, 0.68), np.float32)
# The reflection is the coat in shadow, not black: near-black read as a hole in the
# water, or a dark creature standing on it (V1-42).
SILHOUETTE = (COAT * np.float32(0.55)).astype(np.float32)

# Below this speed, with calm water, the Skipper's reflection shows.
IDLE_SPEED = 0.05


class _Mesh:
    def __init__(self):
        self.pos, self.nrm, self.rgb, self.tris = [], [], [], []
        self.count = 0

    def add(self, pos, nrm, faces, rgb):
        pos = np.asarray(pos, np.float32)
        self.pos.append(pos)
        self.nrm.append(np.asarray(nrm, np.float32))
        self.rgb.append(np.broadcast_to(np.asarray(rgb, np.float32), pos.shape).copy())
        self.tris.append(np.asarray(faces, np.int32).reshape(-1, 3) + self.count)
        self.count += len(pos)

    def arrays(self):
        if not self.pos:
            return (np.zeros((0, 3), np.float32), np.zeros((0, 3), np.float32), np.zeros((0, 3), np.float32),
                    np.zeros((0, 3), np.int32))
        return (np.concatenate(self.pos), np.concatenate(self.nrm), np.concatenate(self.rgb),
                np.concatenate(self.tris))


def grip_kind(state) -> str | None:
    """What the paws hold: haul, tiller, oars, tiller_oar, paddle, or None (a wheel)."""
    if getattr(state, "hauling", False):
        return "haul"
    if state.boat_id == "rowboat":
        return "tiller_oar" if state.rowboat_trolling_motor else "oars"
    if state.boat_id == "pontoon":
        return None
    return {"tiller": "tiller", "sail": "tiller", "oars": "oars", "paddle": "paddle"}.get(state.boat.power)


def _paw(m, wrist, toward, side):
    """A forearm from off-screen to `wrist`, then a cream mitt reaching along `toward`."""
    toward = np.asarray(toward, np.float32)
    toward /= np.linalg.norm(toward) + 1e-8
    wrist = np.asarray(wrist, np.float32)
    elbow = wrist + np.array((side * 0.10, -0.30, -0.50), np.float32)
    points = elbow + (wrist - elbow) * np.linspace(0.0, 1.0, 13)[:, None]
    pos, nrm, faces, along = _tube(points, np.linspace(0.050, 0.040, 13), 8, caps=False)
    # Tabby rings around the forearm, from the fixed Skipper palette.
    rgb = np.where((np.sin(along * 34.0) > 0.25)[:, None], STRIPE, COAT)
    m.add(pos, nrm, faces, rgb)
    yaw = math.atan2(float(toward[0]), float(toward[2]))
    pitch = -math.asin(max(-1.0, min(1.0, float(toward[1]))))
    rot = _rot(pitch, yaw)
    centre = wrist + toward * 0.040
    pos, nrm, faces, _a = _ellipsoid(centre, (0.056, 0.036, 0.066), rot, 6, 8)
    m.add(pos, nrm, faces, MITT)
    # Three toe bumps across the front of the mitt, and a pink pad peeking beneath.
    for k in (-1, 0, 1):
        toe = centre + rot @ np.array((k * 0.030, 0.010, 0.054), np.float32)
        pos, nrm, faces, _a = _ellipsoid(toe, (0.019, 0.016, 0.019), rot, 4, 6)
        m.add(pos, nrm, faces, MITT * 0.97)
    pad = centre + rot @ np.array((0.0, -0.029, 0.022), np.float32)
    pos, nrm, faces, _a = _ellipsoid(pad, (0.026, 0.009, 0.022), rot, 4, 6)
    m.add(pos, nrm, faces, PAD)


def _stick(m, a, b, radius, rgb, samples=6):
    """A straight rod in short segments, so a near-plane cull drops only its hidden end."""
    a, b = np.asarray(a, np.float32), np.asarray(b, np.float32)
    points = a + (b - a) * np.linspace(0.0, 1.0, samples)[:, None]
    pos, nrm, faces, _a = _tube(points, np.full(samples, radius), 6)
    m.add(pos, nrm, faces, rgb)


def _tiller_pivot(state):
    """The boat's own tiller end in its eye frame, when the cockpit mesh has one."""
    if state.boat_id == "jon":
        ang = -state.steer * 0.65
        return np.array((0.30 + math.cos(ang) * 0.27, -0.62 + 0.035, 1.58 + math.sin(ang) * 0.16), np.float32)
    if state.boat_id == "sail":
        return np.array((0.12 + state.steer * 0.14, -0.54, 0.68), np.float32)
    if state.boat_id == "rowboat":
        return np.array((0.50, -0.24, 0.89), np.float32)
    return np.array((0.05, -0.80, state.boat.stern + 0.5), np.float32)


def paw_mesh(state, reduced_motion: bool = False):
    """(positions, normals, colours, triangles) of the Skipper's paws in the eye frame."""
    kind = grip_kind(state)
    m = _Mesh()
    if kind is None:
        return m.arrays()
    t = 0.0 if reduced_motion else float(state.anim)
    if kind == "haul":
        # Hand over hand: the line rises from the water past the bow to the paws.
        water = np.array((0.06, -1.25, 3.4), np.float32)
        near = np.array((-0.12, -0.10, 0.52), np.float32)
        _stick(m, near + (water - near) * 0.015, water, 0.008, LINE, 12)
        swing = 0.0 if reduced_motion else math.sin(t * math.tau * 0.9)
        for side, offset in ((1, 0.16 + 0.05 * swing), (-1, 0.07 - 0.05 * swing)):
            grip = near + (water - near) * offset
            _paw(m, grip + np.array((side * 0.02, 0.02, 0.0), np.float32), water - near, side)
        return m.arrays()
    if kind in ("tiller", "tiller_oar"):
        pivot = _tiller_pivot(state)
        if state.boat_id == "jon":
            grip = pivot + np.array((0.0, 0.02, 0.0), np.float32)
        else:
            grip = np.array((0.32 - float(state.steer) * 0.10, -0.33, 0.90), np.float32)
            _stick(m, grip + (grip - pivot) * 0.06, pivot, 0.016, (0.13, 0.14, 0.15))
        _paw(m, grip + np.array((0.0, 0.02, -0.02), np.float32), grip - pivot + np.array((0, 0, 0.4)), 1)
    if kind in ("oars", "tiller_oar"):
        sides = (-1,) if kind == "tiller_oar" else (-1, 1)
        for side in sides:
            grip = np.array((side * 0.40, -0.31, 0.80), np.float32)
            if state.boat_id == "rowboat":
                lock = np.array((side * 0.59, -0.33, 0.96), np.float32)
            else:
                lock = np.array((side * 0.9, -0.55, -0.4), np.float32)
            _stick(m, grip - (lock - grip) * 0.15, lock, 0.020, WOOD)
            _paw(m, grip + np.array((0.0, 0.025, -0.01), np.float32), (side * 0.25, 0.0, 1.0), side)
    if kind == "paddle":
        top = np.array((0.16, -0.13, 0.80), np.float32)
        blade = np.array((1.10, -1.30, 2.50), np.float32)
        stroke = 0.0 if reduced_motion or abs(state.speed) < 0.2 else 0.05 * math.sin(t * math.tau * 0.6)
        top = top + np.array((0.0, 0.0, stroke), np.float32)
        _stick(m, top, blade, 0.018, WOOD, 8)
        _paw(m, top + np.array((0.0, 0.03, 0.0), np.float32), (0.1, 0.1, 1.0), -1)
        _paw(m, top + (blade - top) * 0.26 + np.array((0.0, 0.03, 0.0), np.float32), (0.3, 0.0, 1.0), 1)
    return m.arrays()


def reflection_weight(state, light: dict) -> float:
    """How calm the mirror is for the head: idle, not hauling, no rain and little mist."""
    if getattr(state, "hauling", False) or abs(float(state.speed)) >= IDLE_SPEED:
        return 0.0
    return float(max(0.0, min(1.0, 1.0 - 2.0 * light["rain"] - 0.5 * light.get("mist", 0.0))))


def shows_reflection(state, light: dict) -> bool:
    return reflection_weight(state, light) >= 0.5


def head_silhouette(state):
    """World-space (positions, normals, colours, triangles) of the head the reflection shows.

    The head floats at eye height straight ahead, so its mirror image lies on the
    water halfway out: far enough past the bow that the hull never hides it, ears
    included (they point down in the mirror). Its size reads at that range, about
    0.05 rad across.
    """
    m = _Mesh()
    model = state.boat
    eye = float(model.eye_height)
    landing = max(8.0, 3.4 * float(model.bow) * eye)
    ahead = 2.0 * landing
    s = 0.026 * ahead / 0.16
    yaw = float(state.yaw)
    forward = np.array((math.sin(yaw), 0.0, math.cos(yaw)), np.float32)
    centre = np.array((state.x, eye, state.z), np.float32) + forward * ahead
    rot = _rot(0.0, yaw + math.pi)
    pos, nrm, faces, _a = _ellipsoid(centre, (0.16 * s, 0.14 * s, 0.14 * s), rot, 6, 10)
    m.add(pos, nrm, faces, SILHOUETTE)
    for side in (-1, 1):
        inner = centre + rot @ (np.array((side * 0.03, 0.12, 0.0), np.float32) * s)
        outer = centre + rot @ (np.array((side * 0.14, 0.08, 0.0), np.float32) * s)
        tip = centre + rot @ (np.array((side * 0.13, 0.26, 0.0), np.float32) * s)
        ear = np.stack([inner, outer, tip, inner, outer, tip])
        m.add(ear, np.broadcast_to(-forward, ear.shape), [(0, 1, 2), (3, 5, 4)], SILHOUETTE)
    return m.arrays()
