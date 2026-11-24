"""The shared parametric cat rig (V1-29): 52 cats from one body plan.

A cat is built in its own frame (x to its left, y up, z forward, origin on the
seat) from deformed ellipsoids and swept tubes: torso, head, muzzle, eyes,
nose, ears, whiskers, arms, hind legs and tail, plus attire from a shared kit
and the prop its pose holds. Every pose rebuilds the same topology, so poses
blend by plain vertex interpolation and animate in the vertex shader.

Each vertex carries its posed position and normal, its *coat* position and
normal (the same vertex in the neutral sit pose, so markings stay on the body
whatever the pose), a part id and a 0–1 coordinate along its part. The coat
pattern (`coat_rgb`) reads only those, so the GL fragment shader and the CPU
paths paint the same cat.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import json
import math

import numpy as np

LOD0, LOD1 = 0, 1
# Part ids, shared with shaders/cat.frag and cat.vert.
TORSO, HEAD, MUZZLE, NOSE, EYE, EAR, INNER_EAR, WHISKER = 0, 1, 2, 3, 4, 5, 6, 7
ARM_UPPER, FOREARM, PAW, LEG, FOOT, TAIL = 8, 9, 10, 11, 12, 13
ATTIRE, PROP, GLOW, RUFF, FOREARM_WAVE, PAW_WAVE, PUPIL = 14, 15, 16, 17, 18, 19, 20
# Rig channels for procedural motion, shared with shaders/cat.vert. A vertex's rig value is
# its channel plus RIG_STRIDE times its cat's index in the actor (Pebble, Pip's twin, is 1),
# so each cat turns its head and works its arms about its own pivots.
RIG_BODY, RIG_HEAD, RIG_EAR, RIG_TAIL, RIG_WAVE, RIG_TORSO, RIG_EAR_R, RIG_EYE, RIG_ARM = 0, 1, 2, 3, 4, 5, 6, 7, 8
RIG_STRIDE = 16
HEAD_CHANNELS = (RIG_HEAD, RIG_EAR, RIG_EAR_R, RIG_EYE)
HEAD_ATTIRE = ("cap", "spectacles", "goggles")
HEAD_PARTS = (HEAD, MUZZLE, NOSE, EYE, EAR, INNER_EAR, WHISKER, PUPIL)
HEAD_SCALE = 1.15  # a big, friendly head
# Authored idle poses (npcs.json). Each has a gesture pose it blends to as the player comes
# near: sitters and crafters wave, the helmsman waves from the wheel, a napper rouses and
# looks up. A waving cat is already mid-gesture.
POSES = ("sit_fish", "nap_curl", "wave", "craft", "helm")
GESTURES = {"sit_fish": "wave", "craft": "wave", "helm": "helm_wave", "nap_curl": "nap_rouse", "wave": None}
LYING = ("nap_curl", "nap_rouse")
STANDING = ("helm", "helm_wave")
PATTERNS = ("solid", "tabby", "mackerel", "calico", "tortoiseshell", "tuxedo", "point", "spotted", "bicolor")
_FOLDED_EARS = ("folded", "folded_left", "folded_right")


@dataclass(frozen=True)
class Pivots:
    """One cat's motion pivots in one built pose, in the actor frame (metres, posed size).

    neck: head turn, nod and tilt; elbow: the right forearm's wave and reel; arm,
    arm_axis: the arms' work rotation (shoulders and x for sitters, the wheel's hub and
    z at the helm); head_up: the head's up axis (blinks close along it); eye_open: the
    pose's 0-1 eye opening; seat: the weight-shift pivot under the cat; yaw: the cat's
    turn within the actor (radians; Pebble sits a little turned).
    """

    neck: np.ndarray
    elbow: np.ndarray
    arm: np.ndarray
    arm_axis: np.ndarray
    head_up: np.ndarray
    eye_open: float
    seat: np.ndarray
    yaw: float

    def moved(self, rot: np.ndarray, offset: np.ndarray, yaw: float) -> "Pivots":
        """These pivots for a cat placed in the actor by `rot` (3×3), `offset` and `yaw`."""
        return Pivots(self.neck @ rot.T + offset, self.elbow @ rot.T + offset, self.arm @ rot.T + offset,
                      self.arm_axis @ rot.T, self.head_up @ rot.T, self.eye_open, self.seat @ rot.T + offset,
                      self.yaw + yaw)


@dataclass(frozen=True)
class CatMesh:
    """Indexed geometry for one actor: every pose shares the triangles."""

    positions: dict          # pose -> (n, 3) float32
    normals: dict            # pose -> (n, 3) float32
    coat: np.ndarray         # (n, 3) neutral-pose positions
    coat_normals: np.ndarray  # (n, 3)
    part: np.ndarray         # (n,) float32 part id
    along: np.ndarray        # (n,) float32 0-1 along the part
    triangles: np.ndarray    # (m, 3) int32
    tags: np.ndarray         # (n,) attire item index, or -1
    rig: np.ndarray          # (n,) float32 rig channel (RIG_*)
    pivots: dict             # pose -> (Pivots, ...) one per cat, for the motion in shaders/cat.vert
    cats: tuple              # ((look, first vertex, end vertex), ...): Pip & Pebble share an actor

    @property
    def triangle_count(self) -> int:
        return int(len(self.triangles))

    @property
    def nbytes(self) -> int:
        arrays = [self.coat, self.coat_normals, self.part, self.along, self.triangles, self.tags, self.rig,
                  *self.positions.values(), *self.normals.values()]
        return sum(a.nbytes for a in arrays)

    def blend(self, weights: dict) -> tuple[np.ndarray, np.ndarray]:
        """Positions and normals for any weighting of the built poses."""
        total = sum(weights.values()) or 1.0
        pos = sum(self.positions[p] * (w / total) for p, w in weights.items())
        nrm = sum(self.normals[p] * (w / total) for p, w in weights.items())
        nrm = nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-6)
        return pos.astype(np.float32), nrm.astype(np.float32)


# --- Poses ------------------------------------------------------------------
# Joint positions at size 1 in the cat frame. "l" is the cat's left (+x); limbs
# mirror by x. Torso and head carry (centre, pitch, yaw); tails are Bézier cages.

def _pose(**kw):
    base = dict(
        torso=((0.0, 0.24, 0.0), 0.0), head=((0.0, 0.47, 0.03), 0.0, 0.0),
        hip=(0.075, 0.12, -0.02), knee=(0.09, 0.085, 0.10), ankle=(0.08, 0.03, 0.06), foot=(0.0, 0.0, 1.0),
        shoulder=(0.095, 0.34, 0.03), elbow_l=(0.11, 0.24, 0.07), wrist_l=(0.07, 0.17, 0.13),
        elbow_r=(-0.11, 0.24, 0.07), wrist_r=(-0.07, 0.17, 0.13),
        tail=((0.0, 0.06, -0.10), (0.06, 0.0, -0.26), (0.24, 0.0, -0.12), (0.20, 0.02, 0.10)),
        eyes_open=1.0, prop=((0.0, 0.20, 0.16), (0.0, 0.6, 0.8)))
    base.update(kw)
    return base


POSE_JOINTS = {
    # Sitting upright on the haunches, both paws forward on the rod.
    "sit_fish": _pose(head=((0.0, 0.47, 0.035), 0.12, 0.0),
                      elbow_l=(0.11, 0.25, 0.09), wrist_l=(0.045, 0.21, 0.17),
                      elbow_r=(-0.11, 0.25, 0.09), wrist_r=(-0.045, 0.22, 0.18),
                      prop=((0.0, 0.215, 0.175), (0.0, 0.62, 0.78))),
    # Curled asleep on the deck, chin on the paws, tail around the front.
    "nap_curl": _pose(torso=((0.0, 0.11, -0.02), 1.42), head=((0.0, 0.11, 0.21), 0.35, 0.25),
                      hip=(0.07, 0.07, -0.14), knee=(0.10, 0.05, -0.02), ankle=(0.08, 0.03, 0.06),
                      shoulder=(0.08, 0.10, 0.10), elbow_l=(0.09, 0.05, 0.18), wrist_l=(0.05, 0.035, 0.27),
                      elbow_r=(-0.09, 0.05, 0.18), wrist_r=(-0.05, 0.035, 0.27),
                      tail=((0.0, 0.08, -0.22), (0.20, 0.02, -0.30), (0.26, 0.02, 0.10), (0.06, 0.03, 0.30)),
                      eyes_open=0.0, prop=((0.0, 0.03, 0.27), (0.0, 0.0, 1.0))),
    # Sitting, the right paw raised high; the forearm waves in the shader.
    "wave": _pose(head=((0.0, 0.475, 0.03), -0.05, 0.0),
                  elbow_r=(-0.16, 0.40, 0.05), wrist_r=(-0.15, 0.52, 0.08),
                  elbow_l=(0.11, 0.24, 0.06), wrist_l=(0.08, 0.15, 0.11),
                  prop=((0.08, 0.15, 0.13), (0.0, 0.85, 0.5))),
    # Sitting with the prop close to the chest: a book, brush, whittling, a mug.
    "craft": _pose(head=((0.0, 0.465, 0.04), 0.35, 0.0),
                   elbow_l=(0.11, 0.24, 0.07), wrist_l=(0.05, 0.26, 0.15),
                   elbow_r=(-0.11, 0.24, 0.07), wrist_r=(-0.05, 0.26, 0.15),
                   prop=((0.0, 0.27, 0.17), (0.0, 0.5, 0.86))),
    # Standing at the helm, paws forward at chest height.
    "helm": _pose(torso=((0.0, 0.47, 0.0), 0.05), head=((0.0, 0.72, 0.035), 0.05, 0.0),
                  hip=(0.07, 0.34, -0.01), knee=(0.08, 0.19, 0.04), ankle=(0.08, 0.045, -0.02),
                  shoulder=(0.095, 0.585, 0.03), elbow_l=(0.12, 0.49, 0.10), wrist_l=(0.08, 0.50, 0.21),
                  elbow_r=(-0.12, 0.49, 0.10), wrist_r=(-0.08, 0.50, 0.21),
                  tail=((0.0, 0.31, -0.10), (0.02, 0.16, -0.20), (0.05, 0.02, -0.26), (0.10, 0.16, -0.34)),
                  prop=((0.0, 0.50, 0.24), (0.0, 0.3, 0.95))),
    # Gesture poses (GESTURES): never authored, only blended to as the player comes near.
    # At the helm, the left paw keeps the wheel and the right waves high; the tail lifts.
    "helm_wave": _pose(torso=((0.0, 0.47, 0.0), 0.05), head=((0.0, 0.725, 0.03), -0.05, 0.0),
                       hip=(0.07, 0.34, -0.01), knee=(0.08, 0.19, 0.04), ankle=(0.08, 0.045, -0.02),
                       shoulder=(0.095, 0.585, 0.03), elbow_l=(0.12, 0.49, 0.10), wrist_l=(0.08, 0.50, 0.21),
                       elbow_r=(-0.16, 0.645, 0.05), wrist_r=(-0.15, 0.765, 0.08),
                       tail=((0.0, 0.31, -0.10), (0.02, 0.30, -0.22), (0.06, 0.42, -0.28), (0.04, 0.55, -0.22)),
                       prop=((0.0, 0.50, 0.24), (0.0, 0.3, 0.95))),
    # A napper roused: still curled, the head lifted off the paws, eyes half open.
    "nap_rouse": _pose(torso=((0.0, 0.11, -0.02), 1.42), head=((0.0, 0.20, 0.17), -0.10, 0.10),
                       hip=(0.07, 0.07, -0.14), knee=(0.10, 0.05, -0.02), ankle=(0.08, 0.03, 0.06),
                       shoulder=(0.08, 0.10, 0.10), elbow_l=(0.09, 0.05, 0.18), wrist_l=(0.05, 0.035, 0.27),
                       elbow_r=(-0.09, 0.05, 0.18), wrist_r=(-0.05, 0.035, 0.27),
                       tail=((0.0, 0.08, -0.22), (0.20, 0.02, -0.30), (0.26, 0.02, 0.10), (0.06, 0.08, 0.30)),
                       eyes_open=0.75, prop=((0.0, 0.03, 0.27), (0.0, 0.0, 1.0))),
}


# --- Primitives ---------------------------------------------------------------

class _Builder:
    def __init__(self):
        self.pos, self.nrm, self.part, self.along, self.tris, self.tags = [], [], [], [], [], []
        self.count = 0
        self.tag = -1

    def add(self, pos, nrm, faces, part, along):
        n = len(pos)
        self.tags.append(np.full(n, self.tag, np.int16))
        self.pos.append(np.asarray(pos, np.float32))
        self.nrm.append(np.asarray(nrm, np.float32))
        self.part.append(np.full(n, part, np.float32) if np.isscalar(part) else np.asarray(part, np.float32))
        self.along.append(np.full(n, along, np.float32) if np.isscalar(along) else np.asarray(along, np.float32))
        self.tris.append(np.asarray(faces, np.int32) + self.count)
        self.count += n

    def arrays(self):
        return (np.concatenate(self.pos), np.concatenate(self.nrm), np.concatenate(self.part),
                np.concatenate(self.along), np.concatenate(self.tris), np.concatenate(self.tags))


def _grid_faces(rings, segments, closed=True):
    faces = []
    cols = segments if closed else segments - 1
    for i in range(rings - 1):
        for j in range(cols):
            a, b = i * segments + j, i * segments + (j + 1) % segments
            c, d = (i + 1) * segments + (j + 1) % segments, (i + 1) * segments + j
            faces += [(a, b, c), (a, c, d)]
    return faces


def _rot(pitch=0.0, yaw=0.0, roll=0.0):
    """Rotation: roll about z, then pitch about x (nose down is positive), then yaw about y."""
    cp, sp, cy, sy, cr, sr = math.cos(pitch), math.sin(pitch), math.cos(yaw), math.sin(yaw), math.cos(roll), math.sin(roll)
    rz = np.array([[cr, -sr, 0], [sr, cr, 0], [0, 0, 1]], np.float32)
    rx = np.array([[1, 0, 0], [0, cp, sp], [0, -sp, cp]], np.float32)
    ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]], np.float32)
    return ry @ rx @ rz


def _ellipsoid(centre, radii, rot, rings, segments, shape=None):
    """A closed ellipsoid; `shape(v, u)` returns per-vertex (x, y, z) radius scales."""
    v = np.linspace(0.0, 1.0, rings)[:, None]
    u = np.linspace(0.0, 1.0, segments, endpoint=False)[None, :]
    theta, phi = v * math.pi, u * math.tau
    unit = np.stack([np.sin(theta) * np.sin(phi), np.cos(theta) * np.ones_like(phi), np.sin(theta) * np.cos(phi)], -1)
    scale = np.ones_like(unit) if shape is None else np.broadcast_to(shape(v, u), unit.shape)
    r = np.asarray(radii, np.float32)
    local = unit * scale * r
    normal = unit * scale / np.maximum(r, 1e-6)
    pos = (local.reshape(-1, 3) @ rot.T) + np.asarray(centre, np.float32)
    nrm = normal.reshape(-1, 3) @ rot.T
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
    along = np.repeat(v[:, 0], segments)
    return pos, nrm, _grid_faces(rings, segments), along


def _band(centre, radii, rot, v0, v1, rings, segments, shape=None):
    """An open ellipsoid band between polar fractions v0 and v1 (attire shells)."""
    v = np.linspace(v0, v1, rings)[:, None]
    u = np.linspace(0.0, 1.0, segments, endpoint=False)[None, :]
    theta, phi = v * math.pi, u * math.tau
    unit = np.stack([np.sin(theta) * np.sin(phi), np.cos(theta) * np.ones_like(phi), np.sin(theta) * np.cos(phi)], -1)
    scale = np.ones_like(unit) if shape is None else np.broadcast_to(shape(v, u), unit.shape)
    r = np.asarray(radii, np.float32)
    pos = ((unit * scale * r).reshape(-1, 3) @ rot.T) + np.asarray(centre, np.float32)
    nrm = (unit * scale / np.maximum(r, 1e-6)).reshape(-1, 3) @ rot.T
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-9)
    along = np.repeat((v[:, 0] - v0) / max(v1 - v0, 1e-6), segments)
    return pos, nrm, _grid_faces(rings, segments), along


def _frames(points):
    """Parallel-transport frames along a polyline."""
    tangents = np.gradient(points, axis=0)
    tangents /= np.maximum(np.linalg.norm(tangents, axis=1, keepdims=True), 1e-9)
    ref = np.array([0.0, 1.0, 0.0]) if abs(tangents[0, 1]) < 0.9 else np.array([1.0, 0.0, 0.0])
    normal = np.cross(tangents[0], ref)
    normal /= np.linalg.norm(normal)
    normals = [normal]
    for k in range(1, len(points)):
        n = normals[-1] - tangents[k] * float(normals[-1] @ tangents[k])
        normals.append(n / max(np.linalg.norm(n), 1e-9))
    normals = np.asarray(normals)
    return tangents, normals, np.cross(tangents, normals)


def _tube(points, radii, sides, caps=True):
    """A swept tube with rounded end caps: points (n, 3), radii (n,)."""
    points = np.asarray(points, np.float64)
    t, n, b = _frames(points)
    angle = np.linspace(0, math.tau, sides, endpoint=False)
    ring = np.cos(angle)[None, :, None] * n[:, None, :] + np.sin(angle)[None, :, None] * b[:, None, :]
    pos = points[:, None, :] + ring * np.asarray(radii)[:, None, None]
    nrm = ring
    along = np.repeat(np.linspace(0, 1, len(points)), sides)
    pos, nrm = pos.reshape(-1, 3), nrm.reshape(-1, 3)
    faces = _grid_faces(len(points), sides)
    if caps:
        extra_pos, extra_nrm, extra_along = [], [], []
        base = len(pos)
        for end, sign, ring_index in ((0, -1.0, 0), (len(points) - 1, 1.0, len(points) - 1)):
            tip = points[end] + t[end] * sign * radii[end] * 0.8
            extra_pos.append(tip)
            extra_nrm.append(t[end] * sign)
            extra_along.append(float(end > 0))
            centre = base + len(extra_pos) - 1
            for j in range(sides):
                a, c = ring_index * sides + j, ring_index * sides + (j + 1) % sides
                faces.append((centre, c, a) if sign < 0 else (centre, a, c))
        pos = np.concatenate([pos, extra_pos])
        nrm = np.concatenate([nrm, extra_nrm])
        along = np.concatenate([along, extra_along])
    return pos.astype(np.float32), nrm.astype(np.float32), faces, along.astype(np.float32)


def _bezier(cage, samples):
    p0, p1, p2, p3 = (np.asarray(p, np.float64) for p in cage)
    t = np.linspace(0, 1, samples)[:, None]
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t * t * p2 + t ** 3 * p3


def _limb(a, b, c, r0, r1, sides, samples):
    """Two segments a→b→c as one smooth tube."""
    a, b, c = (np.asarray(p, np.float64) for p in (a, b, c))
    t = np.linspace(0, 1, samples)[:, None]
    # A quadratic through the joint keeps the elbow soft without a seam.
    mid = 2 * b - 0.5 * (a + c)
    pts = (1 - t) ** 2 * a + 2 * (1 - t) * t * mid + t * t * c
    radii = np.linspace(r0, r1, samples)
    return _tube(pts, radii, sides)


def _ear(base, tip, width, depth, kind, lod, rot):
    """Outer and inner ear meshes in metres; folds follow the head's back and left/right axes."""
    rows = 4 if lod == LOD0 else 2
    cols = 6 if lod == LOD0 else 4
    base, tip = np.asarray(base, np.float64), np.asarray(tip, np.float64)
    up = tip - base
    height = np.linalg.norm(up)
    up /= height
    side = rot @ np.array([1.0, 0, 0])
    front = np.cross(side, up)
    folded = kind in _FOLDED_EARS
    if folded:
        # Both ears sweep together in head space, not outward from each ear.
        lateral = 0.85 if kind == "folded_left" else -0.85 if kind == "folded_right" else 0.0
        fold = (side * lateral - front) * height
    pos, nrm = [], []
    for i in range(rows + 1):
        s = i / rows
        if kind == "rounded":
            half = width * math.sqrt(max(0.0, 1 - s ** 2.2))
        elif folded:
            half = width * (1 - 0.6 * s)
        else:
            half = width * (1 - s) ** 0.9
        centre = base + up * height * s
        if folded:
            centre = centre + fold * 0.9 * s * s
        for j in range(cols):
            a = math.pi * j / (cols - 1)
            offset = side * math.cos(a) * half - front * math.sin(a) * depth * (1 - s)
            pos.append(centre + offset)
            nrm.append(side * math.cos(a) - front * math.sin(a))
    faces = _grid_faces(rows + 1, cols, closed=False)
    outer = (np.array(pos, np.float32), np.array(nrm, np.float32), faces,
             np.repeat(np.linspace(0, 1, rows + 1), cols).astype(np.float32))
    # The pink inside of the ear: a slightly smaller fan just in front.
    inner_pos = []
    for i in range(rows + 1):
        s = i / rows
        centre = base + up * height * s * 0.85 + front * depth * 0.25
        if folded:
            centre = centre + fold * 0.85 * s * s
        half = width * 0.62 * (1 - s) if kind != "rounded" else width * 0.62 * math.sqrt(max(0.0, 1 - s ** 2.2))
        for j in range(3):
            inner_pos.append(centre + side * (j - 1) * half)
    inner_faces = _grid_faces(rows + 1, 3, closed=False)
    inner = (np.array(inner_pos, np.float32), np.tile(front, (len(inner_pos), 1)).astype(np.float32), inner_faces,
             np.repeat(np.linspace(0, 1, rows + 1), 3).astype(np.float32))
    return outer, inner


def _box(centre, half, rot):
    corners = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], np.float32) * half
    pos = corners @ rot.T + centre
    faces = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1),
             (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
    nrm = corners / np.linalg.norm(corners, axis=1, keepdims=True)
    return pos.astype(np.float32), (nrm @ rot.T).astype(np.float32), faces, np.zeros(8, np.float32)


# --- The cat ----------------------------------------------------------------

def _counts(lod):
    if lod == LOD0:
        return dict(body=(12, 14), head=(11, 14), small=(6, 9), paw=(5, 8), eye=(5, 7), nose=(4, 6),
                    tube=6, limb=6, tail=12, tail_sides=7)
    return dict(body=(6, 8), head=(6, 8), small=(4, 5), paw=(3, 5), eye=(3, 4), nose=(3, 4),
                tube=4, limb=3, tail=6, tail_sides=4)


def _scaled(p, size):
    return np.asarray(p, np.float32) * size


def build(look: dict, pose: str, lod: int = LOD0) -> tuple:
    """Build one posed cat with its tail root buried inside the torso.

    Args:
        look: Validated appearance; size scales the rig's metre-based dimensions.
        pose: A POSE_JOINTS key, including the greeting poses.
        lod: LOD0 or LOD1; poses and tail kinds retain the same tail topology.

    Returns:
        Positions (metres), normals, part ids, along-part fractions, triangles,
        attire tags and motion pivots. Arrays belong to the caller.

    Raises:
        KeyError: An appearance or pose key is missing or unsupported.
    """
    j = POSE_JOINTS[pose]
    size = float(look["size"])
    build_ = float(look["build"])
    legs = float(look.get("legs", 1.0))
    coat = look["coat"]
    fluff = {"long": 1.12, "rex": 1.04, "hairless": 0.93}.get(coat, 1.0)
    c = _counts(lod)
    out = _Builder()
    s = size

    # Torso: a pear, wider at the seat; tilted forward when lying down.
    (tcx, tcy, tcz), tpitch = j["torso"]
    torso_rot = _rot(pitch=tpitch)
    torso_r = (0.115 * build_ * fluff * s, 0.17 * s, 0.105 * build_ * fluff * s)

    def pear(v, u):
        widen = 1.0 + 0.32 * np.clip(v - 0.35, 0, 1)
        if coat == "rex":
            widen = widen * (1.0 + 0.03 * np.sin(u * math.tau * 9) * np.sin(v * math.pi * 7))
        return np.stack([widen, np.ones_like(widen), widen * 0.96], -1)

    # Legs shorten the sitting height for Munchkins and lift the standing body.
    lift = (legs - 1.0) * (0.12 if pose in STANDING else 0.03)
    centre = _scaled((tcx, tcy + lift, tcz), s)
    p, n, f, a = _ellipsoid(centre, torso_r, torso_rot, *c["body"], shape=pear)
    out.add(p, n, f, TORSO, a)
    if coat == "long":
        # A neck ruff where the long coat gathers.
        ruff_c = _scaled(np.array(j["head"][0]) + (0.0, -0.075, -0.01), s)
        if pose in LYING:
            ruff_c = _scaled((0.0, 0.10, 0.13), s)
        p, n, f, a = _ellipsoid(ruff_c, (0.10 * s * build_, 0.055 * s, 0.095 * s * build_),
                                _rot(pitch=tpitch * 0.5), *c["small"])
        out.add(p, n, f, RUFF, a)

    # Head: cheeks wider below, the brow a little flat.
    (hx, hy, hz), hpitch, hyaw = j["head"]
    head_rot = _rot(pitch=hpitch, yaw=hyaw)
    head_c = _scaled((hx, hy + lift + 0.012, hz), s)
    hs = s * HEAD_SCALE

    def cheeks(v, u):
        wide = 1.0 + 0.14 * np.clip(v - 0.45, 0, 1) * 2
        return np.stack([wide, np.where(v < 0.3, 0.94, 1.0) * np.ones_like(wide), np.ones_like(wide)], -1)

    p, n, f, a = _ellipsoid(head_c, (0.105 * hs, 0.092 * hs, 0.095 * hs), head_rot, *c["head"], shape=cheeks)
    out.add(p, n, f, HEAD, a)

    def on_head(local):
        return head_c + (np.asarray(local, np.float32) * hs) @ head_rot.T

    # Muzzle, nose, eyes.
    p, n, f, a = _ellipsoid(on_head((0.0, -0.03, 0.074)), (0.046 * hs, 0.031 * hs, 0.032 * hs), head_rot, *c["small"])
    out.add(p, n, f, MUZZLE, a)
    p, n, f, a = _ellipsoid(on_head((0.0, -0.014, 0.104)), (0.012 * hs, 0.009 * hs, 0.008 * hs), head_rot, *c["nose"])
    out.add(p, n, f, NOSE, a)
    eyes = float(j["eyes_open"])
    for side in (1, -1):
        eye_rot = head_rot @ _rot(yaw=side * 0.30)
        p, n, f, a = _ellipsoid(on_head((side * 0.040, 0.016, 0.078)),
                                (0.024 * hs, 0.019 * hs * max(eyes, 0.1), 0.012 * hs), eye_rot, *c["eye"])
        out.add(p, n, f, EYE, a)
        p, n, f, a = _ellipsoid(on_head((side * 0.042, 0.016, 0.0885)),
                                (0.0065 * hs, 0.016 * hs * max(eyes, 0.05), 0.004 * hs), eye_rot, *c["nose"])
        out.add(p, n, f, PUPIL, a)

    # Folded ears lie backward; the directional variants also sweep together sideways.
    kind = look["ears"]
    height = 0.042 if kind in _FOLDED_EARS else {"pointed": 0.082, "rounded": 0.062, "tufted": 0.092}[kind]
    for side in (1, -1):
        if look.get("one_ear") and side < 0:
            continue
        base = on_head((side * 0.058, 0.062, -0.005))
        tip = on_head((side * 0.078, 0.062 + height, -0.01))
        (op, on_, of, oa), (ip, in_, inf, ia) = _ear(base, tip, 0.036 * hs, 0.018 * hs, kind, lod, head_rot)
        out.add(op, on_, of, EAR, oa)
        out.add(ip, in_, inf, INNER_EAR, ia)
        if kind == "tufted":
            tp, tn, tf, ta = _tube([tip, tip + (tip - base) * 0.35], [0.006 * hs, 0.001 * hs], 4, caps=False)
            out.add(tp, tn, tf, EAR, ta)

    # Whiskers (LOD0 only): three thin blades a side.
    if lod == LOD0:
        length = 0.075 * float(look["whiskers"]) * hs
        for side in (1, -1):
            for k in range(3):
                root = on_head((side * 0.03, -0.032 + k * 0.006, 0.098))
                tip = root + (head_rot @ np.array([side * 1.0, 0.18 - k * 0.18, 0.15])) * length
                width = head_rot @ np.array([0, 0.0015 * s, 0])
                wp = np.array([root - width, root + width, tip], np.float32)
                wn = np.tile(head_rot @ np.array([0, 0, 1.0]), (3, 1)).astype(np.float32)
                out.add(wp, wn, [(0, 1, 2)], WHISKER, np.array([0, 0, 1], np.float32))

    # Arms: shoulder, elbow, wrist, then the paw. The right forearm and paw wave.
    elbow_pivot = None
    for side in (1, -1):
        sx, sy, sz = j["shoulder"]
        shoulder = _scaled((side * sx, sy + lift, sz), s)
        elbow = _scaled(j["elbow_l" if side > 0 else "elbow_r"], s) + np.array([0, lift * s, 0], np.float32)
        wrist = _scaled(j["wrist_l" if side > 0 else "wrist_r"], s) + np.array([0, lift * s, 0], np.float32)
        r_arm = 0.036 * s * build_ * fluff
        p, n, f, a = _limb(shoulder, (shoulder + elbow) / 2, elbow, r_arm, r_arm * 0.92, c["tube"], c["limb"])
        out.add(p, n, f, ARM_UPPER, a * 0.5)
        p, n, f, a = _limb(elbow, (elbow + wrist) / 2, wrist, r_arm * 0.92, r_arm * 0.8, c["tube"], c["limb"])
        out.add(p, n, f, FOREARM if side > 0 else FOREARM_WAVE, 0.5 + a * 0.5)
        direction = wrist - elbow
        direction = direction / max(np.linalg.norm(direction), 1e-6)
        paw_c = wrist + direction * 0.022 * s
        pitch = math.atan2(-direction[1], math.hypot(direction[0], direction[2]))
        yaw = math.atan2(direction[0], direction[2])
        p, n, f, a = _ellipsoid(paw_c, (0.037 * s, 0.03 * s, 0.043 * s), _rot(pitch=pitch, yaw=yaw), *c["paw"])
        out.add(p, n, f, PAW if side > 0 else PAW_WAVE, a)
        if side < 0:
            elbow_pivot = elbow
    # The arms work about the shoulders' line when sitting and about the wheel's hub at the helm.
    sx, sy, sz = j["shoulder"]
    arm_pivot, arm_axis = _scaled((0.0, sy + lift, sz), s), np.array([1.0, 0.0, 0.0], np.float32)
    if pose in STANDING:
        arm_pivot = _scaled(j["prop"][0], s) + np.array([0, lift * s, 0], np.float32)
        arm_axis = np.asarray(j["prop"][1], np.float32) / np.float32(np.linalg.norm(j["prop"][1]))

    # Hind legs: a haunch along hip→knee, a shin to the ankle, the foot forward.
    for side in (1, -1):
        hip = _scaled((side * j["hip"][0], j["hip"][1], j["hip"][2]), s)
        knee = _scaled((side * j["knee"][0], j["knee"][1], j["knee"][2]), s)
        ankle = _scaled((side * j["ankle"][0], j["ankle"][1], j["ankle"][2]), s)
        if pose in STANDING:
            hip, knee = hip + np.array([0, lift * s, 0]), knee + np.array([0, lift * s * 0.5, 0])
        thigh = knee - hip
        length = max(np.linalg.norm(thigh), 1e-6)
        axis = thigh / length
        pitch = math.atan2(-axis[1], math.hypot(axis[0], axis[2]))
        yaw = math.atan2(axis[0], axis[2])
        haunch_r = (0.062 * s * build_ * fluff, 0.072 * s * build_ * fluff, max(length * 0.62, 0.05 * s))
        p, n, f, a = _ellipsoid((hip + knee) / 2, haunch_r, _rot(pitch=pitch, yaw=yaw), *c["small"])
        out.add(p, n, f, LEG, a * 0.4)
        r_leg = 0.032 * s * build_ * fluff
        p, n, f, a = _limb(knee, (knee + ankle) / 2, ankle, r_leg, r_leg * 0.85, c["tube"], c["limb"])
        out.add(p, n, f, LEG, 0.4 + a * 0.6)
        fx, fy, fz = j["foot"]
        foot_c = ankle + np.array([0.0, -0.01 * s, 0.035 * s], np.float32)
        p, n, f, a = _ellipsoid(foot_c, (0.03 * s, 0.022 * s, 0.05 * s), _rot(yaw=side * 0.1), *c["paw"])
        out.add(p, n, f, FOOT, a)

    # Keep the authored tip and tail kinds, but bury the root in the posed rump.
    tail_kind = look["tail"]
    length = {"long": 1.0, "plume": 1.0, "bob": 0.28, "none": 0.08}[tail_kind]
    cage = _scaled(j["tail"], s)
    cage[:, 1] += lift * s if pose not in LYING else 0.0
    u = np.linspace(0, 1, c["tail"])
    t = (u * length)[:, None]
    pts = (1 - t) ** 3 * cage[0] + 3 * (1 - t) ** 2 * t * cage[1] + 3 * (1 - t) * t * t * cage[2] + t ** 3 * cage[3]
    root = pts[0] - centre
    root_distance = np.linalg.norm((root @ torso_rot) / torso_r)
    # The inner 30% leaves room for the whole ring and cap even on thin, low-LOD
    # torsos. Fade the inset over the *shortened* curve so a Manx tuft is not buried.
    inset = centre + root * (0.30 / root_distance) - pts[0]
    pts += inset * (1 - u[:, None]) ** 3
    thick = (0.034 if tail_kind == "plume" else 0.022) * s * fluff
    radii = thick * (1.0 - 0.55 * u ** 1.5)
    if tail_kind == "plume":
        radii = radii * (1.0 + 0.35 * np.sin(u * math.pi))
    p, n, f, a = _tube(pts, radii, c["tail_sides"])
    out.add(p, n, f, TAIL, a)

    _attire(out, look, j, s, build_, fluff, lift, head_c, head_rot, torso_rot, centre, radii_torso=torso_r,
            lod=lod, counts=c, pose=pose)
    _prop(out, look, j, s, lift, lod, counts=c)
    pos, nrm, part, along, tris, tags = out.arrays()
    pivots = Pivots(neck=(head_c + (np.array([0.0, -0.07, -0.02], np.float32) * hs) @ head_rot.T).astype(np.float32),
                    elbow=np.asarray(elbow_pivot, np.float32), arm=np.asarray(arm_pivot, np.float32),
                    arm_axis=arm_axis.astype(np.float32),
                    head_up=(head_rot @ np.array([0.0, 1.0, 0.0])).astype(np.float32), eye_open=eyes,
                    seat=np.zeros(3, np.float32), yaw=0.0)
    return pos, nrm, part, along, tris, tags, pivots


def _attire(out, look, j, s, build_, fluff, lift, head_c, head_rot, torso_rot, torso_c, radii_torso, lod, counts,
            pose):
    hs = s * HEAD_SCALE

    def on_head(local):
        return head_c + (np.asarray(local, np.float32) * hs) @ head_rot.T

    neck = _scaled(np.array(j["head"][0]) + (0.0, -0.085, -0.005), s) + np.array([0, lift * s, 0], np.float32)
    if pose in LYING:
        neck = _scaled((0.0, 0.11, 0.12), s)
    for index, item in enumerate(look["attire"]):
        out.tag = index
        kind = item["kind"]
        if kind in ("oilskin", "parka", "sweater", "vest", "life_jacket", "shawl"):
            # A shell over the torso between two polar fractions, a little proud of the fur.
            grow, v0, v1 = {"oilskin": (1.09, 0.06, 0.92), "parka": (1.13, 0.03, 0.98), "sweater": (1.05, 0.08, 0.78),
                            "vest": (1.07, 0.10, 0.74), "life_jacket": (1.17, 0.10, 0.52),
                            "shawl": (1.14, 0.04, 0.42)}[kind]
            r = np.asarray(radii_torso) * np.array([grow, 1.02, grow])

            def shell(v, u, kind=kind):
                widen = 1.0 + 0.32 * np.clip(v - 0.35, 0, 1)
                if kind == "vest":
                    # Open at the front: tuck the front strip under the coat.
                    widen = np.where(np.cos(u * math.tau) > 0.8, 0.8, widen)
                if kind == "shawl":
                    # A point that hangs down the back.
                    widen = widen * (1.0 + 0.0 * u)
                return np.stack([widen, np.ones_like(widen), widen * 0.96], -1)

            rings = max(3, int(counts["body"][0] * (v1 - v0)) + 2)
            p, n, f, a = _band(torso_c, r, torso_rot, v0, v1, rings, counts["body"][1], shape=shell)
            out.add(p, n, f, ATTIRE, a)
            if kind == "parka":
                ang = np.linspace(0, math.tau, counts["body"][1] + 1)
                pts = [neck + torso_rot @ np.array([0.095 * s * math.sin(t), 0, 0.09 * s * math.cos(t)]) for t in ang]
                p, n, f, a = _tube(pts, [0.03 * s] * len(pts), counts["tube"], caps=False)
                out.add(p, n, f, RUFF, a)
        elif kind in ("scarf", "bandana"):
            ring = 0.088 if kind == "scarf" else 0.084
            ang = np.linspace(0, math.tau, counts["body"][1] + 1)
            pts = [neck + torso_rot @ np.array([ring * s * build_ * math.sin(t), 0, ring * s * build_ * math.cos(t) * 0.95])
                   for t in ang]
            p, n, f, a = _tube(pts, [(0.02 if kind == "scarf" else 0.014) * s] * len(pts), counts["tube"], caps=False)
            out.add(p, n, f, ATTIRE, a)
            drop = np.array([0.035 * s, -0.12 * s if kind == "scarf" else -0.06 * s, 0.09 * s])
            root = neck + torso_rot @ np.array([0.03 * s, -0.01 * s, 0.08 * s])
            p, n, f, a = _tube([root, root + torso_rot @ (drop * 0.5), root + torso_rot @ drop],
                               [0.02 * s, 0.017 * s, 0.01 * s], counts["tube"] - 2)
            out.add(p, n, f, ATTIRE, a)
        elif kind == "cap":
            p, n, f, a = _ellipsoid(on_head((0.0, 0.055, -0.005)), (0.1 * s, 0.05 * s, 0.098 * s), head_rot,
                                    *counts["small"], shape=lambda v, u: np.stack(
                                        [np.ones_like(v * u), np.where(v > 0.5, 0.25, 1.0) * np.ones_like(u),
                                         np.ones_like(v * u)], -1))
            out.add(p, n, f, ATTIRE, a)
            p, n, f, a = _ellipsoid(on_head((0.0, 0.045, 0.09)), (0.07 * s, 0.008 * s, 0.05 * s), head_rot,
                                    *counts["small"])
            out.add(p, n, f, ATTIRE, a)
        elif kind in ("spectacles", "goggles"):
            ring = 0.022 if kind == "spectacles" else 0.026
            height = 0.018 if kind == "spectacles" else 0.065
            # Thin wire reads at portrait size; at LOD1 the cat is a few dozen pixels tall.
            wire, rim, strap = (4, 9, 14) if lod == LOD0 else (3, 6, 7)
            for side in (1, -1):
                centre = on_head((side * 0.041, height, 0.1 if kind == "spectacles" else 0.08))
                ang = np.linspace(0, math.tau, rim)
                pts = [centre + head_rot @ (np.array([math.cos(t), math.sin(t), 0]) * ring * s) for t in ang]
                p, n, f, a = _tube(pts, [0.004 * s] * len(pts), wire, caps=False)
                out.add(p, n, f, ATTIRE, a)
                if kind == "goggles":
                    p, n, f, a = _ellipsoid(centre, (ring * s, ring * s, 0.008 * s), head_rot, *counts["eye"])
                    out.add(p, n, f, GLOW, a)
            if kind == "goggles":
                ang = np.linspace(-0.6 * math.pi, 1.6 * math.pi, strap)
                pts = [on_head((0.107 * math.sin(t), height, 0.098 * math.cos(t))) for t in ang]
                p, n, f, a = _tube(pts, [0.006 * s] * len(pts), wire, caps=False)
                out.add(p, n, f, ATTIRE, a)
        elif kind == "lantern":
            base = _scaled((0.19, 0.0, 0.12), s)
            out.add(*_box(base + np.array([0, 0.035 * s, 0], np.float32), np.array([0.025, 0.035, 0.025]) * s,
                          np.eye(3, dtype=np.float32))[:3], GLOW, np.zeros(8, np.float32))
            p, n, f, a = _box(base + np.array([0, 0.075 * s, 0], np.float32), np.array([0.03, 0.006, 0.03]) * s,
                              np.eye(3, dtype=np.float32))
            out.add(p, n, f, ATTIRE, a)
    out.tag = -1


def _prop(out, look, j, s, lift, lod, counts):
    prop = look["prop"]
    (px, py, pz), (dx, dy, dz) = j["prop"]
    at = _scaled((px, py, pz), s) + np.array([0, lift * s, 0], np.float32)
    direction = np.array([dx, dy, dz], np.float32)
    direction /= max(np.linalg.norm(direction), 1e-6)
    pitch = math.atan2(-direction[1], math.hypot(direction[0], direction[2]))
    yaw = math.atan2(direction[0], direction[2])
    rot = _rot(pitch=pitch, yaw=yaw)
    if prop == "rod":
        p, n, f, a = _tube([at - direction * 0.08 * s, at + direction * 1.3], [0.009 * s, 0.003], 5)
        out.add(p, n, f, PROP, a)
    elif prop == "book":
        for side in (1, -1):
            out.add(*_box(at + rot @ np.array([side * 0.045 * s, 0, 0], np.float32),
                          np.array([0.045, 0.004, 0.06]) * s, rot @ _rot(roll=-side * 0.25))[:3], PROP, 0.0)
    elif prop == "brush":
        p, n, f, a = _tube([at - direction * 0.04 * s, at + direction * 0.12 * s], [0.005 * s, 0.009 * s], 5)
        out.add(p, n, f, PROP, a)
        # A small easel and canvas in front of the cat.
        easel = _scaled((0.0, 0.18, 0.34), s)
        out.add(*_box(easel, np.array([0.11, 0.08, 0.006]) * s, _rot(pitch=-0.25))[:3], GLOW, 0.0)
    elif prop == "whittle":
        p, n, f, a = _tube([at - direction * 0.06 * s, at + direction * 0.09 * s], [0.011 * s, 0.008 * s], 5)
        out.add(p, n, f, PROP, a)
    elif prop == "mug":
        p, n, f, a = _tube([at, at + np.array([0, 0.06 * s, 0])], [0.03 * s, 0.03 * s], counts["tube"])
        out.add(p, n, f, PROP, a)
    elif prop == "tablet":
        out.add(*_box(at + rot @ np.array([0, 0.04 * s, 0.05 * s], np.float32), np.array([0.09, 0.005, 0.065]) * s,
                      rot @ _rot(pitch=0.7))[:3], GLOW, 0.0)


# --- Assembly and caching -------------------------------------------------------

def _poses_for(look) -> tuple[str, ...]:
    """The cat's own idle pose, plus the gesture it blends to as the player comes near."""
    gesture = GESTURES[look["pose"]]
    return (look["pose"],) if gesture is None else (look["pose"], gesture)


def slots(mesh: "CatMesh") -> tuple[str, str | None]:
    """A mesh's (idle, gesture) pose keys; gesture is None for a cat already waving."""
    pose = mesh.cats[0][0]["pose"]
    return pose, GESTURES[pose]


def _assemble(look: dict, lod: int) -> CatMesh:
    looks = [(look, np.zeros(3, np.float32), 0.0)]
    if "twin" in look:
        looks.append((look["twin"], np.array([-0.26 * look["size"], 0.0, 0.04], np.float32), 0.35))
    poses = _poses_for(look)
    positions, normals, pivots = {}, {}, {}
    coat, coat_n, part, along, tris, tags, rig, cats = [], [], [], [], [], [], [], []
    count = 0
    for index, (cat_look, offset, yaw) in enumerate(looks):
        rot = _rot(yaw=yaw)
        for slot, pose in enumerate(poses):
            # The twin keeps its own idle pose and blends to that pose's own gesture.
            own = cat_look["pose"] if slot == 0 else (GESTURES[cat_look["pose"]] or cat_look["pose"])
            p, n, _pa, _al, _tr, _tg, cat_pivots = build(cat_look, own, lod)
            positions.setdefault(pose, []).append(p @ rot.T + offset)
            normals.setdefault(pose, []).append(n @ rot.T)
            pivots.setdefault(pose, []).append(cat_pivots.moved(rot.astype(np.float32), offset, yaw))
        p, n, pa, al, tr, tg, _ = build(cat_look, "sit_fish", lod)
        rig.append(_rig(cat_look, pa, tg, p) + RIG_STRIDE * index)
        coat.append(p @ rot.T + offset)
        coat_n.append(n @ rot.T)
        part.append(pa)
        along.append(al)
        tags.append(tg)
        tris.append(tr + count)
        cats.append((cat_look, count, count + len(p)))
        count += len(p)
    return CatMesh({k: np.concatenate(v).astype(np.float32) for k, v in positions.items()},
                   {k: np.concatenate(v).astype(np.float32) for k, v in normals.items()},
                   np.concatenate(coat).astype(np.float32), np.concatenate(coat_n).astype(np.float32),
                   np.concatenate(part), np.concatenate(along), np.concatenate(tris).astype(np.int32),
                   np.concatenate(tags), np.concatenate(rig).astype(np.float32),
                   {k: tuple(v) for k, v in pivots.items()}, tuple(cats))


def _rig(look, part, tags, pos):
    """Each vertex's rig channel (RIG_*) for one cat; `pos` is its sit pose, which sides the ears."""
    rig = np.full(len(part), RIG_BODY, np.float32)
    head_items = [i for i, item in enumerate(look["attire"]) if item["kind"] in HEAD_ATTIRE]
    on_head = np.isin(part, HEAD_PARTS) | ((part == ATTIRE) & np.isin(tags, head_items)) | (
        (part == GLOW) & np.isin(tags, head_items))
    rig[on_head] = RIG_HEAD
    ear = (part == EAR) | (part == INNER_EAR)
    rig[ear & (pos[:, 0] >= 0)] = RIG_EAR
    rig[ear & (pos[:, 0] < 0)] = RIG_EAR_R
    rig[(part == EYE) | (part == PUPIL)] = RIG_EYE
    rig[part == TAIL] = RIG_TAIL
    # The left arm, the right upper arm and whatever the paws hold work together (cast, page, wheel).
    held = (part == PROP) | ((part == GLOW) & (tags < 0) & (look["prop"] == "tablet"))
    rig[np.isin(part, (ARM_UPPER, FOREARM, PAW)) | held] = RIG_ARM
    rig[(part == FOREARM_WAVE) | (part == PAW_WAVE)] = RIG_WAVE
    rig[part == TORSO] = RIG_TORSO
    return rig


# Both LODs of every resident actor, with a few spare for portraits.
MESH_CACHE = 32
# The Skipper's look and the creator's draft (both LODs), keyed by the look itself.
LOOK_CACHE = 6
_largest = [0]


def _freeze(mesh: CatMesh) -> CatMesh:
    # Cached meshes are shared by actors, portraits and both renderers: keep them read-only.
    for value in (mesh.coat, mesh.coat_normals, mesh.part, mesh.along, mesh.triangles, mesh.tags, mesh.rig,
                  *mesh.positions.values(), *mesh.normals.values()):
        value.setflags(write=False)
    _largest[0] = max(_largest[0], mesh.nbytes)
    return mesh


@lru_cache(maxsize=MESH_CACHE)
def _cached(npc_id: str, lod: int) -> CatMesh:
    from .content import load_content_v2

    return _freeze(_assemble(load_content_v2().roster[npc_id]["appearance"], lod))


def cat_mesh(npc_id: str, lod: int = LOD0) -> CatMesh:
    """The cached mesh of roster cat `npc_id` (Pip & Pebble's is one mesh) at `lod`."""
    return _cached(npc_id, lod)


@lru_cache(maxsize=LOOK_CACHE)
def _look_cached(key: str, lod: int) -> CatMesh:
    return _freeze(_assemble(json.loads(key), lod))


def look_mesh(look: dict, lod: int = LOD0) -> CatMesh:
    """The cached mesh for an appearance that is not in the roster (the Skipper's).

    Args:
        look: An npcs.json-style appearance (skipperlook.appearance builds one).
        lod: LOD0 or LOD1.

    Returns:
        A read-only CatMesh shared by every caller asking for an equal look.
    """
    return _look_cached(json.dumps(look, sort_keys=True), lod)


def cache_bytes_bound() -> int:
    """An upper bound on both mesh caches: their entries times the largest mesh built."""
    return (_cached.cache_info().currsize + _look_cached.cache_info().currsize) * _largest[0]


def clear_caches() -> None:
    """Drop every cached mesh (tests and memory checks start from empty)."""
    _cached.cache_clear()
    _look_cached.cache_clear()


# --- Coat patterns: the reference for shaders/cat.frag ---------------------------

def _hash3(p):
    # Quantize the occasional fractional salt before hashing; integer mixing
    # avoids backend-specific sin precision amplified by the old large scale.
    q = np.floor(p * np.float32(10.0) + np.float32(0.5)).astype(np.int32).astype(np.uint32)
    with np.errstate(over="ignore"):
        h = q[..., 0] * np.uint32(0x8DA6B343)
        h ^= q[..., 1] * np.uint32(0xD8163841)
        h ^= q[..., 2] * np.uint32(0xCB1AB31F)
        h ^= h >> np.uint32(16)
        h *= np.uint32(0x7FEB352D)
        h ^= h >> np.uint32(15)
        h *= np.uint32(0x846CA68B)
        h ^= h >> np.uint32(16)
    return (h >> np.uint32(8)).astype(np.float32) * np.float32(1.0 / 16777216.0)


def _noise3(p):
    i = np.floor(p)
    f = p - i
    f = f * f * (3 - 2 * f)
    out = 0.0
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                w = (np.where(dx, f[..., 0], 1 - f[..., 0]) * np.where(dy, f[..., 1], 1 - f[..., 1])
                     * np.where(dz, f[..., 2], 1 - f[..., 2]))
                out = out + w * _hash3(i + np.array([dx, dy, dz], np.float32))
    return out


def _smooth(edge0, edge1, x):
    t = np.clip((x - edge0) / (edge1 - edge0), 0, 1)
    return t * t * (3 - 2 * t)


def coat_weights(pattern, coat, coat_n, part, along, size=1.0):
    """Per-vertex (or per-pixel) weights (secondary, accent) for a coat pattern.

    `coat` is the neutral-pose position divided by the cat's size, so markings
    keep their scale on kittens and big cats alike.
    """
    p = np.asarray(coat, np.float32) / np.float32(size)
    n = np.asarray(coat_n, np.float32)
    part = np.asarray(part)
    along = np.asarray(along, np.float32)
    x, y, z = p[..., 0], p[..., 1], p[..., 2]
    sec = np.zeros(x.shape, np.float32)
    acc = np.zeros(x.shape, np.float32)
    belly = ((part == TORSO) | (part == RUFF)) & (n[..., 2] > 0.25) & (y < 0.36)
    chest = _smooth(0.15, 0.55, n[..., 2]) * ((part == TORSO) | (part == RUFF)) * (y < 0.40)
    muzzle = (part == MUZZLE).astype(np.float32)
    paws = ((part == PAW) | (part == PAW_WAVE) | (part == FOOT)).astype(np.float32)
    extremity = (((part == EAR) | (part == TAIL) | (part == PAW) | (part == PAW_WAVE) | (part == FOOT)
                  | (part == FOREARM) | (part == FOREARM_WAVE)).astype(np.float32)
                 + (part == LEG) * _smooth(0.5, 0.9, along))
    face = np.maximum((part == MUZZLE) * 1.0, (part == HEAD) * _smooth(0.55, 0.85, n[..., 2]) * (y < 0.51))
    wobble = _noise3(p * 18.0)
    if pattern == "tabby":
        # Classic swirls: rings around a bullseye on each flank, bars on legs and tail.
        r = np.hypot(np.abs(x) - 0.11, y - 0.22) + (wobble - 0.5) * 0.03
        swirl = np.abs(np.sin(r * 70.0)) < 0.45
        back = (np.abs(x) < 0.03) & (n[..., 2] < -0.2)
        rings = np.abs(np.sin(along * 22.0 + wobble * 2)) < 0.4
        brow = (part == HEAD) & (n[..., 2] > 0.2) & (y > 0.49) & (np.abs(np.sin(x * 160)) < 0.35)
        sec = np.where(part == TORSO, (swirl | back) & ~belly, 0.0)
        sec = np.where((part == TAIL) | (part == LEG) | (part == ARM_UPPER) | (part == FOREARM) |
                       (part == FOREARM_WAVE), rings, sec)
        sec = np.where(brow, 1.0, sec)
    elif pattern == "mackerel":
        # Narrow stripes falling from a dark spine.
        stripe = np.abs(np.sin(y * 95.0 + (wobble - 0.5) * 2.0 + np.abs(x) * 10)) < 0.32
        spine = (np.abs(x) < 0.025) & (n[..., 2] < -0.1)
        rings = np.abs(np.sin(along * 26.0 + wobble * 2)) < 0.38
        sec = np.where((part == TORSO) | (part == HEAD), (stripe | spine) & ~belly & ~(face > 0.5), 0.0)
        sec = np.where((part == TAIL) | (part == LEG) | (part == ARM_UPPER) | (part == FOREARM) |
                       (part == FOREARM_WAVE), rings, sec)
    elif pattern == "spotted":
        cell = np.floor(p * 26.0)
        local = p * 26.0 - cell - (0.25 + 0.5 * np.stack([_hash3(cell), _hash3(cell + 7.1), _hash3(cell + 3.3)], -1))
        spot = (np.linalg.norm(local, axis=-1) < 0.32) & (_hash3(cell + 1.7) > 0.3)
        sec = np.where(part == TAIL, np.abs(np.sin(along * 22.0)) < 0.35, spot & ~belly).astype(np.float32)
    elif pattern in ("calico", "tortoiseshell"):
        patches = _noise3(p * (9.0 if pattern == "calico" else 22.0)) + (wobble - 0.5) * 0.3
        sec = (patches > (0.55 if pattern == "calico" else 0.5)).astype(np.float32)
        if pattern == "calico":
            dark = _noise3(p * 9.0 + 13.0) > 0.62
            acc = (dark & (sec < 0.5)).astype(np.float32)
            # The calico's white is the base: the belly, legs and paws stay white.
            low = (belly | (part == LEG) | (part == FOOT) | (part == PAW) | (part == PAW_WAVE) | (part == MUZZLE)
                   | (part == ARM_UPPER) | (part == FOREARM) | (part == FOREARM_WAVE))
            sec = np.where(low, 0.0, sec)
            acc = np.where(low, 0.0, acc)
        else:
            acc = (_noise3(p * 40.0 + 5.0) > 0.72).astype(np.float32) * (1 - sec)
    elif pattern == "tuxedo":
        acc = np.maximum.reduce([chest, muzzle, paws])
    elif pattern == "bicolor":
        acc = np.maximum.reduce([chest, muzzle, paws, (part == LEG) * _smooth(0.3, 0.6, along),
                                 (part == HEAD) * _smooth(0.2, 0.5, n[..., 2]) * (y < 0.47)])
    elif pattern == "point":
        sec = np.clip(extremity + face * 0.9, 0, 1)
    return sec.astype(np.float32), acc.astype(np.float32)


def coat_rgb(look, coat, coat_n, part, along):
    """Linear fur RGB for each vertex or pixel, before lighting (eyes, nose and inner ears too)."""
    colors = look["colors"]
    base, sec_c, acc_c = (np.asarray(colors[k], np.float32) for k in ("base", "secondary", "accent"))
    sec, acc = coat_weights(look["pattern"], coat, coat_n, part, along, size=float(look["size"]))
    rgb = base * (1 - sec - acc)[..., None] + sec_c * sec[..., None] + acc_c * acc[..., None]
    part = np.asarray(part)
    pink = np.array([0.86, 0.52, 0.56], np.float32)
    dark_nose = float(np.mean(base)) < 0.3
    rgb = np.where((part == NOSE)[..., None], np.array([0.20, 0.14, 0.14], np.float32) if dark_nose else pink, rgb)
    rgb = np.where((part == INNER_EAR)[..., None], pink, rgb)
    rgb = np.where((part == WHISKER)[..., None], np.array([0.95, 0.94, 0.90], np.float32), rgb)
    rgb = np.where((part == EYE)[..., None], np.asarray(look["eyes"], np.float32), rgb)
    rgb = np.where((part == PUPIL)[..., None], np.array([0.05, 0.05, 0.06], np.float32), rgb)
    return rgb.astype(np.float32)


FUR_PARTS = (TORSO, HEAD, MUZZLE, EAR, ARM_UPPER, FOREARM, PAW, LEG, FOOT, TAIL, RUFF, FOREARM_WAVE, PAW_WAVE)
PROP_COLOURS = {"rod": (0.45, 0.32, 0.20), "book": (0.62, 0.20, 0.18), "brush": (0.55, 0.40, 0.25),
                "whittle": (0.72, 0.58, 0.38), "mug": (0.86, 0.84, 0.78), "tablet": (0.55, 0.85, 1.0),
                "none": (0.5, 0.5, 0.5)}


def paint(mesh: CatMesh) -> tuple[np.ndarray, np.ndarray]:
    """Per-vertex RGB and emission for a whole actor: fur, eyes, attire, props and lanterns."""
    rgb = np.empty((len(mesh.part), 3), np.float32)
    glow = np.zeros(len(mesh.part), np.float32)
    for look, lo, hi in mesh.cats:
        part, tags = mesh.part[lo:hi], mesh.tags[lo:hi]
        colour = coat_rgb(look, mesh.coat[lo:hi], mesh.coat_normals[lo:hi], part, mesh.along[lo:hi])
        for index, item in enumerate(look["attire"]):
            colour[(tags == index) & (part == ATTIRE)] = item["color"]
            # A parka's fur trim stays its own white.
            colour[(tags == index) & (part == RUFF) & (item["kind"] == "parka")] = (0.95, 0.94, 0.90)
        colour[part == PROP] = PROP_COLOURS[look["prop"]]
        lantern = next((item["color"] for item in look["attire"] if item["kind"] == "lantern"), None)
        lit = part == GLOW
        for index, item in enumerate(look["attire"]):
            if item["kind"] == "goggles":
                colour[(tags == index) & lit] = (0.55, 0.85, 0.95)
            elif item["kind"] == "lantern":
                colour[(tags == index) & lit] = lantern
        props = lit & (tags < 0)
        colour[props] = (0.95, 0.92, 0.84) if look["prop"] == "brush" else (0.55, 0.85, 1.0)
        glow[lo:hi][lit] = 1.0
        if look.get("glow"):
            sec, _acc = coat_weights(look["pattern"], mesh.coat[lo:hi], mesh.coat_normals[lo:hi], part,
                                     mesh.along[lo:hi], size=float(look["size"]))
            fur = np.isin(part, FUR_PARTS)
            glow[lo:hi] = np.maximum(glow[lo:hi], np.where(fur, sec * float(look["glow"]), 0.0))
        rgb[lo:hi] = colour
    return rgb, glow


# shaders/cat.vert's vertex layout: two poses to blend, the neutral coat frame and the paint.
VERTEX_FORMAT = "3f 3f 3f 3f 3f 3f 3f 1f 1f 1f 1f"
VERTEX_ATTRIBUTES = ("in_pos_a", "in_pos_b", "in_nrm_a", "in_nrm_b", "in_coat", "in_coat_n", "in_color",
                     "in_part", "in_along", "in_glow", "in_rig")


def vertex_block(mesh: CatMesh) -> np.ndarray:
    """(n, 25) float32 vertices in VERTEX_FORMAT: the idle pose, its gesture pose and the paint."""
    pose, gesture = slots(mesh)
    pos_a, nrm_a = mesh.positions[pose], mesh.normals[pose]
    pos_b, nrm_b = mesh.positions.get(gesture, pos_a), mesh.normals.get(gesture, nrm_a)
    rgb, glow = paint(mesh)
    return np.concatenate([pos_a, pos_b, nrm_a, nrm_b, mesh.coat, mesh.coat_normals, rgb, mesh.part[:, None],
                           mesh.along[:, None], glow[:, None], mesh.rig[:, None]], 1).astype(np.float32)
