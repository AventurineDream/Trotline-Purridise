"""CPU renders of the cat rig: dialogue portraits, distance impostors and lineups.

A small deferred rasterizer writes each pixel's coat position, normal, part
and vertex paint, then shades the whole frame at once. Fur takes its coat
pattern per pixel (the same `catmesh.coat_rgb` the GL shader mirrors), so
stripes and points stay crisp at portrait size.
"""

from __future__ import annotations

from functools import lru_cache
import math

import numpy as np

from . import catmesh
from .catmesh import FUR_PARTS, LOD0, LOD1
from .raster import cover

PAPER = np.asarray((0.91, 0.875, 0.79), np.float32)
PORTRAIT_SIZE = 256


def _view(yaw, pitch):
    cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
    # Camera basis looking at the cat's front from yaw (0 = straight on), tilted down by
    # pitch, with the game camera's handedness (camera.py), so nothing is mirrored.
    forward = np.array([-sy * cp, -sp, -cy * cp], np.float32)
    right = np.array([-cy, 0.0, sy], np.float32)
    up = np.cross(forward, right)
    return right, up, forward


def rasterize(mesh: catmesh.CatMesh, weights: dict, width: int, height: int, *, yaw=0.6, pitch=0.18,
              frame=None, light=(0.45, 0.75, 0.55), rim=0.55, background=None, ambient=0.55):
    """(RGB float image, alpha mask) of one posed actor from a fixed view."""
    pos, nrm = mesh.blend(weights)
    rgb, glow = catmesh.paint(mesh)
    right, up, forward = _view(yaw, pitch)
    sx, sy, depth = pos @ right, pos @ up, pos @ forward
    if frame is None:
        lo = np.array([sx.min(), sy.min()])
        hi = np.array([sx.max(), sy.max()])
        frame = (lo + hi) / 2, float(max(hi[0] - lo[0], (hi[1] - lo[1]) * width / height)) * 1.12
    centre, span = frame
    scale = width / span
    px = (sx - centre[0]) * scale + width / 2
    py = height / 2 - (sy - centre[1]) * scale
    tris = mesh.triangles
    # Depth is measured along the view, so shift it positive for the shared raster.
    pixels, owner, bary, _z = cover(px, py, depth - depth.min() + 1.0, tris, width, height)
    covered = np.zeros(height * width, bool)
    covered[pixels] = True
    covered = covered.reshape(height, width)
    out = np.empty((height, width, 3), np.float32)
    out[:] = PAPER if background is None else background
    if not covered.any():
        return out, covered
    # Row-major pixel order matches out[covered].
    order = np.argsort(pixels)
    tri = tris[owner[order]]
    w = bary[order][..., None]

    def lerp(values):
        return (values[tri[:, 0]] * w[:, 0] + values[tri[:, 1]] * w[:, 1] + values[tri[:, 2]] * w[:, 2])

    part = mesh.part[tri[:, 0]]
    n = lerp(nrm)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-6)
    colour = lerp(rgb)
    fur = np.isin(part, FUR_PARTS)
    if fur.any():
        # Per-pixel coat, cat by cat (Pip & Pebble carry two looks).
        verts = tri[:, 0]
        for look, lo, hi in mesh.cats:
            pick = fur & (verts >= lo) & (verts < hi)
            if pick.any():
                cw = w[pick]
                ct = tri[pick]
                coat = (mesh.coat[ct[:, 0]] * cw[:, 0] + mesh.coat[ct[:, 1]] * cw[:, 1] + mesh.coat[ct[:, 2]] * cw[:, 2])
                cn = (mesh.coat_normals[ct[:, 0]] * cw[:, 0] + mesh.coat_normals[ct[:, 1]] * cw[:, 1]
                      + mesh.coat_normals[ct[:, 2]] * cw[:, 2])
                along = (mesh.along[ct[:, 0]] * cw[:, 0, 0] + mesh.along[ct[:, 1]] * cw[:, 1, 0]
                         + mesh.along[ct[:, 2]] * cw[:, 2, 0])
                colour[pick] = catmesh.coat_rgb(look, coat, cn, part[pick], along)
    emit = lerp(glow[:, None])[:, 0]
    l = np.asarray(light, np.float32)
    l /= np.linalg.norm(l)
    # Two-sided normals: thin attire and ears face either way.
    facing = np.where((n @ -forward)[:, None] < 0, -n, n)
    diffuse = np.clip(facing @ l, 0, 1)
    edge = np.clip(1 - np.abs(facing @ -forward), 0, 1) ** 2.5
    warm = np.asarray((1.0, 0.82, 0.55), np.float32)
    shade = (ambient + (1 - ambient) * diffuse)[:, None] * colour + warm * (edge * rim)[:, None] * 0.6
    shade = shade * (1 - emit[:, None]) + colour * emit[:, None] * 1.15
    out[covered] = np.clip(shade, 0, 1)
    # A hand-ink outline where the silhouette meets the paper.
    edge_px = covered & ~(np.roll(covered, 1, 0) & np.roll(covered, -1, 0) & np.roll(covered, 1, 1)
                          & np.roll(covered, -1, 1))
    out[edge_px] = out[edge_px] * 0.45 + np.asarray((0.15, 0.13, 0.11), np.float32) * 0.55
    return out, covered


def _pose_weights(mesh, wave=0.0):
    base = mesh.cats[0][0]["pose"]
    if base == "wave" or wave <= 0:
        return {base: 1.0}
    return {base: 1.0 - wave, "wave": wave}


@lru_cache(maxsize=24)
def portrait(npc_id: str) -> np.ndarray:
    """The 256×256 dialogue portrait: a three-quarter view, warm rim light, paper ground."""
    mesh = catmesh.cat_mesh(npc_id, LOD0)
    pose = mesh.cats[0][0]["pose"]
    # Every head in the actor, so twins share the frame.
    head = mesh.positions[pose][np.isin(mesh.part, catmesh.HEAD_PARTS) & (mesh.part != catmesh.WHISKER)]
    right, up, _f = _view(0.55, 0.12)
    hx, hy = head @ right, head @ up
    # Frame the head and shoulders, whatever the pose.
    tall = float(hy.max() - hy.min())
    centre = (float((hx.max() + hx.min()) / 2), float(hy.max() - tall * 0.95))
    span = max(tall * 2.5, float(hx.max() - hx.min()) * 1.35)
    gy, gx = np.mgrid[0:PORTRAIT_SIZE, 0:PORTRAIT_SIZE] / PORTRAIT_SIZE
    paper = PAPER + (np.asarray((0.80, 0.86, 0.84), np.float32) - PAPER) * (
        np.exp(-((gx - 0.5) ** 2 + (gy - 0.42) ** 2) / 0.12)[..., None] * 0.35)
    image, _mask = rasterize(mesh, _pose_weights(mesh), PORTRAIT_SIZE, PORTRAIT_SIZE, yaw=0.55, pitch=0.12,
                             frame=(centre, span), background=paper.astype(np.float32))
    card = np.clip(image * 255 + 0.5, 0, 255).astype(np.uint8)
    card[2:4, 2:-2] = card[-4:-2, 2:-2] = (151, 133, 103)
    card[2:-2, 2:4] = card[2:-2, -4:-2] = (151, 133, 103)
    card.setflags(write=False)
    return card


@lru_cache(maxsize=8)
def portrait_at(npc_id: str, side: int) -> np.ndarray | None:
    """The portrait at side×side for the dialogue panel, or None for a speaker without one."""
    from .actors import roster
    if npc_id not in roster():
        return None
    card = portrait(npc_id)
    if card.shape[0] != side:
        from .imageops import resize_rgb
        card = np.ascontiguousarray(resize_rgb(card, side, side))
        card.setflags(write=False)
    return card


def impostor(npc_id: str, view_yaw: float = 0.6, height_px: int = 96):
    """A distance sprite of the cat alone (no boat), cropped to its silhouette.

    Returns (RGBA uint8, width m, height m, base m): the sprite spans exactly the
    cat's view-space extent, feet on the bottom row, and base is its lowest point
    above the actor's origin.
    """
    mesh = catmesh.cat_mesh(npc_id, LOD1)
    weights = _pose_weights(mesh)
    pos, _n = mesh.blend(weights)
    right, up, _f = _view(view_yaw, 0.05)
    sx, sy = pos @ right, pos @ up
    width_m, height_m = float(sx.max() - sx.min()), float(sy.max() - sy.min())
    width_px = max(8, int(round(height_px * width_m / height_m)))
    centre = (float(sx.max() + sx.min()) / 2, float(sy.max() + sy.min()) / 2)
    # One scale both ways: the rounded width keeps a sliver more or less of ground.
    span = width_px * height_m / height_px
    image, mask = rasterize(mesh, weights, width_px, height_px, yaw=view_yaw, pitch=0.05,
                            frame=(centre, span), rim=0.25, ambient=0.6)
    rgba = np.zeros((height_px, width_px, 4), np.uint8)
    rgba[..., :3] = np.clip(image * 255 + 0.5, 0, 255).astype(np.uint8)
    rgba[..., 3] = mask.astype(np.uint8) * 255
    return rgba, span, height_m, float(pos[:, 1].min())


def clear_caches() -> None:
    portrait.cache_clear()
    portrait_at.cache_clear()
