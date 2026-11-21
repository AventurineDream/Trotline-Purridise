"""Bot's dialogue portrait: his saved shell and collar on the cats' paper card.

The cats' cards come from their skinned rig (catart). Bot is botmesh's flat-shaded quads,
so this module rasterizes those faces once per look (shell and collar style) with the
cats' three-quarter view, light, rim and ink outline into catart.PortraitLayers. The
lamp and glint faces (botmesh.EYE) are the layers' eyes, so catart.lidded closes a
shutter over his lamp exactly where it lowers a cat's lids, and catart.portrait_rig and
portraitmotion animate him with the same clocks, in his own steadier style
(portraitmotion.SPEAKER_STYLES).

The card follows the profile: a new shell or a retied collar is a new look and renders
on first need (about the cost of one cat card). Two looks are kept, one for each side
of a swap at a landing.
"""

from __future__ import annotations

from functools import lru_cache
from typing import NamedTuple

import numpy as np

from . import botmesh, catart
from .raster import cover

BOT = "bot"  # the speaker id story scenes give him


class Look(NamedTuple):
    """What Bot's card shows: a botmesh shell id and collar style (botmesh.collar_style)."""

    shell: str
    style: str


DEFAULT_LOOK = Look("tin", "none")  # a new game's Bot (botidentity.default_profile)


def look(state) -> Look:
    """Bot's look from the saved profile and settings, as the lake mesh draws him."""
    from .bot import appearance
    seen = appearance(state)
    return Look(seen["shell"], botmesh.collar_style(seen["stage"], seen["knot"], seen["collar_visible"]))


@lru_cache(maxsize=2)
def portrait_layers(bot_look: Look) -> catart.PortraitLayers:
    """Bot's 256×256 portrait layers for one look (read-only arrays).

    Framed like a cat, from the top of his lamp, star or antenna down, with a margin of
    paper beside him; the card cuts off his feet, so a shell's size sets the zoom.
    """
    mesh = botmesh.local_mesh(bot_look.shell, bot_look.style)
    size = catart.PORTRAIT_SIZE
    count = len(mesh.points)
    points = mesh.points.reshape(-1, 3)  # four corners a face; a triangle face repeats its last
    first = np.arange(count) * 4
    tris = np.concatenate((np.stack((first, first + 1, first + 2), 1), np.stack((first, first + 2, first + 3), 1)))
    right, up, forward = catart._view(0.55, 0.12)
    sx, sy, depth = points @ right, points @ up, points @ forward
    top, bottom = float(sy.max()), float(sy.min())
    # The top 80% of a tall shell; a broad one (frog, duck, sub) just fits its width.
    span = max((top - bottom) * 0.80, float(sx.max() - sx.min()))
    centre = (float(sx.max() + sx.min()) / 2, top + span * 0.06 - span / 2)
    scale = size / span
    px = (sx - centre[0]) * scale + size / 2
    py = size / 2 - (sy - centre[1]) * scale
    pixels, owner, _bary, _z = cover(px, py, depth - depth.min() + 1.0, tris, size, size)
    face = owner % count  # each face's second triangle follows all the first ones

    covered = np.zeros(size * size, bool)
    covered[pixels] = True
    covered = covered.reshape(size, size)
    out = catart._paper().copy()
    order = np.argsort(pixels)  # row-major, matching out[covered]
    face = face[order]
    # Bot's normals are per face; his light, rim and glowing lamp match the cats' shading.
    out[covered] = catart.shade(mesh.normals[face], mesh.colors[face], mesh.emission[face], forward)
    catart.ink_outline(out, covered)
    eyes = np.zeros(size * size, bool)
    eyes[np.sort(pixels)] = mesh.parts[face] == botmesh.EYE
    cat = np.clip(out * 255 + 0.5, 0, 255).astype(np.uint8)
    card = cat.copy()
    catart._border(card)
    layers = catart.PortraitLayers(card, cat, covered, eyes.reshape(size, size))
    for array in layers:
        array.setflags(write=False)
    return layers
