"""Software triangle raster and sprite blit. Float color, smaller z is closer."""

from __future__ import annotations

import numpy as np


def clip_near(pts: np.ndarray, near: float = 0.22) -> list[np.ndarray]:
    """Sutherland-Hodgman against camera z = near. pts is (N, 3)."""
    if len(pts) == 0:
        return []
    out: list[np.ndarray] = []
    n = len(pts)
    for i in range(n):
        a = pts[i]
        b = pts[(i + 1) % n]
        a_in = a[2] >= near
        b_in = b[2] >= near
        if a_in and b_in:
            out.append(b)
        elif a_in and not b_in:
            denom = b[2] - a[2]
            t = 0.0 if abs(denom) < 1e-8 else (near - a[2]) / denom
            out.append(a + (b - a) * np.float32(t))
        elif (not a_in) and b_in:
            denom = b[2] - a[2]
            t = 0.0 if abs(denom) < 1e-8 else (near - a[2]) / denom
            out.append(a + (b - a) * np.float32(t))
            out.append(b)
    return out


def raster_tri(color: np.ndarray, zbuf: np.ndarray, xy, zz, rgb: np.ndarray) -> None:
    """xy is 3 (x, y) screen points, zz is 3 camera depths, rgb is 0-1."""
    h, w, _ = color.shape
    xs = np.array([xy[0][0], xy[1][0], xy[2][0]], dtype=np.float32)
    ys = np.array([xy[0][1], xy[1][1], xy[2][1]], dtype=np.float32)
    zs = np.asarray(zz, dtype=np.float32)
    minx = max(int(np.floor(xs.min())), 0)
    maxx = min(int(np.ceil(xs.max())), w - 1)
    miny = max(int(np.floor(ys.min())), 0)
    maxy = min(int(np.ceil(ys.max())), h - 1)
    if minx > maxx or miny > maxy:
        return
    x0, y0 = xs[0], ys[0]
    x1, y1 = xs[1], ys[1]
    x2, y2 = xs[2], ys[2]
    area = (x1 - x0) * (y2 - y0) - (y1 - y0) * (x2 - x0)
    if abs(float(area)) < 0.5:
        return
    gx = np.arange(minx, maxx + 1, dtype=np.float32) + 0.5
    gy = np.arange(miny, maxy + 1, dtype=np.float32) + 0.5
    px, py = np.meshgrid(gx, gy)
    w0 = (x1 - px) * (y2 - py) - (y1 - py) * (x2 - px)
    w1 = (x2 - px) * (y0 - py) - (y2 - py) * (x0 - px)
    w2 = (x0 - px) * (y1 - py) - (y0 - py) * (x1 - px)
    # Flip with the signed area so either winding works.
    w0 /= area
    w1 /= area
    w2 /= area
    mask = (w0 >= -0.001) & (w1 >= -0.001) & (w2 >= -0.001)
    if not np.any(mask):
        return
    z = w0 * zs[0] + w1 * zs[1] + w2 * zs[2]
    sub_z = zbuf[miny:maxy + 1, minx:maxx + 1]
    hit = mask & (z < sub_z)
    if not np.any(hit):
        return
    sub_c = color[miny:maxy + 1, minx:maxx + 1]
    sub_c[hit] = rgb
    sub_z[hit] = z[hit]


def blit_sprite(
    color: np.ndarray,
    zbuf: np.ndarray,
    sprite: np.ndarray,
    x: float,
    y: float,
    depth: float,
    dest_h: int,
    tint: np.ndarray,
    fog: float,
    fog_color: np.ndarray,
) -> None:
    """Bottom-center anchored. sprite is uint8 RGBA. depth is camera z."""
    if dest_h < 2 or depth < 0.3:
        return
    sh, sw = sprite.shape[:2]
    dh = int(dest_h)
    dw = max(1, int(round(dh * (sw / sh))))
    if dh > 900:
        dw = max(1, int(round(dw * (900 / dh))))
        dh = 900
    if dw > 700:
        return
    h, w, _ = color.shape
    x0 = int(round(x - dw * 0.5))
    y0 = int(round(y - dh))
    x1 = x0 + dw
    y1 = y0 + dh
    if x1 <= 0 or y1 <= 0 or x0 >= w or y0 >= h:
        return
    ys = np.minimum((np.arange(dh) * sh / dh).astype(np.int32), sh - 1)
    xs = np.minimum((np.arange(dw) * sw / dw).astype(np.int32), sw - 1)
    samp = sprite[ys][:, xs]
    cx0 = max(x0, 0)
    cy0 = max(y0, 0)
    cx1 = min(x1, w)
    cy1 = min(y1, h)
    sy0 = cy0 - y0
    sx0 = cx0 - x0
    patch = samp[sy0:sy0 + (cy1 - cy0), sx0:sx0 + (cx1 - cx0)]
    alpha = patch[:, :, 3] > 40
    sz = np.float32(depth * 0.98)
    sub_z = zbuf[cy0:cy1, cx0:cx1]
    hit = alpha & (sz < sub_z)
    if not np.any(hit):
        return
    rgb = patch[:, :, :3].astype(np.float32) / 255.0
    rgb *= tint.astype(np.float32)
    rgb = rgb * (1.0 - fog) + fog_color.astype(np.float32) * fog
    dest = color[cy0:cy1, cx0:cx1]
    dest[hit] = np.clip(rgb, 0.0, 1.0)[hit]
    sub_z[hit] = sz
