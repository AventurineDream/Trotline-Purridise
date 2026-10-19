"""Small deterministic shore details; decorative and outside the boating routes.

These share the existing sprite atlas. No new obstacles, downloads or simulation
entities are created, and each lake has a fixed maximum of 440 detail instances.
"""

from __future__ import annotations

import math
import numpy as np

MAX_SHORE_DETAILS = 440


def _coast_samples(world, rng):
    if world.id == "briar":
        # Locate the same procedural water boundary used by the simulation.
        angles = np.linspace(-math.pi, math.pi, 132, endpoint=False)
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
    # Survey coastline plus extra detail in the named fishing coves. Sampling
    # with fixed seeds keeps repeated lake changes and save loads identical.
    indices = list(rng.integers(0,len(coast),110))
    for _,x,z,_ in world.zones:
        near = np.flatnonzero(np.hypot(coast[:,0]-x,coast[:,1]-z)<230)
        if len(near):
            indices.extend(rng.choice(near,size=10,replace=True))
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
    """Return a bounded list of non-colliding Prop records for this lake."""
    rng = np.random.default_rng(31407 if world.id == "briar" else 31829)
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
        pattern = i%8
        jitter = float(rng.uniform(-2.0,2.0))
        if pattern in (0,7):
            for side in (-1.5,0.9,2.6):
                add("cattail",x,z,nx,nz,-float(rng.uniform(0.4,1.8)),jitter+side,rng.uniform(1.5,2.4))
            if pattern==7:
                add("shrub",x,z,nx,nz,rng.uniform(4,8),jitter,rng.uniform(1.5,2.5))
        elif pattern in (1,6):
            for side in (-1.7,1.6):
                add("grass",x,z,nx,nz,rng.uniform(1,3),jitter+side,rng.uniform(0.6,1.0))
            if pattern==6:
                add("flowers",x,z,nx,nz,rng.uniform(2,5),jitter,rng.uniform(0.65,1.0))
        elif pattern==2:
            for side in (-1.2,1.3):
                add("flowers",x,z,nx,nz,rng.uniform(2,5),jitter+side,rng.uniform(0.7,1.1))
        elif pattern==3:
            for side in (-1.5,1.8):
                add("shrub",x,z,nx,nz,rng.uniform(4,10),jitter+side,rng.uniform(1.6,2.9))
        elif pattern==4:
            add("driftwood",x,z,nx,nz,rng.uniform(0.8,2.2),jitter,rng.uniform(0.55,0.85))
            add("grass",x,z,nx,nz,rng.uniform(2,4),jitter+2,rng.uniform(0.7,1.05))
        else:
            for side in (-1.1,1.5):
                add("shore_stone",x,z,nx,nz,rng.uniform(0.3,1.4),jitter+side,rng.uniform(0.4,0.7))

    # A handful of quiet birds reward exploring the shore without becoming
    # obstacles or occupying the clear routes into either landing.
    for i,(x,z,nx,nz) in enumerate(samples[::11]):
        kind = "heron" if i%2==0 else "duck"
        add(kind,x,z,nx,nz,-rng.uniform(0.6,2.0),rng.uniform(-1,1),1.35 if kind=="heron" else 0.48)
    return result
