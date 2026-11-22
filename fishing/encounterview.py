"""V1-37: drawing a legendary's encounter over the haul, and its book page (`encounter.py`).

`ui.UI._haul` hands over the parts that change when the hook carries a legendary: the still
water, the humming line (or the Zero-G Winch), the fish surfacing beside the boat, its name,
and then the book page with the photo, the weight and the release.
"""

from __future__ import annotations

import math

import numpy as np

from . import encounter
from .imageops import resize_rgb

PAPER = (232, 224, 200)
PAPER_INK = (36, 58, 53)
FADED = (82, 102, 91)
OCHRE = (124, 82, 32)
RUST = (150, 62, 38)
LEATHER = (40, 64, 59)
PRINT_BORDER = (246, 241, 226)
WINCH_RIM = (150, 236, 222)
WINCH_BODY = (58, 52, 76)


def hum_line(u, frame, x0, y0, x1, y1, color, width, alpha, tremble: float, t: float):
    """A line that trembles as it hums: a standing wave, strongest at its middle."""
    if tremble <= 0.0:
        u._haul_segment(frame, x0, y0, x1, y1, color, width, alpha)
        return
    length = math.hypot(x1 - x0, y1 - y0) or 1.0
    nx, ny = -(y1 - y0) / length, (x1 - x0) / length
    amplitude = tremble * max(2.0, frame.shape[0] / 180.0)
    wobble = math.sin(t * math.tau * 6.5)
    points = []
    for i in range(15):
        s = i / 14
        off = amplitude * math.sin(math.pi * s) * wobble
        points.append((x0 + (x1 - x0) * s + nx * off, y0 + (y1 - y0) * s + ny * off))
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        u._haul_segment(frame, ax, ay, bx, by, color, width, alpha)


def hum_marks(u, frame, x0, y0, x1, y1, strength: float):
    """Three short marks beside the line's middle: the hum, seen without sound or motion."""
    if strength <= 0.05:
        return
    length = math.hypot(x1 - x0, y1 - y0) or 1.0
    dx, dy = (x1 - x0) / length, (y1 - y0) / length
    nx, ny = -dy, dx
    mx, my = (x0 + x1) / 2, (y0 + y1) / 2
    size = max(5.0, frame.shape[0] / 90.0)
    for k, gap in enumerate((1.6, 2.6, 3.6)):
        for side in (-1, 1):
            cx, cy = mx + nx * side * size * gap, my + ny * side * size * gap
            half = size * (0.9 - 0.18 * k)
            u._haul_segment(frame, cx - dx * half, cy - dy * half, cx + dx * half, cy + dy * half,
                            (226, 232, 206), 2, 0.75 * strength)


def still_water(u, frame, state, water_y: int, still: float):
    """The stilled lake below the line, in the lake's own water colour, deepening toward the
    boat, so the scene reads as a look over the side."""
    from .lakes import LAKES
    h = frame.shape[0]
    rows = h - water_y
    if rows <= 0:
        return
    from .weather import lighting_at
    water = np.asarray(LAKES.get(state.lake_id, LAKES["briar"])["palette"]["water"], np.float32)
    light = lighting_at(state.game_minutes, state)
    # Lit as the hour is: bright and sky-tinted by day, dark under the night sky.
    day = 1.0 - 0.78 * float(light["night"])
    top = np.clip(water * 255 * 1.9 * day + np.asarray(light["horizon"], np.float32) * 255 * 0.30, 0, 255)
    top = top + (top.mean() - top) * 0.5 * float(light.get("overcast", 0.0))  # greyer under cloud
    deep = top * 0.55
    k = np.linspace(0.0, 1.0, rows, dtype=np.float32)[:, None, None]
    colour = top * (1.0 - k) + deep * k
    alpha = 0.84 * still
    region = frame[water_y:].astype(np.float32)
    frame[water_y:] = (region * (1.0 - alpha) + colour * alpha).astype(np.uint8)


def winch(u, frame, cx, h):
    """The Zero-G Winch at the gunwale: a dark drum between luminous rims (02 §9)."""
    top, height, width = int(h * 0.77), int(h * 0.09), int(h * 0.20)  # above the letterbox
    u._round_fill(frame, cx - width / 2, top, width, height, WINCH_BODY, 0.96)
    for x in (cx - width / 2 + 3, cx + width / 2 - 3):
        u._haul_oval(frame, x, top + height / 2, width * 0.05, height * 0.55, WINCH_RIM, 0.9)
    u._haul_segment(frame, cx - width * 0.35, top + height * 0.5, cx + width * 0.35, top + height * 0.5,
                    (92, 86, 116), 3, 0.9)
    return cx, top


def soft_glow(frame, cx, cy, rx, ry, colour, strength: float):
    """A soft light on the water, added to the frame and fading out from its centre."""
    h, w = frame.shape[:2]
    x0, x1 = max(0, int(cx - rx * 1.6)), min(w, int(cx + rx * 1.6) + 1)
    y0, y1 = max(0, int(cy - ry * 1.6)), min(h, int(cy + ry * 1.6) + 1)
    if x0 >= x1 or y0 >= y1 or strength <= 0.0:
        return
    yy = (np.arange(y0, y1, dtype=np.float32)[:, None] - cy) / max(1.0, ry)
    xx = (np.arange(x0, x1, dtype=np.float32)[None, :] - cx) / max(1.0, rx)
    a = (strength * np.exp(-(xx * xx + yy * yy) * 2.4))[..., None]
    region = frame[y0:y1, x0:x1].astype(np.float32)
    frame[y0:y1, x0:x1] = np.clip(region + np.asarray(colour, np.float32) * 255.0 * a, 0, 255).astype(np.uint8)


def _blend_sprite(frame, sprite, x, y, *, alpha: float, below: int | None, water, depth: float):
    """Blit an RGBA sprite; rows below the waterline are tinted toward the water by depth."""
    h, w = sprite.shape[:2]
    dh, dw = frame.shape[:2]
    x0, y0 = max(0, int(x)), max(0, int(y))
    x1, y1 = min(dw, int(x) + w), min(dh, int(y) + h)
    if x0 >= x1 or y0 >= y1 or alpha <= 0.0:
        return
    patch = sprite[y0 - int(y):y1 - int(y), x0 - int(x):x1 - int(x)].astype(np.float32)
    a = patch[:, :, 3:4] * (alpha / 255.0)
    rgb = patch[:, :, :3]
    if below is not None and depth > 0.0:
        under = (np.arange(y0, y1)[:, None, None] >= below)
        rgb = np.where(under, rgb * (1.0 - depth) + np.asarray(water, np.float32) * depth, rgb)
    region = frame[y0:y1, x0:x1].astype(np.float32)
    frame[y0:y1, x0:x1] = np.clip(region * (1.0 - a) + rgb * a, 0, 255).astype(np.uint8)


def fish(u, frame, state, legendary_id: str, beats: dict, t: float, *, reduced: bool, winched: bool,
         water_y: int):
    """The legendary surfacing beside the boat in its idle, with its glow, if it has one."""
    h, w = frame.shape[:2]
    rise = beats["rise"]
    sprite = encounter.posed(legendary_id, t, reduced=reduced)
    fw = int(min(w * 0.42, 600))
    fh = max(1, fw * sprite.shape[0] // sprite.shape[1])
    image = resize_rgb(sprite, fw, fh)
    cx = w * 0.68
    rest = water_y + h * 0.035
    cy = (rest - h * 0.15 * rise) if winched else (water_y + h * 0.10 + (rest - water_y - h * 0.10) * rise)
    glow = encounter.glow_colour(legendary_id)
    if winched:
        glow = glow or (0.45, 0.92, 0.86)
    if glow is not None and rise > 0.0:
        warm = bool(encounter.bespoke(legendary_id).get("warm"))
        soft_glow(frame, cx, rest + h * 0.01, fw * 0.62, h * 0.07, glow, (0.75 if warm else 0.5) * rise)
    if encounter.bespoke(legendary_id).get("warm") and rise > 0.0:
        # Warm walks under the cold (05 §8.5): steam lifts off its back.
        for k in range(6):
            sx = cx - fw * 0.30 + k * fw * 0.12
            drift = 0.0 if reduced else (t * 0.6 + k * 0.37) % 1.0
            sy = cy - fh * 0.20 - h * 0.05 * drift
            for j in range(3):
                bend = math.sin((j + k) * 1.7 + drift * 3.0) * h * 0.006
                u._haul_segment(frame, sx + bend, sy - j * h * 0.018, sx - bend, sy - (j + 1) * h * 0.018,
                                (236, 228, 214), 2, 0.38 * rise * (1.0 - 0.6 * drift) * (1.0 - j * 0.25))
    _blend_sprite(frame, image, cx - fw / 2, cy - fh / 2, alpha=0.18 + 0.82 * rise,
                  below=None if winched else int(cy), water=(34, 84, 85),
                  depth=0.55 - 0.25 * rise)
    if winched and rise > 0.0 and not reduced:
        for k in range(5):  # motes under a floating fish
            a = t * 0.8 + k * 1.3
            u._haul_oval(frame, cx + math.cos(a) * fw * 0.35, rest - h * 0.02 - (k % 3) * h * 0.02,
                         3, 3, (196, 250, 240), 0.7 * rise)


def name(u, frame, legendary_id: str, beats: dict):
    from .legendary import LEGENDARY_DATA
    h, w = frame.shape[:2]
    if beats["name"] < 0.5:
        return
    title = LEGENDARY_DATA[legendary_id]["name"].upper()
    u._backed(frame, title, w / 2, int(h * 0.14), u._size(frame, "head"), (218, 187, 124), family="sans", center=True)


def photo_frame(u, frame, state, legendary_id: str, x: int, y: int, width: int, caption: str = "") -> int:
    """The book's photo in its print border, the caption on its broad lower edge. Returns the
    frame's height. `state` dresses the Skipper's paw on the gunwale in the saved look."""
    from .skipper import mitt_rgb
    border = max(5, width // 28)
    small = u._size(frame, "small")
    foot = u.cell(small)[1] + border * 2 if caption else border
    inner_w = max(16, width - border * 2)
    inner_h = max(12, int(inner_w * 0.62))
    total = border + inner_h + foot
    u._fill(frame, x + 3, y + 4, width, total, (20, 24, 22), 0.25)
    u._fill(frame, x, y, width, total, PRINT_BORDER, 1.0)
    u._blit_rgb(frame, encounter.photo(legendary_id, inner_w, inner_h, mitt_rgb(state)), x + border, y + border)
    if caption:
        while len(caption) > 1 and u._measure(caption, small) > inner_w:
            caption = caption[:-2].rstrip() + "…"
        u._center(frame, caption, x + width / 2, y + border + inner_h + border // 2, small, FADED)
    return total


def wrap(u, text: str, size: int, width: int) -> list[str]:
    """Greedy word wrap by the drawn width of the text, not a fixed cell."""
    lines, current = [], ""
    for word in text.split():
        candidate = f"{current} {word}" if current else word
        if current and u._measure(candidate, size, "mono") > width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def _clock(hour) -> str:
    try:
        hour = float(hour) % 24.0
    except (TypeError, ValueError):
        return ""
    return f"{int(hour):02d}:{int(round((hour % 1.0) * 60)) % 60:02d}"


def photo_caption(legendary_id: str, record: dict | None) -> str:
    from .lakes import LAKES
    from .legendary import LEGENDARY_DATA
    lake = (record or {}).get("lake_id") or LEGENDARY_DATA[legendary_id]["lake"]
    where = LAKES.get(lake, {}).get("name", str(lake).title())
    when = _clock((record or {}).get("hour"))
    return f"{where} · {when}" if when else where


def card(u, frame, state, ui, catch):
    """The book page that follows the scene: the photo, the weight, and the release."""
    from .book import legendary_page
    from .legendary import LEGENDARY_DATA
    from .data import weight_string
    h, w = frame.shape[:2]
    legendary_id = catch.species
    row = LEGENDARY_DATA[legendary_id]
    page = legendary_page(legendary_id, state.v2, remember=False) or {"records": [], "story": "", "teller": ""}
    records = page["records"]
    record = records[-1] if records else None
    head, body, small = (u._size(frame, k) for k in ("head", "body", "small"))
    pw, ph = min(w - 24, 820), min(h - 24, 500)
    x, y = (w - pw) // 2, (h - ph) // 2
    u._fill(frame, 0, 0, w, h, (4, 10, 12), 0.58)
    u._fill(frame, x - 6, y - 6, pw + 12, ph + 12, LEATHER, 1.0)
    u._fill(frame, x, y, pw, ph, PAPER, 1.0)
    pad = max(12, pw // 40)
    u._text(frame, row["name"], x + pad, y + pad, head, PAPER_INK, False)
    stamp = encounter.bespoke(legendary_id).get("stamp", encounter.STAMP)
    sw = u._measure(stamp, small) + pad * 2
    sh = u.cell(small)[1] + 10
    sx, sy = x + pw - pad - sw, y + pad
    u._fill(frame, sx, sy, sw, sh, RUST if stamp != encounter.STAMP else OCHRE, 1.0)
    u._center(frame, stamp, sx + sw / 2, sy + 4, small, PAPER)
    top = y + pad + u.cell(head)[1] + pad
    compact = pw < 560
    photo_w = pw - pad * 2 if compact else int(pw * 0.48)
    if compact:
        photo_w = min(photo_w, int((ph - (top - y) - u.cell(small)[1] * 6) / 0.8))
    used = photo_frame(u, frame, state, legendary_id, x + pad, top, max(80, photo_w),
                       photo_caption(legendary_id, record))
    if compact:
        tx, ty, tw = x + pad, top + used + pad // 2, pw - pad * 2
    else:
        tx, ty, tw = x + pad * 2 + photo_w, top, pw - photo_w - pad * 3
    lines = [(f"{weight_string(catch.weight)} · record {max(1, len(records))} in the book", body, PAPER_INK)]
    note = encounter.bespoke(legendary_id).get("note")
    if note:
        lines.append((note, small, RUST))
    if not compact and page.get("story"):
        lines.append(('“' + page["story"] + '” — ' + page["teller"], small, FADED))
    lines.append(("Released back to the water. The book keeps the record.", small, PAPER_INK))
    bottom = y + ph - u.cell(small)[1] * 2 - pad
    for text, size, colour in lines:
        for part in wrap(u, text, size, tw):
            if ty + u.cell(size)[1] > bottom:
                break
            u._text(frame, part, tx, ty, size, colour, False)
            ty += u.cell(size)[1] + 4
        ty += 6
    foot = u._controls(ui, "Any key except E continues   Hold E speeds the haul",
                       "A continues   Hold A speeds the haul")
    u._center(frame, foot, w / 2, y + ph - u.cell(small)[1] - 8, small, FADED)
