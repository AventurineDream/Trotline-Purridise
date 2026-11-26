"""Small deterministic shore details; decorative and outside the boating routes.

Each lake keeps its own arrangement: a seed, a cycle of plant clusters that sets which
kinds stand where along its bank, and its own waders. The details share the existing
sprite atlas. No new obstacles, downloads or simulation entities are created, and each
lake has a fixed maximum of MAX_SHORE_DETAILS detail instances.
"""

from __future__ import annotations

import math
import numpy as np

# Above the densest bank's count (Flathead, about 500 details), so the cap never trims a lake.
# Each detail is one prop row and one instanced quad, so the cap still bounds draw calls and memory.
MAX_SHORE_DETAILS = 560

# Seeds are per lake, so no two lakes share a shore arrangement even where kinds match.
SHORE_SEED = {"briar": 31407, "cedar": 31829, "flathead": 31847, "crater": 31863}

# A cluster is (kind, sides, offset, height). For each entry of `sides` (metres along the
# bank) the detail sits `offset` metres inland (negative is into the water) and is `height`
# metres tall. `offset` and `height` are (lo, hi) ranges drawn uniformly. A lake repeats its
# cycle of clusters along the coast, so each bank has a rhythm of its own.
SHORE_CYCLES = {
    # Woodland cove: reed fringe, grass, flowers, shrub hedges, driftwood and stones.
    "briar": (
        (("cattail", (-1.5, 0.9, 2.6), (-1.8, -0.4), (1.5, 2.4)),),
        (("grass", (-1.7, 1.6), (1.0, 3.0), (0.6, 1.0)),),
        (("flowers", (-1.2, 1.3), (2.0, 5.0), (0.7, 1.1)),),
        (("shrub", (-1.5, 1.8), (4.0, 10.0), (1.6, 2.9)),),
        (("driftwood", (0.0,), (0.8, 2.2), (0.55, 0.85)),
         ("grass", (2.0,), (2.0, 4.0), (0.7, 1.05))),
        (("shore_stone", (-1.1, 1.5), (0.3, 1.4), (0.4, 0.7)),),
        (("grass", (-1.7, 1.6), (1.0, 3.0), (0.6, 1.0)),
         ("flowers", (0.0,), (2.0, 5.0), (0.65, 1.0))),
        (("cattail", (-1.5, 0.9, 2.6), (-1.8, -0.4), (1.5, 2.4)),
         ("shrub", (0.0,), (4.0, 8.0), (1.5, 2.5))),
    ),
    # Creek mud and flooded cypress: reed beds, dwarf palmetto understory and drift logs.
    "cedar": (
        (("cattail", (-1.5, 0.9, 2.6), (-1.8, -0.4), (1.5, 2.4)),),
        (("palmetto", (-1.9, 1.9), (1.0, 3.0), (0.9, 1.3)),),
        (("grass", (-1.7, 1.6), (1.0, 3.0), (0.6, 1.0)),),
        (("driftwood", (0.0,), (0.8, 2.2), (0.55, 0.85)),
         ("palmetto", (2.4,), (2.0, 4.0), (0.8, 1.1))),
        (("cattail", (-1.2, 1.4), (-1.6, -0.5), (1.4, 2.2)),
         ("grass", (0.0,), (1.0, 2.0), (0.6, 0.9))),
        (("palmetto", (-1.9, 1.9), (1.0, 3.0), (0.9, 1.3)),),
        (("grass", (-1.7, 1.6), (1.0, 3.0), (0.6, 1.0)),
         ("driftwood", (2.5,), (1.0, 2.0), (0.5, 0.8))),
        (("cattail", (-1.5, 0.9, 2.6), (-1.8, -0.4), (1.5, 2.4)),
         ("palmetto", (0.0,), (3.0, 5.0), (0.9, 1.2))),
    ),
    # Glacial reef: erratic boulders, alpine flowers, grass tufts and cattail-fringed bays.
    "flathead": (
        (("shore_stone", (-1.1, 1.5), (0.3, 1.4), (0.4, 0.7)),),
        (("grass", (-1.7, 1.6, 2.4), (1.0, 3.0), (0.6, 1.0)),),
        (("flowers", (-1.2, 1.3), (2.0, 5.0), (0.7, 1.1)),),
        (("cattail", (-1.5, 0.9, 2.6), (-1.8, -0.4), (1.5, 2.4)),),
        (("shore_stone", (-1.1,), (0.3, 1.4), (0.4, 0.7)),
         ("grass", (1.5,), (2.0, 4.0), (0.7, 1.05))),
        (("flowers", (0.0,), (2.0, 5.0), (0.65, 1.0)),
         ("grass", (-1.7, 1.6), (1.0, 3.0), (0.6, 1.0))),
        (("grass", (-1.7, 1.6), (1.0, 3.0), (0.6, 1.0)),
         ("flowers", (-1.2,), (2.0, 5.0), (0.7, 1.1))),
        (("shore_stone", (-1.1, 1.5), (0.3, 1.4), (0.4, 0.7)),
         ("cattail", (2.6,), (-1.8, -0.4), (1.5, 2.4))),
    ),
    # Pumice shelf by the warm springs: stones and drift logs, sparse grass and spring flowers.
    "crater": (
        (("shore_stone", (-1.1, 1.5), (0.3, 1.4), (0.4, 0.7)),),
        (("grass", (-1.7, 1.6), (1.0, 3.0), (0.6, 1.0)),),
        (("flowers", (-1.2, 1.3), (2.0, 5.0), (0.7, 1.1)),),
        (("shore_stone", (-1.1, 1.5), (0.3, 1.4), (0.4, 0.7)),
         ("grass", (0.0,), (2.0, 4.0), (0.7, 1.0))),
        (("driftwood", (0.0,), (0.8, 2.2), (0.55, 0.85)),),
        (("shore_stone", (-1.1, 1.5), (0.3, 1.4), (0.4, 0.7)),),
        (("grass", (-1.7, 1.6), (1.0, 3.0), (0.6, 1.0)),
         ("flowers", (0.0,), (2.0, 5.0), (0.65, 1.0))),
        (("shore_stone", (-1.1,), (0.3, 1.4), (0.4, 0.7)),
         ("driftwood", (2.0,), (1.0, 2.5), (0.5, 0.8))),
    ),
}

# Each lake's own waders in its shallows, cycled along the sampled birds.
SHORE_BIRDS = {
    "briar": ("heron", "duck"),
    "cedar": ("heron", "duck"),
    "flathead": ("duck",),
    "crater": ("heron",),
}


def _coast_samples(world, rng):
    if world.id == "briar":
        # Rays from the lake centre find the water edge the simulation uses. The 165 rays sit
        # about 2.2 degrees apart; each angle jitters by at most 0.018 rad (about 1 degree), so
        # the spokes are not evenly spaced. Each ray bisects [0, 900] world units for 24 steps.
        # The bracket assumes the centre is water and every ray reaches land before 900 units;
        # a ray still in water at 900 returns 900. These values are fixed: changing one moves
        # Briar's shore plants and waders, which no test pins by position.
        angles = np.linspace(-math.pi, math.pi, 165, endpoint=False)
        angles += rng.uniform(-0.018, 0.018, len(angles))
        nx, nz = np.cos(angles), np.sin(angles)
        lo, hi = np.zeros(len(angles)), np.full(len(angles), 900.0)
        for _ in range(24):
            mid = (lo+hi)*0.5
            land = world.shore_sd(nx*mid, nz*mid) >= 0
            hi, lo = np.where(land,mid,hi), np.where(land,lo,mid)
        radius = (lo+hi)*0.5
        return np.stack([nx*radius,nz*radius,nx,nz],axis=1)

    coast = world.coast
    # 140 survey draws along the coastline, then 12 draws from the coast points within 230
    # world units of each named zone, so the fishing coves get denser shore detail. Fixed
    # seeds keep repeated lake loads and saves identical.
    indices = list(rng.integers(0,len(coast),140))
    for _,x,z,_ in world.zones:
        near = np.flatnonzero(np.hypot(coast[:,0]-x,coast[:,1]-z)<230)
        if len(near):
            indices.extend(rng.choice(near,size=12,replace=True))
    return coast[np.asarray(indices,dtype=np.int32)]


def _clear_route(world, x, z):
    a, s = world.slip.local(x,z)
    # Preserve the complete marina envelope and its central launch approach.
    if -55 < float(a) < 65 and abs(float(s)) < 70:
        return False
    if world.id == "cedar" and math.hypot(x-181.25,z+858.36) < 35:
        return False
    return not bool(world.slip.contains(x,z))


def shoreline_props(world, prop_type):
    """Return a bounded list of non-colliding Prop records for this lake.

    Args:
        world: The lake's `World`; its id selects the seed, plant cycle and birds.
        prop_type: The `Prop` record class to build the details with.

    Returns:
        At most MAX_SHORE_DETAILS `prop_type` records, each clear of the boating routes
        and landings and placed on the shallow margin (waders) or the dry shore (plants).
    """
    rng = np.random.default_rng(SHORE_SEED[world.id])
    cycle = SHORE_CYCLES[world.id]
    samples = _coast_samples(world,rng)
    result = []
    positions = set()

    def add(kind, cx, cz, nx, nz, offset, tangent, height):
        if len(result)>=MAX_SHORE_DETAILS:
            return
        x, z = float(cx+nx*offset-nz*tangent), float(cz+nz*offset+nx*tangent)
        if not _clear_route(world,x,z):
            return
        sd = float(world.shore_sd(x,z))
        wet = kind in ("cattail","heron","duck")
        if wet:
            # Waders and emergent plants stay in the shallow bank margin.
            if sd < -3.8 or sd > 0.35 or float(world.depth(x,z)) > 1.25:
                return
        elif sd < 0.15 or sd > 17:
            return
        key = (int(x*0.5),int(z*0.5),kind)
        if key in positions:
            return
        positions.add(key)
        result.append(prop_type(kind,x,z,float(height),float(rng.uniform(0.88,1.06))))

    for i,(x,z,nx,nz) in enumerate(samples):
        jitter = float(rng.uniform(-2.0,2.0))
        for kind, sides, offset, height in cycle[i % len(cycle)]:
            for side in sides:
                add(kind,x,z,nx,nz,rng.uniform(*offset),jitter+side,rng.uniform(*height))

    # A handful of quiet birds reward exploring the shore without becoming
    # obstacles or occupying the clear routes into either landing.
    birds = SHORE_BIRDS[world.id]
    for i,(x,z,nx,nz) in enumerate(samples[::11]):
        kind = birds[i % len(birds)]
        add(kind,x,z,nx,nz,-rng.uniform(0.6,2.0),rng.uniform(-1,1),1.35 if kind=="heron" else 0.48)
    return result
