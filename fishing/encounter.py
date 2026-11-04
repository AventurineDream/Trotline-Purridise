"""V1-37: a legendary's encounter in the haul, and the book's photo of it (02 §7.2, 06 §6.3).

When the hook that carries a legendary reaches the top of the haul, the haul slows into a calm
scene of `SCENE_S` seconds before the book page:
- **The water stills** (0–1.2 s): the haul's ripples settle and the lake turns glassy. Both
  renderers read the stillness through `caldera.reflection_strength`, as V1-35's Settle In does.
- **The line hums** (0.8–2.8 s): the line trembles, the hum sounds, and "The line hums."
  is captioned.
- **The fish surfaces beside the boat** (1.6–3.8 s), in its slow idle (`fishmesh.legendary_idle`).
  It then holds at the surface while its name comes up.

Then the book page: the photo, the weight and the release (`photo`, drawn by `ui.py`).

- The first time each legendary is met, nothing skips or speeds the scene. The page then
  remembers it (`presented`), and every later encounter can be skipped (Esc / B) or hurried
  (hold E / A).
- **Zero-G Winch** (02 §9): with the winch owned, a legendary haul plays the smooth winch
  variant. The winch draws the line in without a sway, its hum is steady, and the fish
  floats up clear of the water in a soft glow.
- **The Caldera Fire-Lizard** is not a fish. It brings a warm glow up through the cold spring
  and steam off its back, and its page is stamped "NOT A FISH!" (01 §7).
- The Star-Whale is witnessed, not hooked: its rising is V1-35's staging (`finale.py`).
- Reduced Motion shows each beat finished and still. The water is glassy and the fish has
  surfaced from the first frame. The line doesn't tremble, so its hum shows as marks beside it.
- Bot keeps quiet during the scene (05 §5.4). His line comes with the release.

Everything here is presentation: the catch, its record and its release are V1-36's.
"""

from __future__ import annotations

from functools import lru_cache
import math

import numpy as np

SCENE_S = 5.0          # the calm scene, inside 02 §7.2's 4–6 s
PHOTO_S = 3.0          # how long the book page holds before the haul moves on
PAGE_SETTLE_S = 0.5    # the page ignores keys this long, so keys pressed through the scene don't turn it
STILL = (0.0, 1.2)     # the water stills
HUM = (0.8, 2.8)       # the line hums
RISE = (1.6, 3.8)      # the fish surfaces beside the boat
NAME = (3.6, 4.4)      # its name comes up
BARS_S = 0.8           # the letterbox closes in this long

SPRITE = (384, 192)    # the fish's sprite, as `ui._haul_mesh_sprite` draws a haul fish
SPRITE_SCALE = 136.0   # sprite pixels per mesh unit
PITCH = 0.45           # seen from the boat, a little from above

# The bespoke beat (01 §7): the Fire-Lizard is a glowing giant salamander, and the book is delighted.
BESPOKE = {
    "caldera_fire_lizard": {"stamp": "NOT A FISH!", "note": "Not a fish at all. The book is delighted.",
                            "warm": (1.0, 0.52, 0.18)},
}
STAMP = "LEGENDARY"


def _smooth(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


def _span(t: float, span: tuple[float, float]) -> float:
    return _smooth((t - span[0]) / (span[1] - span[0]))


def caught_ids() -> tuple[str, ...]:
    """The ten legendaries a line can bring up, in book order."""
    from .legendary import LEGENDARY_DATA
    return tuple(lid for lid, row in LEGENDARY_DATA.items() if row["kind"] == "caught")


def is_legendary(catch) -> bool:
    return catch is not None and bool(getattr(catch, "legendary", False))


def _page(v2, legendary_id: str) -> dict | None:
    pages = v2.get("legendaries") if isinstance(v2, dict) else None
    page = pages.get(legendary_id) if isinstance(pages, dict) else None
    return page if isinstance(page, dict) else None


def presented(v2, legendary_id: str) -> bool:
    """Whether the Skipper has seen this legendary's scene through once."""
    page = _page(v2, legendary_id)
    return bool(page and page.get("presented") is True)


def mark_presented(v2, legendary_id: str) -> None:
    """The scene was seen through: from now on it can be skipped."""
    if not isinstance(v2, dict):
        return
    pages = v2.setdefault("legendaries", {})
    if not isinstance(pages, dict):
        pages = v2["legendaries"] = {}
    page = pages.setdefault(legendary_id, {})
    if not isinstance(page, dict):
        page = pages[legendary_id] = {}
    page["presented"] = True


def variant(state) -> str:
    """'winch' once the Zero-G Winch is owned (02 §9), else the Skipper's paws: 'hands'."""
    return "winch" if state.owns_tool("zero_g_winch") else "hands"


def bespoke(legendary_id: str) -> dict:
    return BESPOKE.get(legendary_id, {})


def look(t: float, *, reduced: bool = False) -> dict:
    """Each beat's progress at t seconds into the scene, 0..1. Under Reduced Motion every beat
    is finished, and the hum has no tremble."""
    if reduced:
        hum = 1.0 if HUM[0] <= t < HUM[1] else 0.0
        return {"still": 1.0, "bars": 1.0, "hum": hum, "tremble": 0.0, "rise": 1.0, "name": 1.0}
    hum = math.sin(math.pi * (t - HUM[0]) / (HUM[1] - HUM[0])) if HUM[0] < t < HUM[1] else 0.0
    return {"still": _span(t, STILL), "bars": _smooth(t / BARS_S), "hum": hum, "tremble": hum,
            "rise": _span(t, RISE), "name": _span(t, NAME)}


def water_still(ui, *, reduced: bool = False) -> float:
    """How glassy the lake is for the haul on screen: the scene's stillness, held through the
    book page. 0 when no legendary is being presented."""
    if getattr(ui, "mode", "") != "haul" or not getattr(ui, "haul_legendary", ""):
        return 0.0
    if ui.haul_phase == "encounter":
        return look(ui.haul_phase_timer, reduced=reduced)["still"]
    if ui.haul_phase == "card":
        return 1.0
    return 0.0


def hum_due(t0: float, t1: float) -> bool:
    """The hum sounds once, as the scene's clock passes its start."""
    return t0 <= HUM[0] < t1 or (t0 == 0.0 and HUM[0] == 0.0)


@lru_cache(maxsize=4)
def fish_sprite(legendary_id: str) -> np.ndarray:
    """The legendary at rest, lit and seen a little from above, as RGBA (read-only, cached).
    Rasterized once per legendary; the idle is a cheap warp of it (`posed`)."""
    from .fishmesh import _species_rows, haul_mesh
    from .raster import raster_tri

    width, height = SPRITE
    mesh = haul_mesh(legendary_id, _species_rows()[legendary_id]["lake"], False)
    cp, sp = math.cos(PITCH), math.sin(PITCH)
    v, n = mesh.vertices, mesh.normals
    y = v[:, 1] * cp - v[:, 2] * sp
    depth = v[:, 1] * sp + v[:, 2] * cp
    ny = n[:, 1] * cp - n[:, 2] * sp
    nz = n[:, 1] * sp + n[:, 2] * cp
    light = np.asarray((0.30, 0.86, -0.42), np.float32)
    light /= np.linalg.norm(light)
    shade = 0.50 + 0.50 * np.abs(n[:, 0] * light[0] + ny * light[1] + nz * light[2])
    screen = np.stack((width * 0.5 + v[:, 0] * SPRITE_SCALE, height * 0.5 - y * SPRITE_SCALE), axis=1)
    colour = np.zeros((height, width, 3), np.float32)
    zbuf = np.full((height, width), 1e6, np.float32)
    for index, tri in enumerate(mesh.triangles):
        raster_tri(colour, zbuf, screen[tri], 3.0 - depth[tri], mesh.colors[index] * shade[index])
    sprite = np.zeros((height, width, 4), np.uint8)
    sprite[:, :, :3] = np.clip(colour * 255.0 + 0.5, 0, 255).astype(np.uint8)
    sprite[:, :, 3] = (zbuf < 1e6).astype(np.uint8) * 255
    sprite.setflags(write=False)
    return sprite


def idle_offsets(legendary_id: str, t: float) -> np.ndarray:
    """Each sprite column's vertical shift, in pixels, for the idle at t seconds.

    It is `fishmesh.idle_mesh`'s motion as the boat sees it: the body wave runs from the snout
    to the tail and grows toward it, and its side-to-side sway shows by the view's tilt, while
    the whole fish bobs at half the wave's rate."""
    from .fishmesh import legendary_idle
    idle = legendary_idle(legendary_id)
    alpha = fish_sprite(legendary_id)[:, :, 3]
    cols = np.flatnonzero(alpha.max(axis=0))
    width = SPRITE[0]
    if cols.size == 0:
        return np.zeros(width, np.int32)
    snout, tail = float(cols.max()), float(cols.min())   # the snout is to the right
    along = np.clip((snout - np.arange(width, dtype=np.float32)) / max(snout - tail, 1.0), 0.0, 1.0)
    phase = math.tau * float(idle["rate"]) * t
    sway = float(idle["sway"]) * along ** 2 * np.sin(phase - 2.4 * along) * math.sin(PITCH)
    bob = float(idle["bob"]) * math.sin(phase * 0.5) * math.cos(PITCH)
    return np.round((sway + bob) * SPRITE_SCALE).astype(np.int32)


def posed(legendary_id: str, t: float, *, reduced: bool = False) -> np.ndarray:
    """The fish's sprite at t seconds of its idle. Reduced Motion holds the resting pose."""
    sprite = fish_sprite(legendary_id)
    if reduced:
        return sprite
    shift = idle_offsets(legendary_id, t)
    rows = np.arange(SPRITE[1], dtype=np.int32)[:, None] + shift[None, :]
    inside = (rows >= 0) & (rows < SPRITE[1])
    out = np.take_along_axis(sprite, np.clip(rows, 0, SPRITE[1] - 1)[:, :, None], axis=0).copy()
    out[~inside] = 0
    return out


def glow_colour(legendary_id: str) -> tuple[float, float, float] | None:
    """The halo a glowing legendary brings up with it: its side colour, by its look's glow."""
    warm = bespoke(legendary_id).get("warm")
    if warm is not None:
        return tuple(warm)
    from .fishmesh import fish_look
    looked = fish_look(legendary_id)
    glow = float(looked.get("glow") or 0.0)
    if glow <= 0.0:
        return None
    side = np.asarray(looked["colors"]["side"], np.float32)
    return tuple(float(c) for c in np.clip(side * 0.55 + glow * 0.45, 0.0, 1.0))


def _photo_palette(lake_id: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    from .lakes import LAKES
    palette = LAKES[lake_id]["palette"]
    water = np.asarray(palette["water"], np.float32)
    land = np.asarray(palette["land"], np.float32)
    sky = np.clip(water * 0.6 + np.asarray((0.62, 0.66, 0.70), np.float32) * 0.7, 0.0, 1.0)
    return sky, land, water


@lru_cache(maxsize=6)
def photo(legendary_id: str, width: int, height: int) -> np.ndarray:
    """The book's photo of a legendary at the surface beside the boat, RGB8 (read-only, cached).

    A strip of far shore over the lake's water, the fish in the middle with the rings it left,
    its glow if it has one, and the gunwale with the Skipper's paw in the corner, toned
    like an old print."""
    from .fishmesh import _species_rows
    from .imageops import resize_rgb

    width, height = max(32, int(width)), max(24, int(height))
    sky, land, water = _photo_palette(_species_rows()[legendary_id]["lake"])
    yy = np.arange(height, dtype=np.float32)[:, None] / height
    xx = np.arange(width, dtype=np.float32)[None, :] / width
    shore = 0.20
    deep = np.clip((yy - shore) / (1.0 - shore), 0.0, 1.0)
    water_rows = water * 1.6 * (1.0 - deep[..., None] * 0.45) + sky * 0.18
    image = np.where((yy < shore)[..., None], sky * (1.0 - yy[..., None] * 0.8), water_rows)
    image = np.broadcast_to(image, (height, width, 3)).copy()
    band = (yy >= shore - 0.07) & (yy < shore)
    hills = shore - 0.07 + 0.03 * np.sin(xx * 9.0 + 1.3) * np.sin(xx * 3.1)
    image[np.broadcast_to(band & (yy >= hills), (height, width))] = land * 0.85
    cx, cy = 0.52, 0.58
    glow = glow_colour(legendary_id)
    if glow is not None:
        d = ((xx - cx) / 0.42) ** 2 + ((yy - cy) / 0.22) ** 2
        image += np.asarray(glow, np.float32) * (0.55 * np.exp(-d * 2.2))[..., None]
    for r, k in ((0.40, 0.16), (0.30, 0.10)):  # the rings it left on the still water
        d = np.sqrt(((xx - cx) / r) ** 2 + ((yy - cy) / (r * 0.42)) ** 2)
        image += k * np.clip(1.0 - np.abs(d - 1.0) * 30.0, 0.0, 1.0)[..., None]
    sprite = fish_sprite(legendary_id)
    fw = int(width * 0.74)
    fh = max(1, fw * sprite.shape[0] // sprite.shape[1])
    small = resize_rgb(sprite[:, :, :3], fw, fh).astype(np.float32) / 255.0
    mask = resize_rgb(np.repeat(sprite[:, :, 3:4], 3, axis=2), fw, fh)[:, :, :1].astype(np.float32) / 255.0
    x0, y0 = int(width * cx - fw / 2), int(height * cy - fh / 2)
    ax, ay = max(0, x0), max(0, y0)
    bx, by = min(width, x0 + fw), min(height, y0 + fh)
    if ax < bx and ay < by:
        part = small[ay - y0:by - y0, ax - x0:bx - x0]
        a = mask[ay - y0:by - y0, ax - x0:bx - x0] * 0.92
        lower = (np.arange(ay, by, dtype=np.float32)[:, None, None] / height) > cy  # below its waterline
        part = np.where(lower, part * 0.62 + water * 0.38, part)
        image[ay:by, ax:bx] = image[ay:by, ax:bx] * (1.0 - a) + part * a
    # The gunwale and a paw on it, in the bottom-left corner.
    rail = yy > 0.86 - 0.22 * xx
    image[np.broadcast_to(rail, (height, width))] = (0.30, 0.21, 0.14)
    edge = np.abs(yy - (0.86 - 0.22 * xx)) < 0.012
    image[np.broadcast_to(edge, (height, width))] = (0.55, 0.42, 0.28)
    paw = ((xx - 0.13) / 0.075) ** 2 + ((yy - 0.86) / 0.06) ** 2 <= 1.0
    image[np.broadcast_to(paw, (height, width))] = (0.72, 0.57, 0.44)
    # Toned like an old print: warm, a little faded, darker at the corners.
    grey = image.mean(axis=2, keepdims=True)
    image = image * 0.72 + grey * np.asarray((1.06, 0.98, 0.84), np.float32) * 0.28
    vignette = 1.0 - 0.32 * (((xx - 0.5) * 1.6) ** 2 + ((yy - 0.5) * 1.6) ** 2)
    image = image * vignette[..., None] + 0.05
    out = np.clip(image * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out.setflags(write=False)
    return out
