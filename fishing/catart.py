"""CPU renders of the cat rig: dialogue portraits, distance impostors and lineups.

A small deferred rasterizer writes each pixel's coat position, normal, part
and vertex paint, then shades the whole frame at once. Fur takes its coat
pattern per pixel (the same `catmesh.coat_rgb` the GL shader mirrors), so
stripes and points stay crisp at portrait size.

A dialogue portrait is rendered once into layers (paper, cat, coverage, eyes);
`portrait_rig` scales them to the panel with open, half and closed lids so
portraitmotion can animate the card per frame without rasterizing again. Bot's
layers come from botportrait, which shares this module's light and ink.
"""

from __future__ import annotations

from functools import lru_cache
import math
from typing import NamedTuple

import numpy as np

from . import catmesh
from .catmesh import FUR_PARTS, LOD0, LOD1
from .portraitmotion import LIDS, PortraitRig
from .raster import cover

PAPER = np.asarray((0.91, 0.875, 0.79), np.float32)
PORTRAIT_SIZE = 256
FRAME_RGB = (151, 133, 103)  # the card's drawn border line
INK = np.asarray((0.15, 0.13, 0.11), np.float32)


def _view(yaw, pitch):
    cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)
    # Camera basis looking at the cat's front from yaw (0 = straight on), tilted down by
    # pitch, with the game camera's handedness (camera.py), so nothing is mirrored.
    forward = np.array([-sy * cp, -sp, -cy * cp], np.float32)
    right = np.array([-cy, 0.0, sy], np.float32)
    up = np.cross(forward, right)
    return right, up, forward


def rasterize(mesh: catmesh.CatMesh, weights: dict, width: int, height: int, *, yaw=0.6, pitch=0.18,
              frame=None, light=(0.45, 0.75, 0.55), rim=0.55, background=None, ambient=0.55, parts=False):
    """(RGB float image, alpha mask) of one posed actor from a fixed view.

    With parts=True a third value is returned: the (height, width) int16 mesh part id
    of each pixel, -1 where nothing covers it (the portrait finds its eyes this way).
    """
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
        return (out, covered, np.full((height, width), -1, np.int16)) if parts else (out, covered)
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
    out[covered] = shade(n, colour, emit, forward, light, rim, ambient)
    ink_outline(out, covered)
    if parts:
        part_img = np.full(height * width, -1, np.int16)
        part_img[np.sort(pixels)] = part
        return out, covered, part_img.reshape(height, width)
    return out, covered


def shade(n, colour, emit, forward, light=(0.45, 0.75, 0.55), rim=0.55, ambient=0.55):
    """Lit 0–1 RGB for covered pixels: two-sided diffuse, a warm rim and self-glow.

    Args:
        n: (N, 3) unit normals; colour: (N, 3) 0–1 base colour; emit: (N,) 0–1 glow.
        forward: The view direction from `_view`; light: direction toward the light.

    Shared with botportrait so Bot's card is lit like the cats'.
    """
    l = np.asarray(light, np.float32)
    l /= np.linalg.norm(l)
    # Two-sided normals: thin attire and ears face either way.
    facing = np.where((n @ -forward)[:, None] < 0, -n, n)
    diffuse = np.clip(facing @ l, 0, 1)
    edge = np.clip(1 - np.abs(facing @ -forward), 0, 1) ** 2.5
    warm = np.asarray((1.0, 0.82, 0.55), np.float32)
    lit = (ambient + (1 - ambient) * diffuse)[:, None] * colour + warm * (edge * rim)[:, None] * 0.6
    lit = lit * (1 - emit[:, None]) + colour * emit[:, None] * 1.15
    return np.clip(lit, 0, 1)


def ink_outline(out: np.ndarray, covered: np.ndarray) -> None:
    """Darken, in place, a hand-ink outline where the (H, W) silhouette meets the paper."""
    edge_px = covered & ~(np.roll(covered, 1, 0) & np.roll(covered, -1, 0) & np.roll(covered, 1, 1)
                          & np.roll(covered, -1, 1))
    out[edge_px] = out[edge_px] * 0.45 + INK * 0.55


def _pose_weights(mesh, wave=0.0):
    base = mesh.cats[0][0]["pose"]
    if base == "wave" or wave <= 0:
        return {base: 1.0}
    return {base: 1.0 - wave, "wave": wave}


class PortraitLayers(NamedTuple):
    """One cat's 256×256 portrait render, kept so the card can be animated without re-rasterizing.

    card: (256, 256, 3) uint8 the still card (cat on paper, with its border).
    cat: (256, 256, 3) uint8 the cat on paper, without the border.
    cover: (256, 256) bool pixels the cat covers.
    eyes: (256, 256) bool visible eye and pupil pixels, where lids are painted.
    """

    card: np.ndarray
    cat: np.ndarray
    cover: np.ndarray
    eyes: np.ndarray


def _border(card: np.ndarray) -> None:
    card[2:4, 2:-2] = card[-4:-2, 2:-2] = FRAME_RGB
    card[2:-2, 2:4] = card[2:-2, -4:-2] = FRAME_RGB


@lru_cache(maxsize=1)
def _paper() -> np.ndarray:
    """The portrait's paper ground: warm paper with a cool glow behind the head."""
    gy, gx = np.mgrid[0:PORTRAIT_SIZE, 0:PORTRAIT_SIZE] / PORTRAIT_SIZE
    paper = PAPER + (np.asarray((0.80, 0.86, 0.84), np.float32) - PAPER) * (
        np.exp(-((gx - 0.5) ** 2 + (gy - 0.42) ** 2) / 0.12)[..., None] * 0.35)
    return paper.astype(np.float32)


@lru_cache(maxsize=24)
def portrait_layers(npc_id: str) -> PortraitLayers:
    """The cat's dialogue portrait layers: a three-quarter view, warm rim light, paper ground."""
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
    image, mask, parts = rasterize(mesh, _pose_weights(mesh), PORTRAIT_SIZE, PORTRAIT_SIZE, yaw=0.55,
                                   pitch=0.12, frame=(centre, span), background=_paper(), parts=True)
    cat = np.clip(image * 255 + 0.5, 0, 255).astype(np.uint8)
    card = cat.copy()
    _border(card)
    layers = PortraitLayers(card, cat, mask, np.isin(parts, (catmesh.EYE, catmesh.PUPIL)))
    for array in layers:
        array.setflags(write=False)
    return layers


def portrait(npc_id: str) -> np.ndarray:
    """The 256×256 still dialogue card (uint8, read-only, shared with the layer cache)."""
    return portrait_layers(npc_id).card


def lidded(cat: np.ndarray, eyes: np.ndarray, closed: float) -> np.ndarray:
    """The cat with its lids lowered over a `closed` fraction (0–1) of each eye.

    Works column by column on each vertical run of eye pixels: the top part takes the
    fur colour just above the eye, slightly shaded, and an ink line marks the lid's edge.
    Fully closed, that line follows the eye's lower rim: the soft ◡ of a content cat.
    """
    if closed <= 0 or not eyes.any():
        return cat
    out = cat.astype(np.float32)
    for x in np.flatnonzero(eyes.any(axis=0)):
        edges = np.diff(np.concatenate(([0], eyes[:, x].astype(np.int8), [0])))
        for top, end in zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)):
            # At least a pixel, so even a far, foreshortened eye shows its lid half-closed.
            k = max(1, int(round(closed * (end - top))))
            # The lid is the fur just above the eye, a touch darker so it reads as a fold.
            out[top:top + k, x] = out[max(0, top - 1), x] * 0.92
            edge = top + k - 1
            # A two-pixel ink lash line, mostly ink so it holds against dark coats too.
            out[max(top, edge - 1):edge + 1, x] = out[max(top, edge - 1):edge + 1, x] * 0.25 + INK * 255 * 0.75
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


@lru_cache(maxsize=2)
def portrait_rig(npc_id: str, side: int, look=None) -> PortraitRig | None:
    """The animated portrait at side×side for the dialogue panel, or None for a speaker without one.

    Cats come from their rig. Bot ("bot") comes from botportrait in `look`, his
    botportrait.Look (DEFAULT_LOOK when None), so a new shell or collar is a new rig;
    cats take look=None. Only one speaker talks at a time; two rigs cover a scene
    handed back and forth.
    Raises ValueError for a side outside 1..PORTRAIT_SIZE: larger would only upscale the
    render, and portrait_bytes_bound sizes rigs at PORTRAIT_SIZE.
    """
    if not 1 <= side <= PORTRAIT_SIZE:
        raise ValueError(f"portrait side {side} outside 1..{PORTRAIT_SIZE}")
    from . import botportrait
    if npc_id == botportrait.BOT:
        layers = botportrait.portrait_layers(look or botportrait.DEFAULT_LOOK)
    else:
        from .actors import roster
        if npc_id not in roster():
            return None
        layers = portrait_layers(npc_id)
    from .imageops import resize_rgb
    paper = np.clip(_paper() * 255 + 0.5, 0, 255).astype(np.uint8)
    border = np.zeros((PORTRAIT_SIZE, PORTRAIT_SIZE, 1), np.uint8)
    border[2:4, 2:-2] = border[-4:-2, 2:-2] = border[2:-2, 2:4] = border[2:-2, -4:-2] = 255

    def scaled(image):
        return resize_rgb(image, side, side)

    cats = {lid: scaled(lidded(layers.cat, layers.eyes, lid)) for lid in LIDS}
    cover_ = scaled(layers.cover.astype(np.uint8)[..., None] * 255)[..., 0] / 255.0
    weight = scaled(border)[..., 0] / 255.0
    return PortraitRig(scaled(paper), cats, cover_, FRAME_RGB, weight)


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


def portrait_bytes_bound() -> int:
    """Bytes the portrait caches hold now: the shared paper ground, layers per cached cat
    and per cached Bot look, and each rig at the largest side portrait_rig allows."""
    from . import botportrait
    layers = PORTRAIT_SIZE ** 2 * (3 + 3 + 1 + 1)  # card, cat, cover, eyes
    paper = _paper.cache_info().currsize * PORTRAIT_SIZE ** 2 * 3 * 4  # float32 RGB
    held = portrait_layers.cache_info().currsize + botportrait.portrait_layers.cache_info().currsize
    return paper + held * layers + portrait_rig.cache_info().currsize * PortraitRig.bytes_for(PORTRAIT_SIZE)


def clear_caches() -> None:
    from . import botportrait
    portrait_layers.cache_clear()
    botportrait.portrait_layers.cache_clear()
    portrait_rig.cache_clear()
