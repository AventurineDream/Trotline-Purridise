"""The automated look-alike check for the field guide (V1-28).

No two fish on one lake may share both a silhouette and a palette at book
thumbnail size (128×64):

- **Silhouette:** intersection over union of the two outlines on the thumbnail
  grid. At or above `SILHOUETTE_IOU` the outlines are the same shape.
- **Palette:** each fish's back, flank and belly thirds (banded column by
  column, so a deep sunfish and a slim minnow are banded alike) become soft
  CIE Lab colour histograms. Two fish share a palette when, averaged over the
  three bands, at least `PALETTE_OVERLAP` of their colour mass falls in the
  same bins. Histograms keep fin colours, bands and markings that a mean
  colour would wash out.

A pair fails only when both hold. A lake's legendaries are checked with its
species. Shiny variants are left out: they share six palettes by design.
"""

from __future__ import annotations

from dataclasses import dataclass
from itertools import combinations

import numpy as np

from .fishmesh import CARD_SIZE, THUMBNAIL_SIZE, paint_card_layers

SILHOUETTE_IOU = 0.90
PALETTE_OVERLAP = 0.60
# Lab histogram bins: L 0–100, a and b −60–60, eight bins each (about 12–15 ΔE wide).
_BINS = np.asarray((8, 8, 8))
_LOW = np.asarray((0.0, -60.0, -60.0))
_HIGH = np.asarray((100.0, 60.0, 60.0))


@dataclass(frozen=True)
class Signature:
    silhouette: np.ndarray   # bool, thumbnail rows × columns
    bands: tuple             # back, flank and belly Lab histograms, each summing to 1


def _lab(rgb: np.ndarray) -> np.ndarray:
    """sRGB (0–255) to CIE Lab under D65."""
    c = rgb.astype(np.float64) / 255.0
    linear = np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    xyz = linear @ np.asarray(((0.4124, 0.2126, 0.0193),
                               (0.3576, 0.7152, 0.1192),
                               (0.1805, 0.0722, 0.9505)))
    xyz /= (0.95047, 1.0, 1.08883)
    f = np.where(xyz > 216 / 24389, np.cbrt(xyz), (24389 / 27 * xyz + 16) / 116)
    return np.stack((116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]),
                     200 * (f[..., 1] - f[..., 2])), axis=-1)


def _blocks(array: np.ndarray) -> np.ndarray:
    """Average a card-sized array down to the thumbnail grid."""
    width, height = THUMBNAIL_SIZE
    fy, fx = CARD_SIZE[1] // height, CARD_SIZE[0] // width
    return array.reshape((height, fy, width, fx) + array.shape[2:]).mean(axis=(1, 3))


def _histogram(lab: np.ndarray) -> np.ndarray:
    """Trilinear soft histogram, so near-identical colours never split across a bin edge."""
    hist = np.zeros(tuple(_BINS))
    if not len(lab):
        return hist
    pos = np.clip((lab - _LOW) / (_HIGH - _LOW) * _BINS - 0.5, 0, _BINS - 1)
    low = np.minimum(np.floor(pos).astype(int), _BINS - 2)
    frac = pos - low
    for corner in np.ndindex(2, 2, 2):
        weight = np.prod(np.where(corner, frac, 1 - frac), axis=1)
        index = low + corner
        np.add.at(hist, (index[:, 0], index[:, 1], index[:, 2]), weight)
    return hist / hist.sum()


def signature(fish_id: str, shiny: bool = False) -> Signature:
    card, mask = paint_card_layers(fish_id, shiny)
    silhouette = _blocks(mask.astype(np.float32)) >= 0.5
    weight = _blocks(mask[..., None].astype(np.float64))
    colour = _blocks(card.astype(np.float64) * mask[..., None]) / np.maximum(weight, 1e-9)
    lab = _lab(np.clip(colour, 0, 255))
    rows = np.arange(silhouette.shape[0])[:, None]
    top = np.argmax(silhouette, axis=0)
    bottom = silhouette.shape[0] - 1 - np.argmax(silhouette[::-1], axis=0)
    band = np.clip(((rows - top) / np.maximum(bottom - top + 1, 1) * 3).astype(int), 0, 2)
    return Signature(silhouette, tuple(_histogram(lab[silhouette & (band == k)]) for k in range(3)))


def compare(a: Signature, b: Signature) -> tuple[float, float]:
    """(silhouette IoU, palette overlap) for two signatures, each from 0 to 1."""
    iou = np.count_nonzero(a.silhouette & b.silhouette) / max(np.count_nonzero(a.silhouette | b.silhouette), 1)
    overlap = np.mean([np.minimum(x, y).sum() for x, y in zip(a.bands, b.bands)])
    return float(iou), float(overlap)


def lake_members(content) -> dict[str, list[str]]:
    members = {lake_id: list(lake["species_ids"]) for lake_id, lake in content.lakes.items()}
    for legendary_id, row in content.legendaries.items():
        members[row["lake"]].append(legendary_id)
    return members


def lookalike_report(content) -> dict:
    """Per lake: pair count, the closest pairs, and every pair that fails."""
    cache: dict[str, Signature] = {}
    lakes, failures = {}, []
    for lake_id, ids in lake_members(content).items():
        pairs = []
        for a, b in combinations(ids, 2):
            for fish_id in (a, b):
                if fish_id not in cache:
                    cache[fish_id] = signature(fish_id)
            iou, overlap = compare(cache[a], cache[b])
            alike = iou >= SILHOUETTE_IOU and overlap >= PALETTE_OVERLAP
            pair = {"a": a, "b": b, "iou": round(iou, 4), "palette_overlap": round(overlap, 4), "alike": alike}
            pairs.append(pair)
            if alike:
                failures.append({"lake": lake_id, **pair})
        # Closest first: how near each pair comes to failing on its weaker axis.
        closest = sorted(pairs, key=lambda p: -min(p["iou"] / SILHOUETTE_IOU,
                                                   p["palette_overlap"] / PALETTE_OVERLAP))
        lakes[lake_id] = {"fish": len(ids), "pairs": len(pairs), "closest": closest[:6]}
    return {"thresholds": {"silhouette_iou": SILHOUETTE_IOU, "palette_overlap": PALETTE_OVERLAP},
            "lakes": lakes, "failures": failures}
