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

# Shared anatomical defaults per family: eye size and fin height. Species-specific
# measurements, colours and traits live in species.json and legendaries.json, so a
# new fish never needs a new geometry generator.
FAMILY_PRESETS = {
    "catfish": {"eye_scale": 0.78, "fin_height": 0.16},
    "bass": {"eye_scale": 0.88, "fin_height": 0.22},
    "sunfish": {"eye_scale": 0.92, "fin_height": 0.22},
    "trout": {"eye_scale": 0.84, "fin_height": 0.20},
    "gar": {"eye_scale": 0.60, "fin_height": 0.12},
    "sucker": {"eye_scale": 0.72, "fin_height": 0.15},
    "minnow": {"eye_scale": 0.90, "fin_height": 0.11},
    "pike": {"eye_scale": 0.76, "fin_height": 0.18},
    "sculpin": {"eye_scale": 0.92, "fin_height": 0.25},
    "eel": {"eye_scale": 0.62, "fin_height": 0.08},
    "cosmic": {"eye_scale": 1.0, "fin_height": 0.24},
    "sturgeon": {"eye_scale": 0.55, "fin_height": 0.16},
    "salamander": {"eye_scale": 0.80, "fin_height": 0.06},
    "ray": {"eye_scale": 0.70, "fin_height": 0.10},
    "whale": {"eye_scale": 0.70, "fin_height": 0.14},
}

# A shiny repaints the fish in one of six shared palettes (back, flank, belly).
SHINY_PALETTES = {
    "albino": ((0.53, 0.37, 0.30), (0.91, 0.77, 0.65), (1.0, 0.92, 0.79)),
    "golden": ((0.50, 0.32, 0.10), (0.95, 0.68, 0.19), (1.0, 0.88, 0.48)),
    "starry": ((0.16, 0.23, 0.47), (0.42, 0.67, 0.91), (0.82, 0.90, 1.0)),
    "glow": ((0.08, 0.34, 0.40), (0.18, 0.78, 0.73), (0.71, 1.0, 0.88)),
    "ink": ((0.08, 0.09, 0.15), (0.27, 0.31, 0.44), (0.63, 0.66, 0.75)),
    "rose": ((0.45, 0.19, 0.25), (0.88, 0.40, 0.48), (1.0, 0.76, 0.68)),
}


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
    # Legendary IDs never collide with species IDs, so one table serves both.
    content = load_content_v2()
    return {**content.species, **content.legendaries}


def fish_look(species_id: str) -> dict:
    row = _species_rows().get(species_id)
    if row is None or not isinstance(row.get("look"), dict):
        raise KeyError(f"fish look is missing for species {species_id!r}")
    return row["look"]


def legendary_ids() -> tuple[str, ...]:
    return tuple(load_content_v2().legendaries)


def _rgb(values) -> np.ndarray:
    return np.asarray(values, dtype=np.float32)


def _palette(species_id: str, shiny: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if shiny:
        return tuple(_rgb(value) for value in SHINY_PALETTES[_species_rows()[species_id]["shiny"]])
    colors = fish_look(species_id)["colors"]
    return tuple(_rgb(colors[key]) for key in ("top", "side", "belly"))


def _freeze(array: np.ndarray) -> np.ndarray:
    array.setflags(write=False)
    return array


@lru_cache(maxsize=MESH_CACHE_ENTRIES)
def haul_mesh(species_id: str, lake_id: str = "briar", shiny: bool = False) -> FishMesh:
    """Build a deterministic mesh of about 1.5k triangles, cached by lake and fish.

    It shares the card's outline, fins and features and is painted from the card.
    """
    from .fishart import haul_geometry

    look = fish_look(species_id)
    preset = FAMILY_PRESETS[look["family"]]
    return _finish_mesh(*haul_geometry(look, fish_card(species_id, shiny), eye_scale=preset["eye_scale"],
                                       fin_height=preset["fin_height"]))


def _finish_mesh(vertices: np.ndarray, triangles: np.ndarray, colors_array: np.ndarray) -> FishMesh:
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


def legendary_idle(legendary_id: str) -> dict:
    """The authored underwater idle: sway (mesh units at the tail), rate (Hz) and bob."""
    return dict(load_content_v2().legendaries[legendary_id]["idle"])


def idle_mesh(legendary_id: str, t: float, *, reduced_motion: bool = False) -> FishMesh:
    """A legendary's slow underwater idle at t seconds, for its scene.

    A body wave travels from the head to the tail and grows toward it, while
    the whole fish bobs at half the wave's rate, so one loop lasts 2 / rate
    seconds. Under Reduced Motion the fish holds its resting pose.
    """
    row = _species_rows()[legendary_id]
    rest = haul_mesh(legendary_id, row["lake"], False)
    if reduced_motion:
        return rest
    idle = row["idle"]
    vertices = rest.vertices.copy()
    x = vertices[:, 0]
    along = (x.max() - x) / max(float(x.max() - x.min()), 1e-6)  # 0 at the snout, 1 at the tail tip
    phase = math.tau * float(idle["rate"]) * t
    vertices[:, 2] += np.float32(idle["sway"]) * along ** 2 * np.sin(phase - 2.4 * along).astype(np.float32)
    vertices[:, 1] += np.float32(idle["bob"] * math.sin(phase * 0.5))
    return _finish_mesh(vertices, rest.triangles, rest.colors)


def _card_seed(species_id: str, shiny: bool) -> int:
    return zlib.crc32((species_id + ("/shiny" if shiny else "/normal")).encode("utf-8"))


@lru_cache(maxsize=CARD_CACHE_ENTRIES)
def _card_cached(species_id: str, shiny: bool = False) -> np.ndarray:
    return _freeze(paint_card_layers(species_id, shiny)[0])


def paint_card_layers(species_id: str, shiny: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Paint one card without caching: (RGB8 card, fish silhouette mask)."""
    from .fishart import paint_card

    look = fish_look(species_id)
    top, side, belly = _palette(species_id, shiny)
    preset = FAMILY_PRESETS[look["family"]]
    shiny_kind = _species_rows()[species_id]["shiny"] if shiny else None
    return paint_card(look, top, side, belly, np.random.default_rng(_card_seed(species_id, shiny)),
                      size=CARD_SIZE, shiny_kind=shiny_kind, eye_scale=preset["eye_scale"],
                      fin_height=preset["fin_height"])


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

