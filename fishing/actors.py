"""Visible cats (V1-29): where each present cat sits, its boat, LOD and the budget.

Every present cat is an *actor*: its rig in one or two poses (its own idle and
the wave it blends to as the player comes within 40 m), seated on its family
boat at its anchor, or standing on its landing's pier if it is a host. Actors
are resident only for the loaded lake and at most `MAX_ACTORS` at once; their
CPU bytes are counted against `ACTOR_BUDGET`. `pose_state` is the one source
of animation parameters for the GL vertex shader and the CPU `animate`.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from functools import lru_cache
import math
import zlib

import numpy as np

from . import catmesh
from .catmesh import LOD0, LOD1, RIG_EAR, RIG_HEAD, RIG_TAIL, RIG_TORSO, RIG_WAVE

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

    def mesh(self, lod: int) -> catmesh.CatMesh:
        if lod not in self.meshes:
            self.meshes[lod] = catmesh.cat_mesh(self.npc_id, lod)
        return self.meshes[lod]

    @property
    def look(self) -> dict:
        return self.mesh(LOD1).cats[0][0]

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


def _smoothstep(edge0, edge1, x):
    t = min(max((x - edge0) / (edge1 - edge0), 0.0), 1.0)
    return t * t * (3 - 2 * t)


def pose_state(actor: Actor, player_x: float, player_z: float, anim: float, reduced_motion: bool) -> dict:
    """Animation parameters: the wave blend, head turn, breathing, tail sway, ear flick and wave."""
    dx, dz = player_x - actor.x, player_z - actor.z
    distance = math.hypot(dx, dz)
    near = 1.0 - _smoothstep(WAVE_RANGE - 10.0, WAVE_RANGE, distance)
    look = actor.look
    # The angle from the cat's facing to the player, clamped to a comfortable turn.
    bearing = math.atan2(dx, dz) - actor.yaw
    bearing = (bearing + math.pi) % math.tau - math.pi
    head_yaw = max(-1.1, min(1.1, bearing)) * near
    t = 0.0 if reduced_motion else float(anim)
    seed = actor.seed * 17.0
    flick_phase = (t * 0.14 + actor.seed) % 1.0
    flick = 0.0 if reduced_motion else max(0.0, math.sin(min(flick_phase, 0.04) / 0.04 * math.pi)) * (flick_phase < 0.04)
    return {
        "blend": near if look["pose"] != "wave" else 0.0,
        "head_yaw": head_yaw,
        "breath": 0.0 if reduced_motion else 0.012 * math.sin(math.tau * 0.22 * t + seed),
        "tail": 0.0 if reduced_motion else 0.06 * float(look["size"]),
        "tail_phase": math.tau * 0.35 * t + seed,
        "flick": flick,
        "wave": 0.0 if reduced_motion else 0.45 * math.sin(math.tau * 1.5 * t),
        "distance": distance,
        "reduced": reduced_motion,
        "t": t,
    }


def shader_uniforms(actor: Actor, mesh: catmesh.CatMesh, params: dict) -> dict:
    """shaders/cat.vert's per-actor uniforms for this frame's pose_state()."""
    look = mesh.cats[0][0]
    size = float(look["size"])
    base = look["pose"]
    wave_weight = 1.0 if base == "wave" else params["blend"]
    elbow = mesh.elbow[base] * (1 - wave_weight) + mesh.elbow.get("wave", mesh.elbow[base]) * wave_weight
    return dict(actor_pos=(actor.x, actor.y, actor.z), actor_yaw=actor.yaw, blend=params["blend"],
                head_yaw=params["head_yaw"], breath=params["breath"], tail=params["tail"],
                tail_phase=params["tail_phase"], flick=params["flick"], wave=params["wave"],
                wave_weight=wave_weight, neck=tuple(float(v) for v in catmesh.NECK * size),
                elbow=tuple(float(v) for v in elbow), cat_size=size)


def _rotate_y(points, pivot, angle):
    c, s = math.cos(angle), math.sin(angle)
    d = points - pivot
    return np.stack([d[:, 0] * c + d[:, 2] * s, d[:, 1], -d[:, 0] * s + d[:, 2] * c], 1) + pivot


def _rotate_z(points, pivot, angle):
    c, s = math.cos(angle), math.sin(angle)
    d = points - pivot
    return np.stack([d[:, 0] * c - d[:, 1] * s, d[:, 0] * s + d[:, 1] * c, d[:, 2]], 1) + pivot


def animate(mesh: catmesh.CatMesh, params: dict) -> tuple[np.ndarray, np.ndarray]:
    """Posed, animated vertices in the cat's frame: the CPU twin of shaders/cat.vert."""
    look = mesh.cats[0][0]
    base = look["pose"]
    weights = {base: 1.0} if base == "wave" else {base: 1.0 - params["blend"], "wave": params["blend"]}
    pos, nrm = mesh.blend(weights)
    pos = pos.copy()
    rig = mesh.rig
    size = float(look["size"])
    torso = rig == RIG_TORSO
    pos[torso, 0] *= 1.0 + params["breath"]
    pos[torso, 2] *= 1.0 + params["breath"]
    tail = rig == RIG_TAIL
    a = mesh.along[tail]
    pos[tail, 0] += params["tail"] * a ** 1.5 * np.cos(params["tail_phase"] - 2.5 * a)
    ear = rig == RIG_EAR
    pos[ear, 2] -= params["flick"] * mesh.along[ear] * 0.03 * size
    elbow = sum(mesh.elbow[p] * w for p, w in weights.items())
    wave_w = weights.get("wave", 0.0)
    arm = rig == RIG_WAVE
    if wave_w > 0 and arm.any():
        pos[arm] = _rotate_z(pos[arm], elbow, params["wave"] * wave_w)
    head = (rig == RIG_HEAD) | ear
    if params["head_yaw"] and head.any():
        pivot = catmesh.NECK * size
        pos[head] = _rotate_y(pos[head], pivot, params["head_yaw"])
        nrm = nrm.copy()
        nrm[head] = _rotate_y(nrm[head], np.zeros(3, np.float32), params["head_yaw"])
    return pos.astype(np.float32), nrm
