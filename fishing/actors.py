"""Visible cats (V1-29): where each present cat sits, its boat, LOD and the budget.

Every present cat is an *actor*: its rig in one or two poses (its own idle and
the gesture it blends to as the player comes within 40 m), seated on its family
boat at its anchor, or standing on its landing's pier if it is a host. Actors
are resident only for the loaded lake and at most `MAX_ACTORS` at once; their
CPU bytes are counted against `ACTOR_BUDGET`. `pose_state` is the one source
of animation parameters for the GL vertex shader and the CPU `animate`; the
idle life it composes (catmotion) is a pure function of the clock and the
cat's seed.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from functools import lru_cache
import math
import zlib

import numpy as np

from . import catmesh, catmotion
from .catmesh import (LOD0, LOD1, RIG_ARM, RIG_EAR, RIG_EAR_R, RIG_EYE, RIG_HEAD, RIG_STRIDE, RIG_TAIL, RIG_TORSO,
                      RIG_WAVE, HEAD_SCALE, PUPIL)

MAX_ACTORS = 14
ACTOR_BUDGET = 150 * 2 ** 20
LOD0_RANGE = 40.0
LOD1_RANGE = 120.0
WAVE_RANGE = 40.0
PIER_DECK = 0.555
MARINA_DECK = 0.53
FLOAT_DECK = 0.32
PIER_REACH = 12.0  # a dock anchor farther than this from any pier gets its own float


@lru_cache(maxsize=1)
def roster() -> dict:
    from .content import load_content_v2
    return load_content_v2().roster


def _seed(text: str) -> float:
    return (zlib.crc32(text.encode("utf-8")) & 0xFFFF) / 65535.0


@dataclass
class Actor:
    npc_id: str
    name: str
    x: float
    y: float
    z: float
    yaw: float            # the cat's facing: 0 looks along +z
    boat_id: str | None
    boat_paint: dict
    boat_faces: list = field(default_factory=list)
    seed: float = 0.0
    meshes: dict = field(default_factory=dict)
    appearance: dict | None = None  # a look outside the roster (the Skipper's); None reads npc_id's

    def mesh(self, lod: int) -> catmesh.CatMesh:
        """This actor's rig at `lod`, built once and kept (counted in `nbytes`)."""
        if lod not in self.meshes:
            self.meshes[lod] = (catmesh.cat_mesh(self.npc_id, lod) if self.appearance is None
                                else catmesh.look_mesh(self.appearance, lod))
        return self.meshes[lod]

    @property
    def look(self) -> dict:
        """The first cat's appearance (pose, prop, size, ...)."""
        return self.appearance if self.appearance is not None else self.mesh(LOD1).cats[0][0]

    def local_to_world(self, points: np.ndarray) -> np.ndarray:
        c, s = math.cos(self.yaw), math.sin(self.yaw)
        right = np.array([c, 0.0, -s], np.float32)
        forward = np.array([s, 0.0, c], np.float32)
        up = np.array([0.0, 1.0, 0.0], np.float32)
        basis = np.stack([right, up, forward])
        return points @ basis + np.array([self.x, self.y, self.z], np.float32)

    def nbytes(self) -> int:
        boat = sum(f.pts.nbytes + 24 for f in self.boat_faces)
        return sum(m.nbytes for m in self.meshes.values()) + boat


def _pier_spot(world, anchor):
    """The nearest standing point on a landing pier to a dock anchor, and its deck height."""
    sl = world.slip
    best = None
    rects = [(4.0, side * (sl.half_w + 0.85), 7.6, 0.5, PIER_DECK) for side in (-1, 1)]
    rects += [(f.a, f.s, max(f.half_a - 0.4, 0.1), max(f.half_s - 0.3, 0.1), MARINA_DECK)
              for f in getattr(world.marina, "footprints", ()) if f.kind == "pier"]
    a0, s0 = (float(v) for v in sl.local(anchor.x, anchor.z))
    for a, s, ha, hs, deck in rects:
        a1, s1 = min(max(a0, a - ha), a + ha), min(max(s0, s - hs), s + hs)
        d = math.hypot(a1 - a0, s1 - s0)
        if best is None or d < best[0]:
            best = (d, a1, s1, deck)
    distance, a, s, deck = best
    if distance > PIER_REACH:
        return None
    x, z = sl.world(a, s)
    # Face the open water, away from the land.
    return float(x), deck, float(z), math.atan2(-sl.ix, -sl.iz)


def _float_faces(x, z, yaw):
    """A small plank float for a host whose dock anchor has no pier nearby."""
    from .world import Face
    c, s = math.cos(yaw), math.sin(yaw)
    right, forward = np.array([c, 0, -s], np.float32), np.array([s, 0, c], np.float32)
    up = np.array([0, 1, 0], np.float32)
    faces = []
    for i in range(5):
        z0, z1 = -1.25 + i * 0.5, -1.25 + i * 0.5 + 0.46
        shade = 0.9 + 0.03 * (i % 3)
        corners = [np.array([x, FLOAT_DECK, z], np.float32) + right * u + forward * v
                   for u, v in ((-1.0, z0), (1.0, z0), (1.0, z1), (-1.0, z1))]
        faces.append(Face(np.array(corners, np.float32), up, np.array((0.56, 0.42, 0.27), np.float32) * shade,
                          "world"))
    for side in (-1.0, 1.0):
        for u, v in ((side, -1.25), (side, 1.25)):
            base = np.array([x, 0.0, z], np.float32) + right * u * 0.95 + forward * v * 0.95
            corners = [base + up * 0.02, base + right * 0.18 + up * 0.02, base + right * 0.18 + up * FLOAT_DECK,
                       base + up * FLOAT_DECK]
            faces.append(Face(np.array(corners, np.float32), forward, np.array((0.30, 0.31, 0.30), np.float32),
                              "world"))
    return faces


def place(npc, world, roster) -> Actor:
    row = roster[npc.id]
    seed = _seed(npc.id)
    anchor = npc.anchor
    if row["role"] == "host" or anchor.kind == "dock" or row["boat"] is None:
        spot = _pier_spot(world, anchor)
        if spot is not None:
            x, y, z, yaw = spot
            return Actor(npc.id, npc.name, x, y, z, yaw, None, {}, [], seed)
        yaw = _seed(anchor.id) * math.tau
        return Actor(npc.id, npc.name, anchor.x, FLOAT_DECK, anchor.z, yaw, None, {},
                     _float_faces(anchor.x, anchor.z, yaw), seed)
    from .boat import BOATS
    from .boatfamilies import npc_faces, seat
    # A steady heading per anchor: boats swing to the same breeze each day.
    yaw = _seed(anchor.id) * math.tau
    model = BOATS[row["boat"]]
    faces = npc_faces(row["boat"], anchor.x, anchor.z, yaw, row.get("boat_paint"))
    sx, sy, sz = seat(model)
    c, s = math.cos(yaw), math.sin(yaw)
    x = anchor.x + c * sx + s * sz
    z = anchor.z - s * sx + c * sz
    return Actor(npc.id, npc.name, float(x), float(model.eye_height + sy), float(z), yaw, row["boat"],
                 dict(row.get("boat_paint") or {}), faces, seed)


class ActorCache:
    """Resident actors for the loaded lake, at most MAX_ACTORS, least recently seen first out."""

    def __init__(self, world):
        self.world = world
        self.actors: OrderedDict[str, Actor] = OrderedDict()
        self._key = None

    def sync(self, npcs, roster) -> list[Actor]:
        key = tuple((n.id, n.anchor.id) for n in npcs if n.anchor.lake_id == self.world.id)
        if key != self._key:
            for npc_id, anchor_id in key:
                current = self.actors.get(npc_id)
                if current is None or getattr(current, "anchor_id", None) != anchor_id:
                    npc = next(n for n in npcs if n.id == npc_id)
                    actor = place(npc, self.world, roster)
                    actor.anchor_id = anchor_id
                    self.actors[npc_id] = actor
                self.actors.move_to_end(npc_id)
            while len(self.actors) > MAX_ACTORS:
                self.actors.popitem(last=False)
            self._key = key
        present = [npc_id for npc_id, _a in key][-MAX_ACTORS:]
        return [self.actors[npc_id] for npc_id in present if npc_id in self.actors]

    def nbytes(self) -> int:
        return sum(actor.nbytes() for actor in self.actors.values())


def memory_report(cache: ActorCache | None, gpu_bytes: int = 0, paint_bytes: int = 0) -> dict:
    """Bytes held for cat actors and portraits, against the 150 MiB budget (06 §7)."""
    from . import catart
    portraits = catart.portrait_bytes_bound()
    report = {
        "resident_actors": len(cache.actors) if cache is not None else 0,
        "max_actors": MAX_ACTORS,
        "resident_bytes": cache.nbytes() if cache is not None else 0,
        "mesh_cache_bytes_bound": catmesh.cache_bytes_bound(),
        "portrait_bytes_bound": portraits,
        "gpu_bytes": int(gpu_bytes),
        "software_paint_bytes": int(paint_bytes),
        "budget_bytes": ACTOR_BUDGET,
    }
    # An actor keeps its meshes after the cache drops them, so both terms count.
    report["total_bytes_bound"] = (report["resident_bytes"] + report["mesh_cache_bytes_bound"] + portraits
                                   + report["gpu_bytes"] + report["software_paint_bytes"])
    return report


def lod_for(distance: float) -> int | None:
    """LOD0 close, LOD1 to 120 m, then None: the impostor."""
    if distance < LOD0_RANGE:
        return LOD0
    if distance < LOD1_RANGE:
        return LOD1
    return None


def _int_seed(actor: Actor) -> int:
    return int(round(actor.seed * 65535.0))


def pose_state(actor: Actor, player_x: float | None, player_z: float | None, anim: float, reduced_motion: bool,
               *, gesture: float | None = None, steer: float = 0.0, attention: float = 1.0) -> dict:
    """This frame's animation parameters for one actor: the single source for cat.vert and `animate`.

    Args:
        actor: The cat (its pose, seed, place and facing).
        player_x, player_z: World point the cat attends to (the player's boat), or
            None when no one is near; within 40 m the cat turns to it, its ears
            perk and it blends to its gesture pose (catmesh.GESTURES).
        anim: The world clock in seconds (state.anim): idle life is a pure function of it.
        reduced_motion: Hold every clock-driven motion still (breath, blinks, ears,
            glances, tail, work loops, waving, weight shifts). The distance-driven
            gesture blend, head turn and ear perk stay: they answer the player.
        gesture: Overrides the distance blend (0-1): the Skipper's wave-back and the
            creator's hello.
        steer: -1..1 helm input; turns the wheel and leans the body (the Skipper).
        attention: 0-1 scale on the head's turn toward the point: the Skipper lowers it
            when cats on opposite sides pull its look both ways, so the head eases to
            centre instead of snapping across. Cats always pass 1.

    Returns:
        A dict of floats (angles in radians, lengths in metres at size 1) plus
        "distance", "reduced" and "t".
    """
    if player_x is None or player_z is None:
        dx = dz = 0.0
        distance = math.inf
    else:
        dx, dz = player_x - actor.x, player_z - actor.z
        distance = math.hypot(dx, dz)
    near = 1.0 - catmotion.smoother((distance - (WAVE_RANGE - 10.0)) / 10.0)
    look = actor.look
    pose, prop = look["pose"], look.get("prop", "none")
    gesture_pose = catmesh.GESTURES[pose]
    blend = 0.0 if gesture_pose is None else (near if gesture is None else min(max(gesture, 0.0), 1.0))
    # The angle from the cat's facing to the player, clamped to a comfortable turn; a player
    # straight behind is out of sight, so the head eases back rather than snapping across.
    bearing = (math.atan2(dx, dz) - actor.yaw + math.pi) % math.tau - math.pi
    track = (max(-1.1, min(1.1, bearing)) * near * min(max(float(attention), 0.0), 1.0)
             * (1.0 - catmotion.smooth((abs(bearing) - 2.3) / 0.6)))
    t = 0.0 if reduced_motion else float(anim)
    live = 0.0 if reduced_motion else 1.0
    seed = _int_seed(actor)
    asleep = pose == "nap_curl"
    quiet = (1.0 - near) * live  # glances and work give way to attention as the player comes near
    g_yaw, g_pitch, g_roll = catmotion.glance(t, seed, pose) if not asleep else (0.0, 0.0, 0.0)
    arm, forearm, work_pitch = catmotion.work(t, seed, pose, prop)
    breath, rise = catmotion.breath(t, seed, pose)
    sway, phase, curl = catmotion.tail(t, seed, pose)
    roll, pitch = catmotion.weight(t, seed, pose)
    if gesture_pose in ("wave", "helm_wave"):
        waving = blend
    elif pose == "wave":
        waving = max(catmotion.wave_bursts(t, seed), near)
    else:
        waving = 0.0
    work_w = (1.0 - blend) * live
    steer = min(max(float(steer), -1.0), 1.0) if pose == "helm" else 0.0
    wheel = arm * work_w + 0.55 * steer
    return {
        "blend": blend,
        "head_yaw": track + g_yaw * quiet,
        "head_pitch": g_pitch * quiet + work_pitch * work_w,
        # A curious tilt as the hello begins: distance-driven, so it stays with reduced motion.
        "head_roll": g_roll * quiet + 0.5 * blend * (1.0 - blend) * (0.0 if asleep else 1.0),
        "blink": catmotion.blink(t, seed) * live,
        "ear_l": catmotion.ear(t, seed, 1) * live,
        "ear_r": catmotion.ear(t, seed, -1) * live,
        "ear_perk": near,
        "breath": breath * live,
        "rise": rise * live,
        "tail": sway * live * (1.0 + 0.5 * blend),
        "tail_phase": phase,
        "tail_curl": curl * live,
        "tail_lift": (0.02 if asleep else 0.05) * blend,
        "forearm": (catmotion.wave(t) * waving + forearm * (1.0 - blend)) * live,
        "arm": wheel if pose == "helm" else arm * work_w,
        "body_roll": roll * live * (1.0 - 0.5 * blend) + (0.12 * wheel if pose == "helm" else 0.0),
        "body_pitch": pitch * live * (1.0 - 0.5 * blend),
        "distance": distance,
        "reduced": reduced_motion,
        "t": t,
    }


_SCALARS = ("blend", "head_yaw", "head_pitch", "head_roll", "blink", "ear_l", "ear_r", "ear_perk", "breath", "rise",
            "tail", "tail_phase", "tail_curl", "tail_lift", "forearm", "arm", "body_roll", "body_pitch")


def _rig_uniforms(mesh: catmesh.CatMesh, params: dict) -> dict:
    """The rig's per-cat pivots for this blend (two entries; a lone cat fills both)."""
    idle, gesture = catmesh.slots(mesh)
    w = params["blend"] if gesture is not None else 0.0
    a = mesh.pivots[idle]
    b = mesh.pivots[gesture] if gesture is not None else a
    out = {key: [] for key in ("neck", "elbow", "arm_pivot", "arm_axis", "head_up", "seat", "eye_open", "cat_yaw",
                               "cat_size")}
    for i in (0, 1):
        k = min(i, len(a) - 1)
        pa, pb = a[k], b[k]
        for key, attr in (("neck", "neck"), ("elbow", "elbow"), ("arm_pivot", "arm"), ("arm_axis", "arm_axis"),
                          ("head_up", "head_up"), ("seat", "seat")):
            value = getattr(pa, attr) * (1.0 - w) + getattr(pb, attr) * w
            out[key].append(tuple(float(v) for v in value))
        out["eye_open"].append(pa.eye_open * (1.0 - w) + pb.eye_open * w)
        out["cat_yaw"].append(float(pa.yaw))
        out["cat_size"].append(float(mesh.cats[k][0]["size"]))
    return out


def shader_uniforms(actor: Actor, mesh: catmesh.CatMesh, params: dict) -> dict:
    """shaders/cat.vert's per-actor uniforms for this frame's pose_state()."""
    return dict(actor_pos=(actor.x, actor.y, actor.z), actor_yaw=actor.yaw,
                **{key: float(params[key]) for key in _SCALARS}, **_rig_uniforms(mesh, params))


def _rotate(v: np.ndarray, axis: np.ndarray, angle) -> np.ndarray:
    """Rodrigues rotation of rows `v` about unit `axis` (one axis, or one per row) by `angle`."""
    c, s = np.cos(angle), np.sin(angle)
    axis = np.broadcast_to(axis, v.shape)
    c = np.reshape(c, (-1, 1)) if np.ndim(c) else c
    s = np.reshape(s, (-1, 1)) if np.ndim(s) else s
    dot = np.sum(axis * v, axis=1, keepdims=True)
    return v * c + np.cross(axis, v) * s + axis * dot * (1.0 - c)


def animate(mesh: catmesh.CatMesh, params: dict) -> tuple[np.ndarray, np.ndarray]:
    """Posed, animated vertices in the actor's frame: the CPU twin of shaders/cat.vert.

    Each step mirrors the shader's, in the same order; the test suite checks the
    two agree by transform feedback.
    """
    u = {key: np.asarray(value, np.float32) for key, value in _rig_uniforms(mesh, params).items()}
    idle, gesture = catmesh.slots(mesh)
    weights = {idle: 1.0} if gesture is None else {idle: 1.0 - params["blend"], gesture: params["blend"]}
    pos, nrm = mesh.blend(weights)
    pos, nrm = pos.copy(), nrm.copy()
    f = {key: np.float32(params[key]) for key in _SCALARS}
    index = np.floor((mesh.rig + 0.5) / RIG_STRIDE).astype(np.intp)
    ch = mesh.rig - RIG_STRIDE * index
    size = u["cat_size"][index]
    yaw = u["cat_yaw"][index]
    xa = np.stack([np.cos(yaw), np.zeros_like(yaw), -np.sin(yaw)], 1)
    za = np.stack([np.sin(yaw), np.zeros_like(yaw), np.cos(yaw)], 1)
    up = np.array([0.0, 1.0, 0.0], np.float32)

    def on(*channels):
        return np.isin(ch, channels)

    torso = on(RIG_TORSO)
    centre = u["neck"][index[torso]]
    pos[torso, 0] = centre[:, 0] + (pos[torso, 0] - centre[:, 0]) * (1.0 + f["breath"])
    pos[torso, 2] = centre[:, 2] + (pos[torso, 2] - centre[:, 2]) * (1.0 + f["breath"])
    tail = on(RIG_TAIL)
    a = mesh.along[tail]
    lateral = f["tail"] * a ** 1.5 * np.cos(f["tail_phase"] - 2.5 * a) + f["tail_curl"] * a * a * a
    pos[tail] += (xa[tail] * lateral[:, None] + up * (f["tail_lift"] * a * a)[:, None]) * size[tail, None]
    for channel, twitch, side in ((RIG_EAR, f["ear_l"], 1.0), (RIG_EAR_R, f["ear_r"], -1.0)):
        ear = on(channel)
        swivel = (-za[ear] * (0.03 * twitch) + xa[ear] * (side * 0.012 * twitch) + za[ear] * (0.004 * f["ear_perk"])
                  + up * (0.006 * f["ear_perk"]))
        pos[ear] += swivel * (mesh.along[ear] * size[ear])[:, None]
    eye = on(RIG_EYE)
    k = np.where(mesh.part[eye] == PUPIL, np.float32(0.016), np.float32(0.019))
    close = f["blink"] * u["eye_open"][index[eye]] * k * size[eye] * HEAD_SCALE * np.cos(np.pi * mesh.along[eye])
    pos[eye] -= u["head_up"][index[eye]] * close[:, None]
    head = on(RIG_HEAD, RIG_EAR, RIG_EAR_R, RIG_EYE)
    for axis, angle in ((za[head], f["head_roll"]), (xa[head], f["head_pitch"]), (up, f["head_yaw"])):
        pivot = u["neck"][index[head]]
        pos[head] = pivot + _rotate(pos[head] - pivot, axis, angle)
        nrm[head] = _rotate(nrm[head], axis, angle)
    pos[head, 1] += f["rise"] * size[head]
    wave = on(RIG_WAVE)
    pivot = u["elbow"][index[wave]]
    pos[wave] = pivot + _rotate(pos[wave] - pivot, za[wave], f["forearm"])
    nrm[wave] = _rotate(nrm[wave], za[wave], f["forearm"])
    arms = on(RIG_WAVE, RIG_ARM)
    pivot, axis = u["arm_pivot"][index[arms]], u["arm_axis"][index[arms]]
    pos[arms] = pivot + _rotate(pos[arms] - pivot, axis, f["arm"])
    nrm[arms] = _rotate(nrm[arms], axis, f["arm"])
    pos[arms, 1] += 0.6 * f["rise"] * size[arms]
    seat = u["seat"][index]
    for axis, angle in ((xa, f["body_pitch"]), (za, f["body_roll"])):
        pos = seat + _rotate(pos - seat, axis, angle)
        nrm = _rotate(nrm, axis, angle)
    return pos.astype(np.float32), nrm.astype(np.float32)
