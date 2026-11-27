"""The Skipper in first person (V1-29): two paws and a calm-water self-reflection.

Paws are a small mesh in the boat's eye frame (x to starboard, y up, z ahead), as
the cockpit meshes are. They hold the boat's tiller, oars or paddle, and the line
hand over hand while the haul screen is up. Where a boat's own control sits out of
view, the paws hold its in-view end: a tiller extension, the oar looms or the
paddle shaft. Wheel-steered boats show paws only for the haul.

The paws wear the Skipper's own coat (skipperlook): each forearm and mitt vertex is
painted by catmesh.coat_rgb at the coat coordinates of the matching vertex on the
rig's left forearm and paw, so a tuxedo Skipper has white mitts and a tabby has
ringed arms, exactly as the same cat would on the rig. The pink pads are drawn here
only (the rig has none).

The head is never drawn in the scene in first person. Only the reflection pass sees
its silhouette, placed so its mirror image lies on the water just past the bow, and
only when the boat sits idle on calm water. Views off the eye draw the whole rig
instead (skipperview.SkipperFigure), and neither paws nor silhouette.
"""

from __future__ import annotations

from functools import lru_cache
import json
import math

import numpy as np

from . import catmesh, skipperlook
from .boatmesh import tiller_grip
from .catmesh import _ellipsoid, _rot, _tube

PAD = np.array((0.78, 0.52, 0.52), np.float32)
WOOD = np.array((0.58, 0.42, 0.26), np.float32)
LINE = np.array((0.86, 0.82, 0.68), np.float32)
# The reflection is the coat in shadow, not black: near-black read as a hole in the
# water, or a dark creature standing on it (V1-42).
SHADOW = 0.55
# paw_mesh(parts=True) labels: the arm, the mitt (with toes), the pad, and what the paws hold.
PART_FOREARM, PART_MITT, PART_PAD, PART_GEAR = 0, 1, 2, 3

# Below this speed, with calm water, the Skipper's reflection shows.
IDLE_SPEED = 0.05


class _Mesh:
    def __init__(self):
        self.pos, self.nrm, self.rgb, self.tris, self.part = [], [], [], [], []
        self.count = 0

    def add(self, pos, nrm, faces, rgb, part=PART_GEAR):
        pos = np.asarray(pos, np.float32)
        self.pos.append(pos)
        self.nrm.append(np.asarray(nrm, np.float32))
        self.rgb.append(np.broadcast_to(np.asarray(rgb, np.float32), pos.shape).copy())
        self.tris.append(np.asarray(faces, np.int32).reshape(-1, 3) + self.count)
        self.part.append(np.full(len(pos), part, np.int8))
        self.count += len(pos)

    def arrays(self, parts=False):
        if not self.pos:
            empty = (np.zeros((0, 3), np.float32), np.zeros((0, 3), np.float32), np.zeros((0, 3), np.float32),
                     np.zeros((0, 3), np.int32))
            return empty + (np.zeros(0, np.int8),) if parts else empty
        out = (np.concatenate(self.pos), np.concatenate(self.nrm), np.concatenate(self.rgb),
               np.concatenate(self.tris))
        return out + (np.concatenate(self.part),) if parts else out


def grip_kind(state) -> str | None:
    """What the paws hold: haul, tiller, oars, tiller_oar, paddle, or None (a wheel)."""
    if getattr(state, "hauling", False):
        return "haul"
    if state.boat_id == "rowboat":
        return "tiller_oar" if state.rowboat_trolling_motor else "oars"
    if state.boat_id == "pontoon":
        return None
    return {"tiller": "tiller", "sail": "tiller", "oars": "oars", "paddle": "paddle"}.get(state.boat.power)


# The first-person arm and mitt share the rig's topology counts, so vertex i here is
# vertex i of the same primitive built on the rig's left forearm and paw.
_ARM_RINGS, _ARM_SIDES = 25, 8  # enough rings for a tabby's arm stripes to read as rings
_MITT, _TOE = (6, 8), (4, 6)


@lru_cache(maxsize=4)
def _paw_colours(look_key: str, side: int):
    """(forearm, mitt, toe) RGB for one first-person paw, painted from the rig's own arm.

    Args:
        look_key: The Skipper appearance as sorted JSON (a cache key).
        side: +1 the cat's left paw, -1 its right (mirrors the coat coordinates).

    Returns:
        Three float32 (n, 3) arrays matching `_paw`'s forearm tube, mitt and one toe.
    """
    look = json.loads(look_key)
    j = catmesh.POSE_JOINTS["sit_fish"]
    flip = np.array((side, 1.0, 1.0), np.float32)
    elbow, wrist = np.asarray(j["elbow_l"], np.float32) * flip, np.asarray(j["wrist_l"], np.float32) * flip
    points = elbow + (wrist - elbow) * np.linspace(0.0, 1.0, _ARM_RINGS)[:, None]
    pos, nrm, _f, along = _tube(points, np.full(_ARM_RINGS, 0.033), _ARM_SIDES, caps=False)
    # The rig's forearm runs 0.5 → 1 along its arm (catmesh.build).
    arm = catmesh.coat_rgb(look, pos, nrm, np.full(len(pos), catmesh.FOREARM), 0.5 + 0.5 * along)
    direction = (wrist - elbow) / np.linalg.norm(wrist - elbow)
    paw_c = wrist + direction * 0.022
    pos, nrm, _f, along = _ellipsoid(paw_c, (0.037, 0.03, 0.043), np.eye(3, dtype=np.float32), *_MITT)
    mitt = catmesh.coat_rgb(look, pos, nrm, np.full(len(pos), catmesh.PAW), along)
    pos, nrm, _f, along = _ellipsoid(paw_c + direction * 0.03, (0.012, 0.01, 0.012), np.eye(3, dtype=np.float32),
                                     *_TOE)
    toe = catmesh.coat_rgb(look, pos, nrm, np.full(len(pos), catmesh.PAW), along)
    return arm, mitt, toe


def _paw(m, wrist, toward, side, look_key):
    """A forearm from off-screen to `wrist`, then a mitt reaching along `toward`, in the Skipper's coat."""
    arm_rgb, mitt_rgb, toe_rgb = _paw_colours(look_key, side)
    toward = np.asarray(toward, np.float32)
    toward /= np.linalg.norm(toward) + 1e-8
    wrist = np.asarray(wrist, np.float32)
    elbow = wrist + np.array((side * 0.10, -0.30, -0.50), np.float32)
    points = elbow + (wrist - elbow) * np.linspace(0.0, 1.0, _ARM_RINGS)[:, None]
    pos, nrm, faces, _along = _tube(points, np.linspace(0.050, 0.040, _ARM_RINGS), _ARM_SIDES, caps=False)
    m.add(pos, nrm, faces, arm_rgb, PART_FOREARM)
    yaw = math.atan2(float(toward[0]), float(toward[2]))
    pitch = -math.asin(max(-1.0, min(1.0, float(toward[1]))))
    rot = _rot(pitch, yaw)
    centre = wrist + toward * 0.040
    pos, nrm, faces, _a = _ellipsoid(centre, (0.056, 0.036, 0.066), rot, *_MITT)
    m.add(pos, nrm, faces, mitt_rgb, PART_MITT)
    # Three toe bumps across the front of the mitt, and a pink pad peeking beneath.
    for k in (-1, 0, 1):
        toe = centre + rot @ np.array((k * 0.030, 0.010, 0.054), np.float32)
        pos, nrm, faces, _a = _ellipsoid(toe, (0.019, 0.016, 0.019), rot, *_TOE)
        m.add(pos, nrm, faces, toe_rgb * 0.97, PART_MITT)
    pad = centre + rot @ np.array((0.0, -0.029, 0.022), np.float32)
    pos, nrm, faces, _a = _ellipsoid(pad, (0.026, 0.009, 0.022), rot, 4, 6)
    m.add(pos, nrm, faces, PAD, PART_PAD)


def _stick(m, a, b, radius, rgb, samples=6):
    """A straight rod in short segments, so a near-plane cull drops only its hidden end."""
    a, b = np.asarray(a, np.float32), np.asarray(b, np.float32)
    points = a + (b - a) * np.linspace(0.0, 1.0, samples)[:, None]
    pos, nrm, faces, _a = _tube(points, np.full(samples, radius), 6)
    m.add(pos, nrm, faces, rgb)


def _tiller_pivot(state):
    """The grip a paw holds, in the eye frame: the boat's own control where it sits in view.

    The jon's is the far end of its tiller extension (boatmesh.tiller_grip). The arm swings with
    the outboard, and the grip follows the arm's tip, so the paw stays on it at every steer.
    """
    if state.boat_id == "jon":
        return tiller_grip(state.steer)
    if state.boat_id == "sail":
        return np.array((0.12 + state.steer * 0.14, -0.54, 0.68), np.float32)
    if state.boat_id == "rowboat":
        return np.array((0.50, -0.24, 0.89), np.float32)
    return np.array((0.05, -0.80, state.boat.stern + 0.5), np.float32)


def look_key(state) -> str:
    """The Skipper's rig appearance as sorted JSON: the cache key for its paws' colours."""
    return json.dumps(skipperlook.appearance(skipperlook.saved(state)), sort_keys=True)


def silhouette_rgb(state) -> np.ndarray:
    """The reflection's colour: the Skipper's base coat in shadow."""
    return (np.asarray(skipperlook.saved(state)["colors"]["base"], np.float32) * np.float32(SHADOW))


def mitt_rgb(state) -> tuple[float, float, float]:
    """The Skipper's mitt as one colour (0-1 RGB): the paw in the legendary photos.

    The median of the first-person right mitt, so a tuxedo shows its white glove and a
    tabby its coat, as the rig paints them. A tuple, so callers can use it as a cache key.
    """
    mitt = _paw_colours(look_key(state), -1)[1]
    return tuple(round(float(v), 4) for v in np.median(mitt, axis=0))


def paw_mesh(state, reduced_motion: bool = False, parts: bool = False):
    """(positions, normals, colours, triangles) of the Skipper's paws in the eye frame.

    With parts=True a fifth array labels each vertex PART_FOREARM, PART_MITT,
    PART_PAD or PART_GEAR (the tiller, oars, paddle or line).
    """
    kind = grip_kind(state)
    m = _Mesh()
    if kind is None:
        return m.arrays(parts)
    key = look_key(state)
    t = 0.0 if reduced_motion else float(state.anim)
    if kind == "haul":
        # Hand over hand: the line rises from the water past the bow to the paws.
        water = np.array((0.06, -1.25, 3.4), np.float32)
        near = np.array((-0.12, -0.10, 0.52), np.float32)
        _stick(m, near + (water - near) * 0.015, water, 0.008, LINE, 12)
        swing = 0.0 if reduced_motion else math.sin(t * math.tau * 0.9)
        for side, offset in ((1, 0.16 + 0.05 * swing), (-1, 0.07 - 0.05 * swing)):
            grip = near + (water - near) * offset
            _paw(m, grip + np.array((side * 0.02, 0.02, 0.0), np.float32), water - near, side, key)
        return m.arrays(parts)
    if kind in ("tiller", "tiller_oar"):
        pivot = _tiller_pivot(state)
        if state.boat_id == "jon":
            grip = pivot + np.array((0.0, 0.02, 0.0), np.float32)
        else:
            grip = np.array((0.32 - float(state.steer) * 0.10, -0.33, 0.90), np.float32)
            _stick(m, grip + (grip - pivot) * 0.06, pivot, 0.016, (0.13, 0.14, 0.15))
        _paw(m, grip + np.array((0.0, 0.02, -0.02), np.float32), grip - pivot + np.array((0, 0, 0.4)), 1, key)
    if kind in ("oars", "tiller_oar"):
        sides = (-1,) if kind == "tiller_oar" else (-1, 1)
        for side in sides:
            grip = np.array((side * 0.40, -0.31, 0.80), np.float32)
            if state.boat_id == "rowboat":
                lock = np.array((side * 0.59, -0.33, 0.96), np.float32)
            else:
                lock = np.array((side * 0.9, -0.55, -0.4), np.float32)
            _stick(m, grip - (lock - grip) * 0.15, lock, 0.020, WOOD)
            _paw(m, grip + np.array((0.0, 0.025, -0.01), np.float32), (side * 0.25, 0.0, 1.0), side, key)
    if kind == "paddle":
        top = np.array((0.16, -0.13, 0.80), np.float32)
        blade = np.array((1.10, -1.30, 2.50), np.float32)
        stroke = 0.0 if reduced_motion or abs(state.speed) < 0.2 else 0.05 * math.sin(t * math.tau * 0.6)
        top = top + np.array((0.0, 0.0, stroke), np.float32)
        _stick(m, top, blade, 0.018, WOOD, 8)
        _paw(m, top + np.array((0.0, 0.03, 0.0), np.float32), (0.1, 0.1, 1.0), -1, key)
        _paw(m, top + (blade - top) * 0.26 + np.array((0.0, 0.03, 0.0), np.float32), (0.3, 0.0, 1.0), 1, key)
    return m.arrays(parts)


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

    Args:
        state: Live game state, including the saved Skipper look and boat eye height.

    Returns:
        Positions in world metres, unit normals, RGB colours and triangle indices
        for the reflection's simplified head and ear outline.
    """
    m = _Mesh()
    look = skipperlook.saved(state)
    shade = silhouette_rgb(state)
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
    m.add(pos, nrm, faces, shade)
    # The ear tips follow the Skipper's ears: the outline is all the mirror shows of them.
    tip_x, tip_y = {"pointed": (0.13, 0.26), "rounded": (0.14, 0.22), "tufted": (0.12, 0.30),
                    "folded": (0.17, 0.16), "folded_left": (0.17, 0.16),
                    "folded_right": (0.17, 0.16)}[look["ears"]]
    # Mirror the same cat-relative sweep as the shared rig, rather than splaying both tips.
    sweep = 0.05 if look["ears"] == "folded_left" else -0.05 if look["ears"] == "folded_right" else 0.0
    for side in (-1, 1):
        inner = centre + rot @ (np.array((side * 0.03, 0.12, 0.0), np.float32) * s)
        outer = centre + rot @ (np.array((side * 0.14, 0.08, 0.0), np.float32) * s)
        tip = centre + rot @ (np.array((side * tip_x + sweep, tip_y, 0.0), np.float32) * s)
        ear = np.stack([inner, outer, tip, inner, outer, tip])
        m.add(ear, np.broadcast_to(-forward, ear.shape), [(0, 1, 2), (3, 5, 4)], shade)
    return m.arrays()
