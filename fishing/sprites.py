"""Procedural shore sprites. Baked once, tinted when drawn.

Shapes are big on purpose. A tree on the far bank is only a few dozen
pixels tall, so the silhouette has to read before the texture does.
"""

from __future__ import annotations

import numpy as np


def _img(w, h) -> np.ndarray:
    return np.zeros((h, w, 4), dtype=np.uint8)


def _stamp(img, color, mask):
    img[mask] = color


def _tri(img, ax, ay, bx, by, cx, cy, color):
    h, w, _ = img.shape
    minx = max(int(min(ax, bx, cx)), 0)
    maxx = min(int(max(ax, bx, cx)) + 1, w - 1)
    miny = max(int(min(ay, by, cy)), 0)
    maxy = min(int(max(ay, by, cy)) + 1, h - 1)
    if minx > maxx or miny > maxy:
        return
    ys, xs = np.mgrid[miny:maxy + 1, minx:maxx + 1]
    area = (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
    if abs(area) < 1:
        return
    w0 = (bx - xs) * (cy - ys) - (by - ys) * (cx - xs)
    w1 = (cx - xs) * (ay - ys) - (cy - ys) * (ax - xs)
    w2 = (ax - xs) * (by - ys) - (ay - ys) * (bx - xs)
    if area < 0:
        mask = (w0 <= 0) & (w1 <= 0) & (w2 <= 0)
    else:
        mask = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
    region = img[miny:maxy + 1, minx:maxx + 1]
    region[mask] = color


def _ellipse(img, cx, cy, rx, ry, color):
    h, w, _ = img.shape
    yy, xx = np.mgrid[0:h, 0:w]
    mask = (xx - cx) ** 2 / (rx * rx) + (yy - cy) ** 2 / (ry * ry) <= 1
    _stamp(img, color, mask)


def pine() -> np.ndarray:
    img = _img(56, 112)
    img[78:108, 25:32] = (96, 68, 42, 255)
    img[100:110, 22:35] = (78, 54, 34, 255)
    tiers = (
        (8, 24, 48, 18, 86, 46),
        (22, 10, 46, 14, 74, 40),
        (38, 6, 50, 16, 96, 46),
        (54, 4, 52, 12, 68, 34),
        (70, 8, 48, 20, 58, 30),
    )
    for apex_y, left, right, g0, g1, g2 in tiers:
        mid = 28
        base = apex_y + 28
        _tri(img, mid, apex_y, left, base, right, base, (g0, g1, g2, 255))
        _tri(img, mid, apex_y + 10, left + 2, base, right - 2, base, (g0 - 6, g1 - 18, g2 - 8, 255))
    return img


def oak() -> np.ndarray:
    img = _img(72, 88)
    # Canopy first, trunk stamped over it so the stem stays visible.
    _ellipse(img, 36, 36, 28, 24, (28, 78, 36, 255))
    _ellipse(img, 28, 30, 16, 14, (46, 108, 48, 255))
    _ellipse(img, 46, 42, 14, 12, (18, 58, 26, 255))
    _ellipse(img, 34, 26, 10, 8, (62, 124, 58, 255))
    img[52:84, 32:41] = (102, 72, 46, 255)
    img[76:86, 28:46] = (86, 60, 38, 255)
    img[54:80, 33:36] = (128, 96, 64, 255)
    return img


def cypress() -> np.ndarray:
    img = _img(48, 128)
    h, w = img.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    # Flared buttress. Wide at the water, narrow through the middle.
    t = np.clip((yy - 28) / 96.0, 0.0, 1.0)
    half = 3.0 + t * t * 14.0
    trunk = (np.abs(xx - 24) <= half) & (yy >= 26) & (yy < 126)
    _stamp(img, (86, 64, 44, 255), trunk)
    _stamp(img, (118, 90, 62, 255), trunk & (xx < 22) & (yy > 40))
    _stamp(img, (62, 46, 32, 255), trunk & (xx > 28) & (yy > 70))
    _ellipse(img, 24, 24, 12, 20, (16, 58, 36, 255))
    _ellipse(img, 22, 18, 7, 10, (28, 78, 44, 255))
    # Moss hangs off the crown in a few strands.
    drape = (yy > 20) & (yy < 78) & (np.abs(xx - 24) < 11) & (((xx * 3 + yy) % 5) == 0)
    _stamp(img, (14, 42, 28, 255), drape)
    return img


def rock() -> np.ndarray:
    img = _img(48, 32)
    _ellipse(img, 24, 18, 20, 12, (92, 90, 82, 255))
    _ellipse(img, 18, 16, 10, 8, (128, 124, 112, 255))
    _ellipse(img, 30, 20, 9, 6, (68, 66, 60, 255))
    h, w, _ = img.shape
    yy, xx = np.mgrid[0:h, 0:w]
    shadow = (yy > 20) & (img[:, :, 3] > 0)
    img[shadow, 0] = (img[shadow, 0].astype(np.int16) * 0.65).astype(np.uint8)
    img[shadow, 1] = (img[shadow, 1].astype(np.int16) * 0.65).astype(np.uint8)
    img[shadow, 2] = (img[shadow, 2].astype(np.int16) * 0.65).astype(np.uint8)
    return img


def stump() -> np.ndarray:
    img = _img(28, 24)
    _ellipse(img, 14, 10, 11, 6, (140, 104, 68, 255))
    img[10:22, 6:22] = (102, 74, 48, 255)
    img[12:20, 8:14] = (78, 54, 34, 255)
    img[11:13, 10:18] = (64, 44, 28, 255)
    return img


def knee() -> np.ndarray:
    img = _img(18, 32)
    img[8:30, 7:12] = (92, 68, 46, 255)
    img[4:12, 5:14] = (118, 88, 58, 255)
    img[14:28, 8:11] = (70, 50, 34, 255)
    img[26:31, 5:15] = (62, 48, 32, 255)
    return img


def reed() -> np.ndarray:
    img = _img(24, 48)
    for x, lean in ((6, 0), (11, 1), (16, -1)):
        for y in range(16, 46):
            xx = x + lean * (y // 16)
            if 0 <= xx < 24:
                img[y, xx] = (48, 78, 36, 255)
        img[12:18, x - 1:x + 2] = (92, 64, 36, 255)
        img[10:13, x:x + 1] = (120, 86, 48, 255)
    return img


def buoy(rgb: tuple[int, int, int], flagged: bool) -> np.ndarray:
    img = _img(16, 28)
    img[12:22, 4:12] = (*rgb, 255)
    img[10:13, 6:10] = (40, 36, 32, 255)
    img[14:18, 5:7] = (min(rgb[0] + 40, 255), min(rgb[1] + 40, 255), min(rgb[2] + 40, 255), 255)
    img[22:25, 6:10] = (30, 30, 28, 255)
    if flagged:
        img[2:12, 8:10] = (40, 32, 24, 255)
        img[3:8, 10:15] = (170, 40, 32, 255)
    return img


def bake(buoy_rgb: tuple[int, int, int]) -> dict[str, np.ndarray]:
    r, g, b = [int(c * 255) for c in buoy_rgb]
    return {
        "pine": pine(),
        "oak": oak(),
        "cypress": cypress(),
        "rock": rock(),
        "stump": stump(),
        "knee": knee(),
        "reed": reed(),
        "buoy": buoy((r, g, b), False),
        "buoy_flag": buoy((r, g, b), True),
    }
