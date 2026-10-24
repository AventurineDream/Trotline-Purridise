"""Parametric fish meshes and bounded field-guide watercolor cards."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import math
import zlib

import numpy as np

from .content import load_content_v2
from .imageops import resize_rgb

CARD_SIZE = (512, 256)
THUMBNAIL_SIZE = (128, 64)
MESH_CACHE_ENTRIES = 64
CARD_CACHE_ENTRIES = 48

# Shared anatomical defaults. Species-specific measurements and traits live in
# species.json so a new species does not need a new geometry generator.
FAMILY_PRESETS = {
    "catfish": {"body_curve": 0.74, "eye_scale": 0.78, "fin_height": 0.16},
    "bass": {"body_curve": 0.78, "eye_scale": 0.88, "fin_height": 0.22},
    "sunfish": {"body_curve": 0.62, "eye_scale": 0.92, "fin_height": 0.22},
    "trout": {"body_curve": 0.82, "eye_scale": 0.84, "fin_height": 0.20},
    "gar": {"body_curve": 0.94, "eye_scale": 0.60, "fin_height": 0.12},
    "sucker": {"body_curve": 0.78, "eye_scale": 0.72, "fin_height": 0.15},
    "minnow": {"body_curve": 0.95, "eye_scale": 0.90, "fin_height": 0.11},
    "pike": {"body_curve": 0.89, "eye_scale": 0.76, "fin_height": 0.18},
    "sculpin": {"body_curve": 0.70, "eye_scale": 0.92, "fin_height": 0.25},
    "eel": {"body_curve": 1.18, "eye_scale": 0.62, "fin_height": 0.08},
    "cosmic": {"body_curve": 0.82, "eye_scale": 1.0, "fin_height": 0.24},
}

# Colors are normalized RGB. Each family gets a recognizable base; per-species
# palettes add the markings that distinguish the existing roster.
PALETTES = {
    "bluegill": ((0.24, 0.34, 0.23), (0.69, 0.62, 0.35), (0.88, 0.70, 0.49)),
    "bullhead": ((0.31, 0.27, 0.18), (0.60, 0.48, 0.31), (0.78, 0.66, 0.48)),
    "crappie": ((0.25, 0.33, 0.36), (0.67, 0.69, 0.61), (0.86, 0.80, 0.64)),
    "carp": ((0.36, 0.28, 0.13), (0.68, 0.52, 0.25), (0.86, 0.72, 0.45)),
    "drum": ((0.30, 0.32, 0.31), (0.65, 0.59, 0.45), (0.81, 0.71, 0.55)),
    "channel": ((0.28, 0.31, 0.27), (0.63, 0.60, 0.48), (0.82, 0.75, 0.58)),
    "blue": ((0.16, 0.25, 0.32), (0.44, 0.54, 0.58), (0.75, 0.76, 0.68)),
    "flathead": ((0.39, 0.36, 0.22), (0.72, 0.62, 0.35), (0.85, 0.73, 0.46)),
    "largemouth": ((0.20, 0.34, 0.19), (0.49, 0.62, 0.32), (0.82, 0.75, 0.46)),
    "smallmouth": ((0.29, 0.34, 0.23), (0.64, 0.57, 0.34), (0.83, 0.71, 0.48)),
    "gar": ((0.34, 0.37, 0.22), (0.61, 0.62, 0.38), (0.79, 0.74, 0.51)),
    "buffalo": ((0.28, 0.30, 0.27), (0.57, 0.51, 0.39), (0.79, 0.70, 0.54)),
    "redear": ((0.28, 0.35, 0.24), (0.70, 0.62, 0.36), (0.90, 0.72, 0.48)),
    "green_sunfish": ((0.17, 0.35, 0.22), (0.52, 0.61, 0.31), (0.86, 0.70, 0.43)),
    "warmouth": ((0.21, 0.31, 0.25), (0.60, 0.51, 0.34), (0.83, 0.68, 0.45)),
    "redbreast": ((0.30, 0.35, 0.24), (0.70, 0.53, 0.36), (0.88, 0.64, 0.45)),
    "longear": ((0.18, 0.31, 0.28), (0.54, 0.62, 0.40), (0.86, 0.70, 0.47)),
    "bass": ((0.22, 0.35, 0.24), (0.55, 0.62, 0.34), (0.83, 0.74, 0.45)),
    "hybrid_striper": ((0.23, 0.32, 0.34), (0.67, 0.68, 0.57), (0.86, 0.78, 0.59)),
    "striped_bass": ((0.18, 0.27, 0.33), (0.61, 0.67, 0.62), (0.86, 0.82, 0.68)),
    "bowfin": ((0.22, 0.29, 0.21), (0.53, 0.49, 0.31), (0.76, 0.66, 0.45)),
    "spotted_gar": ((0.34, 0.37, 0.23), (0.63, 0.64, 0.40), (0.83, 0.76, 0.53)),
    "shortnose_gar": ((0.31, 0.34, 0.24), (0.60, 0.59, 0.39), (0.81, 0.73, 0.51)),
    "alligator_gar": ((0.29, 0.32, 0.20), (0.57, 0.57, 0.34), (0.77, 0.70, 0.46)),
    "black_bullhead": ((0.20, 0.20, 0.18), (0.43, 0.39, 0.31), (0.67, 0.59, 0.46)),
    "brown_bullhead": ((0.33, 0.26, 0.19), (0.62, 0.48, 0.33), (0.80, 0.67, 0.49)),
    "blue_sucker": ((0.22, 0.31, 0.34), (0.55, 0.62, 0.61), (0.82, 0.78, 0.67)),
    "bigmouth_buffalo": ((0.30, 0.27, 0.19), (0.61, 0.48, 0.29), (0.82, 0.68, 0.43)),
    "black_buffalo": ((0.18, 0.21, 0.20), (0.43, 0.43, 0.38), (0.71, 0.65, 0.53)),
    "golden_shiner": ((0.26, 0.31, 0.27), (0.76, 0.67, 0.39), (0.90, 0.81, 0.57)),
    "gizzard_shad": ((0.27, 0.34, 0.39), (0.70, 0.73, 0.69), (0.88, 0.83, 0.69)),
    "threadfin_shad": ((0.30, 0.37, 0.40), (0.75, 0.75, 0.68), (0.91, 0.82, 0.68)),
    "chain_pickerel": ((0.31, 0.35, 0.24), (0.62, 0.64, 0.39), (0.82, 0.75, 0.51)),
}

SHINY_PALETTES = {
    "albino": ((0.53, 0.37, 0.30), (0.91, 0.77, 0.65), (1.0, 0.92, 0.79)),
    "golden": ((0.50, 0.32, 0.10), (0.95, 0.68, 0.19), (1.0, 0.88, 0.48)),
    "starry": ((0.16, 0.23, 0.47), (0.42, 0.67, 0.91), (0.82, 0.90, 1.0)),
    "glow": ((0.08, 0.34, 0.40), (0.18, 0.78, 0.73), (0.71, 1.0, 0.88)),
    "ink": ((0.08, 0.09, 0.15), (0.27, 0.31, 0.44), (0.63, 0.66, 0.75)),
    "rose": ((0.45, 0.19, 0.25), (0.88, 0.40, 0.48), (1.0, 0.76, 0.68)),
}

_PATTERNS = {"plain", "spots", "bars", "stripes", "mottled", "vermiculate"}


@dataclass(frozen=True)
class FishMesh:
    """Triangle mesh in fish-local coordinates, with per-triangle paint colors."""

    vertices: np.ndarray
    triangles: np.ndarray
    normals: np.ndarray
    colors: np.ndarray

    @property
    def triangle_count(self) -> int:
        return int(len(self.triangles))

    @property
    def nbytes(self) -> int:
        return sum(array.nbytes for array in
                   (self.vertices, self.triangles, self.normals, self.colors))


@lru_cache(maxsize=1)
def _species_rows() -> dict[str, dict]:
    return load_content_v2().species


def fish_look(species_id: str) -> dict:
    row = _species_rows().get(species_id)
    if row is None or not isinstance(row.get("look"), dict):
        raise KeyError(f"fish look is missing for species {species_id!r}")
    return row["look"]


def _rgb(values) -> np.ndarray:
    return np.asarray(values, dtype=np.float32)


def _palette(species_id: str, shiny: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    row = _species_rows()[species_id]
    look = fish_look(species_id)
    if shiny:
        return tuple(_rgb(value) for value in SHINY_PALETTES[row["shiny"]])
    return tuple(_rgb(value) for value in PALETTES.get(look["palette"], PALETTES["bass"]))


def _freeze(array: np.ndarray) -> np.ndarray:
    array.setflags(write=False)
    return array


@lru_cache(maxsize=MESH_CACHE_ENTRIES)
def haul_mesh(species_id: str, lake_id: str = "briar", shiny: bool = False) -> FishMesh:
    """Build a deterministic 1.4–1.6k triangle mesh, cached by lake and fish."""
    look = fish_look(species_id)
    preset = FAMILY_PRESETS[look["family"]]
    top, side, belly = _palette(species_id, shiny)
    stations, sides = 42, 18
    body_depth = float(look["body_depth"])
    ratio = float(look["length_depth_ratio"])
    radius_y = min(0.64, max(0.18, 1.58 / ratio)) * body_depth
    radius_z = radius_y * (0.48 if look["family"] == "gar" else 0.69)
    snout = float(look["snout"])
    verts: list[tuple[float, float, float]] = []
    tri: list[tuple[int, int, int]] = []
    colors: list[np.ndarray] = []

    def triangle(a, b, c, color):
        base = len(verts)
        verts.extend((tuple(a), tuple(b), tuple(c)))
        tri.append((base, base + 1, base + 2))
        colors.append(_rgb(color))

    body_base = len(verts)
    for ix in range(stations):
        u = ix / (stations - 1)
        x = -0.90 + u * (1.80 + snout * 0.62)
        curve = float(preset["body_curve"])
        bulge = max(0.0, math.sin(math.pi * u)) ** curve
        head_taper = 1.0 - 0.34 * max(0.0, u - 0.60) / 0.40
        if look["head_shape"] == "flat":
            head_taper = 1.0 - 0.18 * max(0.0, u - 0.68) / 0.32
        if look["head_shape"] == "pointed":
            head_taper *= 1.0 - 0.55 * max(0.0, u - 0.65) / 0.35
        ry = max(0.006, radius_y * bulge * head_taper)
        rz = max(0.006, radius_z * bulge * head_taper)
        if snout and u > 0.82:
            ry = max(0.004, ry * (1.0 - snout * (u - 0.82) / 0.18))
            rz = max(0.004, rz * (1.0 - snout * (u - 0.82) / 0.18))
        for iz in range(sides):
            theta = math.tau * iz / sides
            y, z = ry * math.cos(theta), rz * math.sin(theta)
            verts.append((x, y, z))
    for ix in range(stations - 1):
        u = (ix + 0.5) / (stations - 1)
        for iz in range(sides):
            j = (iz + 1) % sides
            a = body_base + ix * sides + iz
            b = body_base + ix * sides + j
            c = body_base + (ix + 1) * sides + j
            d = body_base + (ix + 1) * sides + iz
            for points in ((a, b, c), (a, c, d)):
                tri.append(points)
                angle = math.tau * (iz + 0.5) / sides
                height = math.cos(angle)
                x_mark = (math.sin(u * math.tau * 7.0) + 1.0) * 0.5
                pattern = look["scale_pattern"]
                mark = False
                if pattern == "bars":
                    mark = math.sin(u * math.tau * 7.2 + 0.3) > 0.73 and abs(height) < 0.70
                elif pattern == "stripes":
                    mark = abs(math.sin(angle * 3.0)) < 0.13 and abs(height) < 0.80
                elif pattern == "spots":
                    mark = (math.sin(u * math.tau * 17.0) * math.cos(angle * 4.0) > 0.68)
                elif pattern in {"mottled", "vermiculate"}:
                    wave = math.sin(u * 53.0 + math.sin(angle * 5.0) * 2.0)
                    mark = wave > (0.52 if pattern == "mottled" else 0.75)
                color = top if height > 0.35 else belly if height < -0.50 else side
                if mark:
                    color = _rgb(color) * (0.62 if pattern != "vermiculate" else 0.73)
                colors.append(_rgb(color) * np.float32(0.96 + 0.05 * x_mark))

    fin = _rgb(side) * 0.78 + _rgb(top) * 0.22
    fin_height = float(preset["fin_height"])
    dorsal_count = int(look["dorsal_count"])
    for index in range(dorsal_count):
        x0 = -0.25 + index * 0.22
        x1 = 0.16 + index * 0.20
        y0, y1 = radius_y * 0.78, radius_y * 0.73
        triangle((x0, y0, 0), ((x0 + x1) * 0.5, y0 + fin_height, 0), (x1, y1, 0), fin)
        triangle((x0, y0, 0.01), (x1, y1, 0.01), ((x0 + x1) * 0.5, y0 + fin_height, 0.01), fin)
    if look["adipose"]:
        triangle((-0.08, radius_y * 0.83, 0), (0.02, radius_y + 0.10, 0),
                 (0.16, radius_y * 0.83, 0), fin)
    tail_y = radius_y * (0.24 if look["tail_shape"] == "truncate" else 0.40)
    tail_x = -1.27
    if look["tail_shape"] == "forked":
        triangle((-0.84, 0, 0), (tail_x, tail_y, 0), (-1.03, 0.045, 0), fin)
        triangle((-0.84, 0, 0), (-1.03, -0.045, 0), (tail_x, -tail_y, 0), fin)
    elif look["tail_shape"] == "rounded":
        triangle((-0.85, 0.02, 0), (tail_x, tail_y, 0), (tail_x, -tail_y, 0), fin)
    else:
        triangle((-0.85, tail_y, 0), (tail_x, tail_y, 0),
                 (tail_x, -tail_y, 0), fin)
        triangle((-0.85, tail_y, 0), (tail_x, -tail_y, 0), (-0.85, -tail_y, 0), fin)
    # Pectoral, pelvic and anal fins make the silhouette read from the side.
    for sign in (-1, 1):
        z = sign * radius_z * 0.80
        triangle((0.02, -0.02, z), (-0.20, -0.28, sign * 0.34),
                 (-0.05, -0.08, sign * 0.25), fin)
        triangle((-0.34, -radius_y * 0.48, sign * radius_z * 0.52),
                 (-0.48, -radius_y * 0.76, sign * 0.16),
                 (-0.24, -radius_y * 0.66, sign * radius_z * 0.60), fin)
    triangle((-0.48, -radius_y * 0.70, 0), (-0.22, -radius_y - fin_height * 0.65, 0),
             (-0.02, -radius_y * 0.55, 0), fin)

    # A dark terminal/inferior/upturned mouth and paired ink-bright eyes.
    mouth_y = {"terminal": 0.0, "inferior": -0.055, "upturned": 0.055}[look["mouth"]]
    triangle((0.79, mouth_y - 0.018, -0.03), (0.91 + snout * 0.45, mouth_y, 0),
             (0.79, mouth_y + 0.018, 0.03), (0.12, 0.10, 0.08))
    eye_x = 0.62 if not snout else 0.70
    for sign in (-1, 1):
        center = np.asarray((eye_x, radius_y * 0.18, sign * radius_z * 0.88), np.float32)
        for j in range(8):
            a0, a1 = j * math.tau / 8, (j + 1) * math.tau / 8
            p0 = center + np.asarray((math.cos(a0) * 0.035, math.sin(a0) * 0.035, 0), np.float32)
            p1 = center + np.asarray((math.cos(a1) * 0.035, math.sin(a1) * 0.035, 0), np.float32)
            triangle(center, p0, p1, (0.91, 0.83, 0.63))
        triangle(center + (0, 0, sign * 0.002),
                 center + (0.018, 0, sign * 0.002),
                 center + (0.008, -0.018, sign * 0.002), (0.08, 0.07, 0.06))
    barbels = int(look["barbels"])
    for n in range(barbels):
        for sign in (-1, 1):
            start = np.asarray((0.70 - n * 0.035, -0.035, sign * radius_z * 0.72), np.float32)
            end = start + np.asarray((0.13 + 0.02 * (n % 2), -0.12 - 0.02 * n,
                                     sign * (0.10 + n * 0.018)), np.float32)
            mid = (start + end) * 0.5 + np.asarray((0, -0.025, 0), np.float32)
            triangle(start, mid + (0, 0, 0.012), end, fin)
            triangle(start, end, mid - (0, 0, 0.012), fin)

    vertices = np.asarray(verts, dtype=np.float32)
    triangles = np.asarray(tri, dtype=np.int32)
    colors_array = np.asarray(colors, dtype=np.float32)
    points = vertices[triangles]
    normals = np.cross(points[:, 1] - points[:, 0], points[:, 2] - points[:, 0])
    norms = np.linalg.norm(normals, axis=1, keepdims=True)
    normals = normals / np.maximum(norms, 1e-7)
    if len(normals) != len(colors_array):
        raise AssertionError("fish mesh colors must match its triangles")
    for array in (vertices, triangles, colors_array):
        _freeze(array)
    normals = _freeze(normals.astype(np.float32))
    return FishMesh(vertices, triangles, normals, colors_array)


def _poly_mask(xx, yy, points):
    mask = np.zeros(xx.shape, dtype=np.bool_)
    previous = points[-1]
    for current in points:
        x0, y0 = previous
        x1, y1 = current
        crosses = (y0 > yy) != (y1 > yy)
        edge_x = (x1 - x0) * (yy - y0) / (y1 - y0 + 1e-9) + x0
        mask ^= crosses & (xx < edge_x)
        previous = current
    return mask


def _card_seed(species_id: str, shiny: bool) -> int:
    return zlib.crc32((species_id + ("/shiny" if shiny else "/normal")).encode("utf-8"))


@lru_cache(maxsize=CARD_CACHE_ENTRIES)
def _card_cached(species_id: str, shiny: bool = False) -> np.ndarray:
    look = fish_look(species_id)
    top, side, belly = _palette(species_id, shiny)
    width, height = CARD_SIZE
    xx, yy = np.meshgrid(np.linspace(0, 1, width, dtype=np.float32),
                         np.linspace(0, 1, height, dtype=np.float32))
    rng = np.random.default_rng(_card_seed(species_id, shiny))
    noise = rng.normal(0.0, 2.1, (height, width, 1)).astype(np.float32)
    wash = np.exp(-(((xx - 0.54) / 0.68) ** 2 + ((yy - 0.50) / 0.72) ** 2))
    base = np.empty((height, width, 3), dtype=np.float32)
    paper = np.asarray((0.91, 0.875, 0.79), np.float32)
    blue_wash = np.asarray((0.76, 0.83, 0.82), np.float32)
    base[:] = paper + (blue_wash - paper) * (wash[..., None] * 0.20) + noise / 255.0

    # Draw long jaws as a separate wedge so gar remain recognizable at
    # thumbnail size without stretching the profile of ordinary fish.
    u = (xx - 0.105) / 0.78
    uc = np.clip(u, 0.0, 1.0)
    ratio = float(look["length_depth_ratio"])
    depth = float(look["body_depth"])
    family = look["family"]
    curve = float(FAMILY_PRESETS[family]["body_curve"])
    profile = np.clip(np.sin(np.pi * uc), 0.0, 1.0) ** curve
    half = profile * (0.245 / max(1.5, ratio)) * 4.0 * depth
    half *= 1.0 - 0.22 * np.maximum(uc - 0.65, 0) / 0.35
    if look["head_shape"] == "flat":
        half *= 1.0 - 0.16 * np.maximum(uc - 0.7, 0) / 0.3
    if look["head_shape"] == "pointed":
        half *= 1.0 - 0.40 * np.maximum(uc - 0.66, 0) / 0.34
    snout = float(look["snout"])
    snout_start = 0.82
    snout_length = 0.20 * snout
    snout_u = np.clip((xx - snout_start) / max(0.001, snout_length), 0.0, 1.0)
    snout_half = (0.035 * depth * np.power(1.0 - snout_u, 0.82)
                  if snout > 0.0 else np.zeros_like(xx))
    cy = 0.50 + 0.015 * np.sin(uc * math.pi)
    body = (u >= 0) & (u <= 1) & (np.abs(yy - cy) <= half)
    beak = ((snout > 0.0) & (xx >= snout_start) &
            (xx <= snout_start + snout_length) &
            (np.abs(yy - 0.50) <= snout_half))
    body |= beak

    dorsal = _poly_mask(xx, yy, ((0.31, 0.50 - 0.20 * depth),
                                (0.43, 0.23), (0.63, 0.50 - 0.13 * depth)))
    anal = _poly_mask(xx, yy, ((0.48, 0.50 + 0.14 * depth),
                              (0.63, 0.79), (0.70, 0.50 + 0.08 * depth)))
    tail = _poly_mask(xx, yy, ((0.12, 0.47), (0.025, 0.27), (0.075, 0.49),
                              (0.025, 0.73), (0.12, 0.53)))
    if look["tail_shape"] != "forked":
        tail = _poly_mask(xx, yy, ((0.12, 0.46), (0.03, 0.32), (0.045, 0.68), (0.12, 0.54)))
    pectoral = _poly_mask(xx, yy, ((0.50, 0.50), (0.37, 0.68), (0.57, 0.61)))
    fins = dorsal | anal | tail | pectoral
    silhouette = body | fins

    lower = yy > cy + half * 0.35
    upper = yy < cy - half * 0.42
    side_band = np.broadcast_to(side, base.shape).copy()
    fish = np.where(upper[..., None], top, side_band)
    fish = np.where(lower[..., None], belly, fish)
    fin_color = np.clip(side * 0.76 + top * 0.24, 0, 1)
    fish[fins] = fin_color

    pattern = look["scale_pattern"]
    if pattern == "bars":
        marks = (np.sin(u * math.tau * 7.5 + 0.4) > 0.64) & body & (np.abs(yy - cy) < half * 0.82)
        fish[marks] *= 0.67
    elif pattern == "stripes":
        phase = np.sin((yy - cy) * 110 + np.sin(u * 24) * 2.2)
        marks = (phase > 0.66) & body & (np.abs(yy - cy) < half * 0.75)
        fish[marks] *= 0.70
    elif pattern == "spots":
        spots = (np.sin(u * 104) * np.cos(yy * 145) > 0.79)
        fish[spots & body] *= 0.55
    elif pattern in {"mottled", "vermiculate"}:
        cells = np.sin(u * 57 + np.sin(yy * 79) * (2.8 if pattern == "vermiculate" else 1.2))
        fish[(cells > (0.62 if pattern == "mottled" else 0.78)) & body] *= 0.62
    grain = rng.normal(0.0, 0.035, (height, width, 1)).astype(np.float32)
    fish = np.clip(fish * (1.0 + grain), 0, 1)
    base[silhouette] = fish[silhouette]

    # Soft pigment bleed under the hand-ink contour.
    dilated = np.zeros_like(silhouette)
    eroded = np.ones_like(silhouette)
    for dy in (-2, -1, 0, 1, 2):
        for dx in (-2, -1, 0, 1, 2):
            shifted = np.roll(np.roll(silhouette, dy, axis=0), dx, axis=1)
            dilated |= shifted
            if abs(dx) <= 1 and abs(dy) <= 1:
                eroded &= shifted
    halo = dilated & ~silhouette
    base[halo] = base[halo] * 0.77 + side * 0.23
    edge = silhouette & ~eroded
    base[edge] = base[edge] * 0.40 + np.asarray((0.15, 0.13, 0.11), np.float32) * 0.60

    # Gill arc, mouth, and eye use a dry-ink line with a small paper highlight.
    gill = (np.abs(((xx - 0.735) / 0.044) ** 2 + ((yy - 0.50) / 0.14) ** 2 - 1.0) < 0.045)
    gill &= silhouette & (yy > 0.46) & (yy < 0.64)
    base[gill] *= 0.52
    mouth_y = 0.5 + {"terminal": 0.0, "inferior": 0.012, "upturned": -0.012}[look["mouth"]]
    mouth_x = 0.86 + 0.13 * snout
    mouth = (np.abs(xx - mouth_x) < 0.003) & (np.abs(yy - mouth_y) < 0.012)
    base[mouth] = (0.12, 0.10, 0.08)
    barbels = int(look["barbels"])
    if barbels:
        # Fine paired whiskers extend from the mouth; keep them long enough to
        # survive the 128×64 book thumbnail downsample.
        for index in range(barbels):
            for sign in (-1.0, 1.0):
                x0 = 0.888 - index * 0.007
                y0 = mouth_y + sign * 0.004
                x1 = x0 + 0.045 + index * 0.006
                y1 = mouth_y + sign * (0.033 + index * 0.008)
                dx, dy = x1 - x0, y1 - y0
                pad = 0.003
                left = max(0, int((min(x0, x1) - pad) * width))
                right = min(width, int((max(x0, x1) + pad) * width) + 1)
                top = max(0, int((min(y0, y1) - pad) * height))
                bottom = min(height, int((max(y0, y1) + pad) * height) + 1)
                local_x, local_y = xx[top:bottom, left:right], yy[top:bottom, left:right]
                t = np.clip(((local_x - x0) * dx + (local_y - y0) * dy) /
                            (dx * dx + dy * dy), 0.0, 1.0)
                distance = np.hypot(local_x - (x0 + t * dx), local_y - (y0 + t * dy))
                base[top:bottom, left:right][distance < 0.0022] = (0.20, 0.16, 0.11)
    eye_x = 0.825 - 0.08 * snout
    eye = ((xx - eye_x) / 0.011) ** 2 + ((yy - 0.455) / 0.011) ** 2 <= 1
    base[eye] = (0.08, 0.07, 0.06)
    eye_glint = ((xx - eye_x - 0.003) / 0.003) ** 2 + ((yy - 0.452) / 0.003) ** 2 <= 1
    base[eye_glint] = (0.96, 0.91, 0.72)
    if shiny and _species_rows()[species_id].get("shiny") == "starry":
        stars = (np.sin(xx * 420) * np.cos(yy * 370) > 0.995) & body
        base[stars] = (1.0, 0.97, 0.76)
    card = np.clip(base * 255 + 0.5, 0, 255).astype(np.uint8)
    # A double paper rule frames each field-guide plate.
    card[3:5, 3:-3] = (151, 133, 103)
    card[-5:-3, 3:-3] = (151, 133, 103)
    card[3:-3, 3:5] = (151, 133, 103)
    card[3:-3, -5:-3] = (151, 133, 103)
    card[6:7, 6:-6] = (202, 184, 148)
    card[6:-6, 6:7] = (202, 184, 148)
    return _freeze(card)


def fish_card(species_id: str, shiny: bool = False) -> np.ndarray:
    """Return a cached 512×256 watercolor card for GPU or software UI use."""
    return _card_cached(species_id, bool(shiny))


@lru_cache(maxsize=CARD_CACHE_ENTRIES)
def _thumbnail_cached(species_id: str, shiny: bool = False) -> np.ndarray:
    return _freeze(resize_rgb(fish_card(species_id, shiny), *THUMBNAIL_SIZE))


def fish_thumbnail(species_id: str, shiny: bool = False) -> np.ndarray:
    return _thumbnail_cached(species_id, bool(shiny))


def cache_bytes() -> int:
    """Approximate resident bytes across the bounded card and thumbnail LRUs."""
    cards = _card_cached.cache_info().currsize * CARD_SIZE[0] * CARD_SIZE[1] * 3
    thumbs = (_thumbnail_cached.cache_info().currsize
              * THUMBNAIL_SIZE[0] * THUMBNAIL_SIZE[1] * 3)
    return cards + thumbs


def card_cache_limit_bytes(entries: int = CARD_CACHE_ENTRIES) -> int:
    return entries * (CARD_SIZE[0] * CARD_SIZE[1] * 3 + THUMBNAIL_SIZE[0] * THUMBNAIL_SIZE[1] * 3)


def clear_caches() -> None:
    haul_mesh.cache_clear()
    _card_cached.cache_clear()
    _thumbnail_cached.cache_clear()
    _species_rows.cache_clear()


class FishCardPainter:
    """Apply the watercolor paint pass to cached card pixels on a GL context."""

    _VERTEX = """
        #version 330
        in vec2 in_pos;
        out vec2 card_uv;
        void main() {
            gl_Position = vec4(in_pos, 0.0, 1.0);
            card_uv = in_pos * 0.5 + 0.5;
        }
    """
    _FRAGMENT = """
        #version 330
        uniform sampler2D source_card;
        uniform float variant;
        in vec2 card_uv;
        out vec4 frag;
        float hash21(vec2 p) {
            p = fract(p * vec2(123.34, 345.45));
            p += dot(p, p + 34.345);
            return fract(p.x * p.y);
        }
        void main() {
            vec2 uv = vec2(card_uv.x, 1.0 - card_uv.y);
            vec3 color = texture(source_card, uv).rgb;
            float paper = hash21(floor(gl_FragCoord.xy * 0.75) + variant * 91.0) - 0.5;
            float wash = 0.965 + 0.035 * hash21(floor(gl_FragCoord.xy / 8.0));
            vec3 quantized = floor(color * 5.0 + 0.5) / 5.0;
            vec3 paint = mix(color, quantized, 0.27) * wash + paper * 0.055;
            frag = vec4(clamp(paint, 0.0, 1.0), 1.0);
        }
    """

    def __init__(self, context):
        import moderngl

        self.ctx = context
        self.program = context.program(vertex_shader=self._VERTEX, fragment_shader=self._FRAGMENT)
        quad = np.asarray(((-1, -1), (1, -1), (1, 1),
                           (-1, -1), (1, 1), (-1, 1)), np.float32)
        self.vertex_buffer = context.buffer(quad.tobytes())
        self.vertex_array = context.vertex_array(self.program, [(self.vertex_buffer, "2f", "in_pos")])
        self.source = context.texture(CARD_SIZE, 3, dtype="f1")
        self.source.filter = (moderngl.LINEAR, moderngl.LINEAR)
        self.output = context.texture(CARD_SIZE, 3, dtype="f1")
        self.framebuffer = context.framebuffer(color_attachments=[self.output])
        self.program["source_card"].value = 0
        self.source.use(0)
        self._last_key = None
        self._last_image = None

    def render(self, species_id: str, shiny: bool = False) -> np.ndarray:
        import moderngl

        key = (species_id, bool(shiny))
        if key == self._last_key:
            return self._last_image
        image = fish_card(species_id, shiny)
        self.source.write(image.tobytes())
        self.source.use(0)
        self.framebuffer.use()
        self.ctx.viewport = (0, 0, *CARD_SIZE)
        self.ctx.disable(moderngl.DEPTH_TEST)
        self.program["variant"].value = float(_card_seed(species_id, shiny) & 0xFFFF)
        self.vertex_array.render(mode=moderngl.TRIANGLES, vertices=6)
        raw = self.framebuffer.read(components=3, alignment=1)
        self._last_image = _freeze(
            np.frombuffer(raw, np.uint8)
            .reshape(CARD_SIZE[1], CARD_SIZE[0], 3)[::-1]
            .copy()
        )
        self._last_key = key
        return self._last_image

    def close(self) -> None:
        for value in (self.framebuffer, self.output, self.source,
                      self.vertex_array, self.vertex_buffer, self.program):
            try:
                value.release()
            except Exception:
                pass


_FONT_3X5 = {
    "A": (2, 5, 7, 5, 5), "B": (6, 5, 6, 5, 6), "C": (3, 4, 4, 4, 3),
    "D": (6, 5, 5, 5, 6), "E": (7, 4, 6, 4, 7), "F": (7, 4, 6, 4, 4),
    "G": (3, 4, 5, 5, 3), "H": (5, 5, 7, 5, 5), "I": (7, 2, 2, 2, 7),
    "J": (1, 1, 1, 5, 2), "K": (5, 5, 6, 5, 5), "L": (4, 4, 4, 4, 7),
    "M": (5, 7, 7, 5, 5), "N": (5, 7, 7, 7, 5), "O": (2, 5, 5, 5, 2),
    "P": (6, 5, 6, 4, 4), "Q": (2, 5, 5, 3, 1), "R": (6, 5, 6, 5, 5),
    "S": (3, 4, 2, 1, 6), "T": (7, 2, 2, 2, 2), "U": (5, 5, 5, 5, 7),
    "V": (5, 5, 5, 5, 2), "W": (5, 5, 7, 7, 5), "X": (5, 5, 2, 5, 5),
    "Y": (5, 5, 2, 2, 2), "Z": (7, 1, 2, 4, 7),
    "0": (7, 5, 5, 5, 7), "1": (2, 6, 2, 2, 7), "2": (6, 1, 2, 4, 7),
    "3": (6, 1, 2, 1, 6), "4": (5, 5, 7, 1, 1), "5": (7, 4, 6, 1, 6),
    "6": (3, 4, 6, 5, 2), "7": (7, 1, 2, 2, 2), "8": (2, 5, 2, 5, 2),
    "9": (2, 5, 3, 1, 6), " ": (0, 0, 0, 0, 0), "-": (0, 0, 7, 0, 0),
}


def _tiny_label(image: np.ndarray, label: str, x: int, y: int, color=(54, 58, 48)) -> None:
    cursor = x
    for character in label.upper()[:23]:
        glyph = _FONT_3X5.get(character, _FONT_3X5["-"])
        for row, bits in enumerate(glyph):
            for column in range(3):
                if bits & (1 << (2 - column)):
                    image[y + row, cursor + column] = color
        cursor += 4


def fish_card_contact_sheet(card_renderer=None) -> np.ndarray:
    """Normal and shiny thumbnails for every species, each with a printed label."""
    from .data import SPECIES

    cols, cell_w, cell_h = 9, THUMBNAIL_SIZE[0], 80
    entries = [(species, shiny) for species in SPECIES for shiny in (False, True)]
    rows = math.ceil(len(entries) / cols)
    sheet = np.empty((rows * cell_h, cols * cell_w, 3), np.uint8)
    sheet[:] = (224, 215, 193)
    for index, (species, shiny) in enumerate(entries):
        row, col = divmod(index, cols)
        x, y = col * cell_w, row * cell_h
        title = ("SHINY " if shiny else "FIELD ") + species.name.upper()
        _tiny_label(sheet, title, x + 3, y + 2, (77, 68, 48) if shiny else (54, 58, 48))
        if card_renderer is None:
            thumbnail = fish_thumbnail(species.id, shiny)
        else:
            thumbnail = resize_rgb(card_renderer(species.id, shiny), *THUMBNAIL_SIZE)
        sheet[y + 15:y + 79, x:x + cell_w] = thumbnail
    return sheet

