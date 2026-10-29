"""V2 field-guide anatomy: the watercolor card painter and its matching haul mesh.

A look that names its own `colors` (instead of borrowing a legacy `palette`)
is painted here. It may also opt into markings in their own colour, a lateral
band, throat slash, parr marks, ear flaps, fin colours and edges, dorsal and
pectoral styles, extra tails, signature features, a cosmic glow, and the
sturgeon, salamander, ray and whale body plans. The haul mesh shares the
card's outline, fins and features and takes its colours from the painted card,
so the two always agree. Everything is deterministic and bounded: one 512×256
card and its silhouette per (species, shiny) request.
"""

from __future__ import annotations

import math

import numpy as np

# The ink and paper shared with the legacy painter.
PAPER = np.asarray((0.91, 0.875, 0.79), np.float32)
WASH = np.asarray((0.76, 0.83, 0.82), np.float32)
INK = np.asarray((0.15, 0.13, 0.11), np.float32)



def _rgb(value):
    return np.asarray(value, np.float32)


def _poly(xx, yy, points):
    mask = np.zeros(xx.shape, np.bool_)
    px, py = points[-1]
    for cx, cy in points:
        crosses = (py > yy) != (cy > yy)
        edge = (cx - px) * (yy - py) / (cy - py + 1e-9) + px
        mask ^= crosses & (xx < edge)
        px, py = cx, cy
    return mask


def _ellipse(xx, yy, cx, cy, rx, ry):
    return ((xx - cx) / rx) ** 2 + ((yy - cy) / ry) ** 2 <= 1.0


def _segment(xx, yy, x0, y0, x1, y1, width):
    dx, dy = x1 - x0, (y1 - y0) * 0.5
    t = np.clip(((xx - x0) * dx + (yy - y0) * 0.5 * dy) / (dx * dx + dy * dy + 1e-12), 0, 1)
    return np.hypot(xx - (x0 + t * dx), (yy - (y0 + t * dy * 2)) * 0.5) < width


def _hash(ix, iy, salt):
    value = np.sin(ix * 127.1 + iy * 311.7 + salt * 74.7) * 43758.5453
    return value - np.floor(value)


def _noise(px, py, salt):
    """Smooth value noise on an integer lattice, for irregular blotches and worm lines."""
    px, py = np.asarray(px, np.float64), np.asarray(py, np.float64)
    ix, iy = np.floor(px), np.floor(py)
    fx, fy = px - ix, py - iy
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b = _hash(ix, iy, salt), _hash(ix + 1, iy, salt)
    c, d = _hash(ix, iy + 1, salt), _hash(ix + 1, iy + 1, salt)
    return (a + (b - a) * fx + (c - a) * fy + (a - b - c + d) * fx * fy).astype(np.float32)


class _Body:
    """Profile of a side-on fish body, in card units (x across 512 px, y across 256 px)."""

    def __init__(self, look):
        self.look = look
        family = look["family"]
        snout = float(look["snout"])
        # Flowing veils and comet trails need room behind the tail.
        self.x0 = 0.26 if "comet" in look.get("features", ()) else 0.22 if look["tail_shape"] == "flowing" else 0.15
        self.x1 = 0.86 - snout * 0.10
        self.snout_len = snout * 0.14
        ratio = float(look["length_depth_ratio"])
        length = self.x1 - self.x0
        self.h = min(0.34, length * 2 / ratio * 0.5 * float(look["body_depth"]))
        self.cy = 0.50
        self.peduncle = {"eel": 0.30, "salamander": 0.32, "sturgeon": 0.30, "whale": 0.22}.get(family, 0.24)
        self.peak = {"sunfish": 0.55, "sucker": 0.58, "catfish": 0.66, "sculpin": 0.74,
                     "salamander": 0.62, "sturgeon": 0.62, "whale": 0.62}.get(family, 0.58)
        self.curve = {"eel": 0.45, "gar": 0.5, "pike": 0.55, "minnow": 0.75,
                      "sunfish": 1.05, "salamander": 0.40}.get(family, 0.85)
        features = set(look.get("features", ()))
        self.hump = 0.16 if "hump" in features else 0.0
        self.flat_belly = family in ("sturgeon", "catfish", "sculpin", "salamander")

    def shape(self, u):
        """Half-depth fraction along the body: 0 at the tail end, 1 at the snout base."""
        u = np.clip(u, 0.0, 1.0)
        w = np.where(u < self.peak, 0.5 * u / self.peak, 0.5 + 0.5 * (u - self.peak) / (1 - self.peak))
        bump = np.clip(np.sin(np.pi * w), 0, 1) ** self.curve
        s = self.peduncle + (1 - self.peduncle) * np.clip(bump, 0, 1)
        head = self.look["head_shape"]
        cap = 0.82 if head == "rounded" else 0.74 if head == "flat" else 0.70
        # The head closes as an ellipse (blunt) or a wedge (pointed).
        t = np.clip((u - cap) / (1 - cap), 0, 1)
        if head == "pointed":
            close = 1 - 0.78 * t
        else:
            close = np.sqrt(np.clip(1 - (t * 0.94) ** 2, 0, 1))
        return s * np.where(u > cap, close, 1.0)

    def outline(self, u):
        s = self.shape(u)
        top = self.cy - self.h * s * (1 + self.hump * np.exp(-((u - 0.66) / 0.14) ** 2))
        if self.look["head_shape"] == "flat":
            # The brow eases down onto a flat head instead of stepping.
            w = np.clip((u - 0.62) / 0.16, 0, 1)
            w = w * w * (3 - 2 * w)
            top = top * (1 - w) + np.maximum(top, self.cy - self.h * s * 0.72) * w
        bottom = self.cy + self.h * s * (0.86 if self.flat_belly else 1.0)
        return top, bottom

    def u(self, xx):
        return (xx - self.x0) / (self.x1 - self.x0)

    def point(self, u, v):
        """Card point at body fraction u and vertical fraction v (-1 back, +1 belly)."""
        top, bottom = self.outline(np.asarray(u, np.float32))
        x = self.x0 + u * (self.x1 - self.x0)
        mid = (top + bottom) * 0.5
        half = (bottom - top) * 0.5
        return float(x), float(mid + v * half)


def _ellipse_points(cx, cy, rx, ry, n=20, max_x=None):
    """An ellipse as a polygon, optionally cut by the vertical line x = max_x."""
    points = []
    for k in range(n):
        angle = math.tau * k / n
        x = cx + rx * math.cos(angle)
        points.append((x if max_x is None else min(x, max_x), cy + ry * math.sin(angle)))
    return points


class FinShapes:
    """Fin outlines in card units, shared by the card painter and the haul mesh.

    `fins` are the median and paired fins outside the body, `tail` the caudal
    fin, and `pectoral` the fin laid over the flank (with its ray root).
    """

    def __init__(self):
        self.fins, self.tail, self.pectoral = [], [], []
        self.pectoral_root = (0.0, 0.0)


def fin_shapes(body, look, preset_height):
    family = look["family"]
    style = look.get("dorsal_style", "normal")
    shapes = FinShapes()
    fins = shapes.fins
    h = body.h
    fin_h = preset_height * 2.0

    def at(u, v):
        return body.point(u, v)

    def dorsal(u0, u1, height, spiny=False):
        a, b = at(u0, -1), at(u1, -1)
        rise = h * height
        if spiny:
            points = [a]
            for k in range(7):
                t = (k + 0.5) / 7
                x, y = at(u0 + (u1 - u0) * t, -1)
                points.append((x, y - rise * (0.95 if k % 2 == 0 else 0.55)))
            points.append(b)
        else:
            peak_u = u0 + (u1 - u0) * 0.40
            px, py = at(peak_u, -1)
            points = [a, (px - 0.01, py - rise), (px + 0.015, py - rise * 0.88), b]
        fins.append(points)

    if family not in ("salamander", "whale", "ray"):
        count = int(look["dorsal_count"])
        if style == "sail":
            a, b = at(0.40, -1), at(0.80, -1)
            rise = h * 1.05
            fins.append([a, (a[0] - 0.01, a[1] - rise * 0.55), (a[0] + 0.05, a[1] - rise),
                         ((a[0] + b[0]) * 0.5, a[1] - rise * 1.06), (b[0] - 0.02, b[1] - rise * 0.78), b])
        elif style == "long":
            dorsal(0.08, 0.66, 0.32)
            if count > 1:
                dorsal(0.70, 0.80, 0.30)
        elif family == "sturgeon":
            dorsal(0.16, 0.30, fin_h * 1.2)
        elif count >= 2:
            dorsal(0.54, 0.74, fin_h * (1.15 if style == "spiny" else 0.95), spiny=style == "spiny")
            dorsal(0.30, 0.52, fin_h * 0.85)
        else:
            dorsal(0.40, 0.66, fin_h)
        if look["adipose"]:
            ax, ay = at(0.12, -1)
            fins.append(_ellipse_points(ax, ay - h * 0.06, 0.018, h * 0.10, 12))
        # Anal and pelvic fins on the belly.
        if style == "long" and family in ("eel", "pike", "cosmic"):
            a, b = at(0.06, 1), at(0.52, 1)
            fins.append([a, (a[0] + 0.02, a[1] + h * 0.30), (b[0], b[1] + h * 0.26), b])
        else:
            a, b = at(0.18, 1), at(0.36, 1)
            fins.append([a, ((a[0] + b[0]) * 0.5, a[1] + h * fin_h * 0.95), b])
        p, q = at(0.50, 1), at(0.58, 1)
        fins.append([p, (p[0] - 0.03, p[1] + h * fin_h * 0.85), q])
    # Pectoral fin behind the gill.
    if family == "whale":
        px, py = at(0.70, 0.55)
        fins.append([(px, py), (px - 0.10, py + h * 0.75), (px - 0.05, py + h * 0.80), (px + 0.03, py + h * 0.1)])
        dx, dy = at(0.30, -1)
        fins.append([(dx - 0.03, dy + 0.005), (dx, dy - h * 0.22), (dx + 0.02, dy + 0.005)])
    elif look.get("pectoral", "normal") == "fan":
        px, py = at(0.70, 0.15)
        shapes.pectoral.append(_ellipse_points(px - 0.04, py + h * 0.10, 0.07, h * 0.62, 24, max_x=px + 0.005))
        shapes.pectoral_root = (px, py + h * 0.10)
    elif family not in ("salamander", "ray"):
        px, py = at(0.72, 0.35)
        shapes.pectoral.append([(px, py), (px - 0.09, py + h * 0.42), (px - 0.035, py + h * 0.50)])
        shapes.pectoral_root = (px, py)
    if family == "salamander" or "legs" in look.get("features", ()):
        for leg_u in (0.30, 0.70):
            lx, ly = at(leg_u, 0.9)
            for lean in (-1, 1):
                foot = (lx + lean * 0.018 - 0.01, ly + h * 0.55)
                fins.append([(lx - 0.012, ly - 0.01), (lx + 0.012, ly - 0.01),
                             (foot[0] + 0.012, foot[1]), (foot[0] - 0.012, foot[1])])
                fins.append(_ellipse_points(foot[0], foot[1], 0.016, h * 0.07, 10))
        # A keel of tail fin above and below the tapering tail.
        a, b = at(0.02, -1), at(0.40, -1)
        fins.append([(a[0] - 0.02, a[1]), (a[0] + 0.05, a[1] - h * 0.22), (b[0], b[1])])
        a, b = at(0.02, 1), at(0.30, 1)
        fins.append([(a[0] - 0.02, a[1]), (a[0] + 0.05, a[1] + h * 0.14), (b[0], b[1])])

    # Tail.
    tail = look["tail_shape"]
    tx, ty = at(0.0, 0)
    ped = h * body.peduncle
    if tail == "forked":
        points = [(tx + 0.01, ty - ped), (tx - 0.10, ty - h * 0.85), (tx - 0.065, ty),
                  (tx - 0.10, ty + h * 0.85), (tx + 0.01, ty + ped)]
    elif tail == "rounded":
        # A fan that flares from the peduncle and closes in a round edge.
        spread = min(h * 0.62, max(ped * 1.7, h * 0.42))
        end = tx - 0.055
        cap = [(end - 0.028 * math.sin(math.pi * k / 10), ty - spread * math.cos(math.pi * k / 10))
               for k in range(11)]
        points = [(tx + 0.01, ty - ped)] + cap + [(tx + 0.01, ty + ped)]
    elif tail == "truncate":
        points = [(tx + 0.01, ty - ped), (tx - 0.075, ty - h * 0.62), (tx - 0.085, ty - h * 0.55),
                  (tx - 0.085, ty + h * 0.55), (tx - 0.075, ty + h * 0.62), (tx + 0.01, ty + ped)]
    elif tail == "heterocercal":
        points = [(tx + 0.02, ty - ped), (tx - 0.14, ty - h * 1.05), (tx - 0.10, ty - h * 0.55),
                  (tx - 0.02, ty + h * 0.05), (tx - 0.06, ty + h * 0.55), (tx + 0.02, ty + ped)]
    elif tail == "pointed":
        points = [(tx + 0.02, ty - ped * 1.1), (tx - 0.11, ty), (tx + 0.02, ty + ped * 1.1)]
    elif tail == "fluke":
        points = [(tx + 0.02, ty - ped), (tx - 0.06, ty - ped * 0.6), (tx - 0.12, ty - h * 0.18),
                  (tx - 0.13, ty - h * 0.08), (tx - 0.08, ty), (tx - 0.13, ty + h * 0.08),
                  (tx - 0.12, ty + h * 0.18), (tx - 0.06, ty + ped * 0.6), (tx + 0.02, ty + ped)]
    else:
        # A veil that billows back and droops like silk, with a scalloped trailing edge.
        reach = min(0.19, tx - 0.03)
        spread = max(h * 1.15, 0.08)
        points = [(tx + 0.02, ty - ped)]
        for k in range(7):
            t = k / 6
            points.append((tx - reach * (0.35 + 0.55 * t), ty - spread * (0.55 + 0.25 * math.sin(t * 2.2))
                           + spread * 0.55 * t * t))
        for k in range(9):
            t = k / 8
            scallop = 0.012 * math.sin(t * math.pi * 5)
            points.append((tx - reach + scallop + reach * 0.10 * t, ty + spread * (0.10 + 1.05 * t)))
        points += [(tx - reach * 0.35, ty + spread * 0.95), (tx - 0.01, ty + ped * 1.2), (tx + 0.02, ty + ped)]
    shapes.tail.append(points)
    return shapes


def snout_polygon(body, look):
    """A snout beyond the head: a wedge for pike and gar, a shovel for sturgeon (or None)."""
    if body.snout_len <= 0.004:
        return None
    family = look["family"]
    hx, hy = body.point(1.0, -0.1 if family != "sturgeon" else 0.25)
    top, bottom = body.outline(np.float32(0.985))
    root = (float(bottom) - float(top)) * (0.30 if family in ("gar", "pike") else 0.42)
    tip_y = hy + (0.03 if family == "sturgeon" else 0.0)
    reach = body.snout_len
    return [(body.x1 - 0.01, hy - root), (body.x1 + reach, tip_y - root * 0.12),
            (body.x1 + reach, tip_y + root * 0.12), (body.x1 - 0.01, hy + root)]


def mouth_point(look, body):
    mx, my = body.point(1.0, 0.0)
    mx += body.snout_len
    if look["mouth"] == "inferior":
        mx -= body.snout_len * 0.55
        my += body.h * 0.30
    return mx, my


def barbel_segments(look, body):
    """Barbels and whiskers as (x0, y0, x1, y1) segments from the mouth."""
    features = set(look.get("features", ()))
    mx, my = mouth_point(look, body)
    length = 0.08 if "whiskers" in features else 0.045
    segments = []
    for index in range(int(look["barbels"])):
        for sign in (-1.0, 1.0):
            x0, y0 = mx - 0.012 - index * 0.008, my + 0.005 + index * 0.01
            x1 = x0 + length * (1.6 if "whiskers" in features and index == 0 else 1.0) - index * 0.004
            y1 = y0 + sign * (0.03 + index * 0.012) + (0.05 if "whiskers" in features else 0.015)
            if look["family"] == "sturgeon":
                x0, y0 = mx - 0.02 - index * 0.012, my + 0.01
                x1, y1 = x0 + 0.004, y0 + 0.05
            segments.append((x0, y0, x1, y1))
    return segments


def eye_geometry(look, body, eye_scale):
    """(x, y, pupil radius) of the eye in card units."""
    family = look["family"]
    ex, ey = body.point(0.90 if family != "whale" else 0.84, -0.32)
    if family == "salamander":
        ex, ey = body.point(0.90, -0.55)
    return ex, ey, 0.011 * eye_scale * (1.3 if family == "whale" else 1.0)


def gill_segments(body):
    gx, gy = body.point(0.78, -0.6)
    return [(gx, gy + k * 0.03, gx - 0.035, gy - 0.07 + k * 0.05 + lean)
            for k, lean in enumerate((-0.04, 0.0, 0.04))]


def lure_geometry(body):
    """The lantern lure: its stalk segment and the bulb centre."""
    sx, sy = body.point(0.94, -1)
    return (sx, sy, sx + 0.05, sy - 0.12), (sx + 0.05, sy - 0.12)


def halo_centre(body):
    return body.point(0.86, -0.1)


HALO_OUTER, HALO_INNER = (0.075, 0.24), (0.064, 0.205)


def ring_geometry(body):
    """A planetary ring: centre, half-width and outer/inner half-heights."""
    rx, ry = body.point(0.52, 0)
    return rx, ry, (body.x1 - body.x0) * 0.66, body.h * 0.46, body.h * 0.30


def ribbon_points(body):
    """A long trailing ribbon from the dorsal fin, waving behind the body."""
    ox, oy = body.point(0.70, -1)
    return [(ox - k / 13 * 0.62, oy - body.h * 0.25 + 0.05 * math.sin(k / 13 * 7.0)) for k in range(14)]


# A ray is painted from above: its disc centre and half-axes in card units.
RAY_DISC = (0.56, 0.50, 0.27, 0.42)


def _fins(body, look, xx, yy, preset_height):
    """Fin masks: (outer fins, tail, (pectoral over the flank, its ray root))."""
    shapes = fin_shapes(body, look, preset_height)

    def mask(polygons):
        out = np.zeros(xx.shape, np.bool_)
        for points in polygons:
            out |= _poly(xx, yy, points)
        return out

    return mask(shapes.fins), mask(shapes.tail), (mask(shapes.pectoral), shapes.pectoral_root)


def _rays(xx, yy, root, count):
    """Fin rays fanning out from a root point (card x is twice as wide as y)."""
    angle = np.arctan2(yy - root[1], (xx - root[0]) * 2.0)
    return np.abs(np.sin(angle * count)) < 0.16


def _pattern(kind, u, v, xx, yy, scale, inside):
    """Marking mask on the body, in body coordinates u (0 tail, 1 head) and v (-1 back, 1 belly)."""
    if kind == "plain":
        return np.zeros(u.shape, np.bool_), None
    halo = None
    if kind in ("spots", "speckled", "haloed", "stars"):
        n = {"spots": 14, "speckled": 30, "haloed": 13, "stars": 22}[kind] * scale
        cu, cv = u * n, v * n * 0.42
        iu, iv = np.floor(cu), np.floor(cv)
        jitter_u = _hash(iu, iv, 1.0) * 0.6 + 0.2
        jitter_v = _hash(iu, iv, 2.0) * 0.6 + 0.2
        keep = _hash(iu, iv, 3.0) > (0.35 if kind != "speckled" else 0.45)
        du, dv = cu - iu - jitter_u, (cv - iv - jitter_v) * 2.2
        r = np.hypot(du, dv)
        radius = {"spots": 0.26, "speckled": 0.20, "haloed": 0.22, "stars": 0.12}[kind]
        if kind == "speckled":
            # Concentrated on the back and toward the tail, like cutthroat spotting.
            keep &= (v < 0.35 + (1 - u) * 0.5)
        mask = (r < radius) & keep
        if kind == "haloed":
            halo = (r < radius * 1.75) & ~mask & keep
        if kind == "stars":
            mask |= ((np.abs(du) < 0.035) & (np.abs(dv) < radius * 3.2) |
                     (np.abs(dv) < 0.06) & (np.abs(du) < radius * 2.0)) & keep
        return mask & inside, (halo & inside) if halo is not None else None
    if kind == "bars":
        n = 7 * scale
        phase = u * n
        taper = 1 - np.clip((v + 1) / 2, 0, 1) * 0.65
        return ((np.abs(phase - np.round(phase)) < 0.17 * taper) & (v < 0.55) & inside), None
    if kind == "saddles":
        n = 4.5 * scale
        phase = u * n + 0.3
        width = 0.22 * (1 - np.clip((v + 1) / 1.4, 0, 1))
        return ((np.abs(phase - np.round(phase)) < width) & (v < 0.25) & inside), None
    if kind == "stripes":
        rows = np.abs(np.sin((v + 1) * math.pi * 3.5 * scale)) < 0.22
        return rows & (np.abs(v) < 0.8) & inside, None
    if kind == "chain":
        a = np.sin(u * 52 * scale + np.sin(v * 9) * 0.8)
        b = np.sin(v * 13 * scale + np.sin(u * 30) * 0.9)
        return ((np.abs(a) < 0.22) | (np.abs(b) < 0.20)) & (v < 0.75) & inside, None
    if kind == "mottled":
        px, py = xx * 512 * scale, yy * 256 * scale
        n = _noise(px / 10, py / 7, 7.0) * 0.6 + _noise(px / 4, py / 3.5, 8.0) * 0.4
        return (n > 0.60) & inside, None
    if kind == "vermiculate":
        # Worm tracks: thin contours of smooth noise, on the back and upper flank.
        px, py = xx * 512 * scale, yy * 256 * scale
        n = _noise(px / 13, py / 10, 11.0)
        return (np.abs(n - 0.5) < 0.05) & (v < 0.25) & inside, None
    if kind == "blotched":
        n = 6 * scale
        cu, cv = u * n, v * 2.2
        iu, iv = np.floor(cu), np.floor(cv)
        r = np.hypot(cu - iu - 0.5, (cv - iv - 0.5) * 1.6)
        mask = (r < 0.32 + 0.12 * _hash(iu, iv, 5.0)) & (_hash(iu, iv, 6.0) > 0.25)
        return mask & inside, None
    raise ValueError(kind)


def _dilate(mask, radius):
    out = mask.copy()
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy <= radius * radius:
                out |= np.roll(np.roll(mask, dy, axis=0), dx, axis=1)
    return out


def paint_card(look, top, side, belly, rng, *, size=(512, 256), shiny_kind=None, eye_scale=0.9,
               fin_height=0.2):
    """Return (RGB8 card, silhouette mask) for a v2 look."""
    width, height = size
    xx, yy = np.meshgrid(np.linspace(0, 1, width, dtype=np.float32),
                         np.linspace(0, 1, height, dtype=np.float32))
    noise = rng.normal(0.0, 2.1, (height, width, 1)).astype(np.float32)
    wash = np.exp(-(((xx - 0.54) / 0.68) ** 2 + ((yy - 0.50) / 0.72) ** 2))
    base = PAPER + (WASH - PAPER) * (wash[..., None] * 0.20) + noise / 255.0
    family = look["family"]
    marks_rgb = _rgb(look["marks"]) if "marks" in look else None
    fin_rgb = _rgb(look["fins"]) if "fins" in look else np.clip(side * 0.72 + top * 0.28, 0, 1)
    if shiny_kind is not None:
        fin_rgb = np.clip(side * 0.72 + top * 0.28, 0, 1)
        marks_rgb = None
    glow = float(look.get("glow", 0.0))
    features = set(look.get("features", ()))
    scale = float(look.get("mark_scale", 1.0))

    if family == "ray":
        return _paint_ray(look, base, xx, yy, top, side, belly, marks_rgb, fin_rgb, glow, scale, rng, shiny_kind)

    body = _Body(look)
    u = body.u(xx)
    top_y, bottom_y = body.outline(u)
    inside = (u >= 0) & (u <= 1) & (yy >= top_y) & (yy <= bottom_y)
    mid = (top_y + bottom_y) * 0.5
    half = np.maximum((bottom_y - top_y) * 0.5, 1e-4)
    v = np.clip((yy - mid) / half, -1.2, 1.2)
    snout_points = snout_polygon(body, look)
    snout = _poly(xx, yy, snout_points) if snout_points else np.zeros(xx.shape, np.bool_)
    fins, tail, (pectoral, pectoral_root) = _fins(body, look, xx, yy, fin_height)
    body_mask = inside | snout
    silhouette = body_mask | fins | tail | pectoral

    # Body colour: a soft vertical gradient from back to belly.
    tv = np.clip((v + 1) / 2, 0, 1)[..., None]
    upper = np.clip(1 - tv * 2.2, 0, 1)
    lower = np.clip(tv * 2.4 - 1.25, 0, 1)
    fish = side * (1 - upper - lower) + top * upper + belly * lower
    fish = np.clip(fish, 0, 1)
    if "band" in look and shiny_kind is None:
        band = np.exp(-((v - 0.02) / 0.20) ** 2)[..., None] * (0.25 + 0.75 * np.clip((u[..., None] - 0.05) * 1.5, 0, 1))
        fish = fish * (1 - band * 0.75) + _rgb(look["band"]) * band * 0.75
    marks, halos = _pattern(look["scale_pattern"], u, v, xx, yy, scale, inside)
    if halos is not None:
        fish[halos] = fish[halos] * 0.45 + np.asarray((0.88, 0.86, 0.80), np.float32) * 0.55
    if marks_rgb is None:
        fish[marks] *= 0.60
    else:
        fish[marks] = fish[marks] * 0.18 + marks_rgb * 0.82
    if "parr" in look and shiny_kind is None:
        for k in range(8):
            cu = 0.16 + k * 0.085
            px, py = body.point(cu, 0.05)
            oval = _ellipse(xx, yy, px, py, 0.016, body.h * body.shape(np.float32(cu)) * 0.42) & inside
            fish[oval] = fish[oval] * 0.35 + _rgb(look["parr"]) * 0.65
    if "throat" in look and shiny_kind is None:
        tx, ty = body.point(0.90, 0.80)
        slash = _segment(xx, yy, tx - 0.035, ty - 0.01, tx + 0.03, ty - 0.03, 0.005)
        fish[slash] = _rgb(look["throat"])
    fish[fins | tail] = fin_rgb
    tail_root = body.point(0.0, 0.0)
    if look["tail_shape"] == "flowing":
        # Veils are sheer: the paper shows through between the rays.
        fish[tail] = fin_rgb * 0.62 + base[tail] * 0.38
    tail_rays = tail & _rays(xx, yy, (tail_root[0] + 0.02, tail_root[1]), 26)
    fish[tail_rays] *= 0.84
    if "marks" in look and look["scale_pattern"] in ("spots", "speckled", "stars") and shiny_kind is None:
        # Trout, grayling and cosmic fins carry the body's spots.
        fin_marks, _ = _pattern(look["scale_pattern"], (xx - body.x0 + 0.15) * 2.2, (yy - 0.5) * 6,
                                xx, yy, scale, (fins | tail) & ~_lower_fins(body, xx, yy))
        fish[fin_marks] = fish[fin_marks] * 0.3 + marks_rgb * 0.7
    if "fin_edge" in look and shiny_kind is None:
        edge = (fins | tail) & ~np.roll(fins | tail, -3, axis=1) & (yy > body.cy)
        fish[edge] = _rgb(look["fin_edge"])
    if pectoral.any():
        # The pectoral lies over the flank, so the body shows faintly through it.
        fish[pectoral] = fish[pectoral] * 0.42 + fin_rgb * 0.58
        fish[pectoral & _rays(xx, yy, pectoral_root, 30)] *= 0.86
        rim = pectoral & ~(~_dilate(~pectoral, 1))
        fish[rim] = fish[rim] * 0.55 + INK * 0.45
    if "ocellus" in features and shiny_kind is None:
        # A dark eyespot ringed in orange at the base of the tail (bowfin).
        ox, oy = body.point(0.07, -0.35)
        ring = _ellipse(xx, yy, ox, oy, 0.020, body.h * 0.34)
        spot = _ellipse(xx, yy, ox, oy, 0.013, body.h * 0.22)
        fish[ring & inside] = (0.95, 0.62, 0.22)
        fish[spot & inside] = (0.08, 0.08, 0.07)
    if "shoulder_spot" in features and shiny_kind is None:
        # The dark shoulder spot behind the gill cover (shad).
        sx, sy = body.point(0.70, -0.42)
        spot = _ellipse(xx, yy, sx, sy, 0.012, body.h * 0.15) & inside
        fish[spot] = fish[spot] * 0.25 + np.asarray((0.16, 0.12, 0.22), np.float32) * 0.75
    if "scutes" in features:
        for row_v in (-0.92, 0.0, 0.62):
            for k in range(14):
                cu = 0.06 + k * 0.064
                px, py = body.point(cu, row_v)
                plate = _poly(xx, yy, [(px - 0.010, py), (px, py - 0.022), (px + 0.010, py), (px, py + 0.022)])
                fish[plate] = np.clip(fish[plate] * 0.5 + np.asarray((0.92, 0.90, 0.82), np.float32) * 0.5, 0, 1)
    grain = rng.normal(0.0, 0.03, (height, width, 1)).astype(np.float32)
    fish = np.clip(fish * (1.0 + grain), 0, 1)

    # Features drawn outside the body: comet trail and glow sit under the fish.
    if "comet" in features:
        start = body.x0 + 0.03
        trail = _poly(xx, yy, [(start, body.cy - body.h * 0.55), (0.02, body.cy - body.h * 0.10),
                               (0.02, body.cy + body.h * 0.10), (start, body.cy + body.h * 0.55)])
        # Brightest where it leaves the tail fin, gone at the card edge.
        fade = np.clip((xx - 0.02) / (body.x0 - 0.12), 0, 1)[..., None] ** 1.2
        colour = np.clip(_rgb(look.get("band", (0.9, 0.95, 1.0))) * 0.55 + top * 0.45, 0, 1)
        base[trail] = base[trail] * (1 - fade[trail] * 0.75) + colour * fade[trail] * 0.75
        streaks = np.zeros(xx.shape, np.bool_)
        for k, lane in enumerate((-0.42, -0.2, 0.0, 0.22, 0.40)):
            streaks |= _segment(xx, yy, start, body.cy + body.h * lane * 1.1,
                                0.03 + 0.03 * (k % 2), body.cy + body.h * lane * 0.25, 0.0024)
        streaks &= trail
        base[streaks] = base[streaks] * (1 - fade[streaks] * 0.9) + np.clip(colour * 0.6 + 0.4, 0, 1) * fade[streaks] * 0.9
    if glow > 0:
        ring = _dilate(silhouette, 7) & ~silhouette
        colour = _rgb(look.get("band", look.get("marks", (0.8, 0.9, 1.0))))
        base[ring] = base[ring] * (1 - glow * 0.55) + colour * glow * 0.55
    ring = ring_y = None
    if "rings" in features:
        # A planetary ring: its far half passes behind the body, its near half in front.
        rx, ring_y, reach, outer, inner = ring_geometry(body)
        ring = (_ellipse(xx, yy, rx, ring_y, reach, outer)
                & ~_ellipse(xx, yy, rx, ring_y, reach * 0.86, inner))
    if "ribbon" in features:
        points = ribbon_points(body)
        ribbon = np.zeros(xx.shape, np.bool_)
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            ribbon |= _segment(xx, yy, ax, ay, bx, by, 0.006)
        ribbon &= ~silhouette
        base[ribbon] = _rgb(look.get("band", fin_rgb))
        silhouette = silhouette | ribbon
    ring_rgb = _rgb(look.get("band", (0.92, 0.78, 0.45)))
    if ring is not None:
        base[ring & (yy <= ring_y)] = ring_rgb
    base[silhouette] = fish[silhouette]
    if ring is not None:
        base[ring & (yy > ring_y)] = ring_rgb
        silhouette = silhouette | ring

    _ink(base, silhouette, side)
    _head(base, look, body, xx, yy, eye_scale, features)
    if look["scale_pattern"] == "stars":
        sparkle = marks & (_hash(np.floor(xx * 180), np.floor(yy * 90), 9.0) > 0.4)
        base[sparkle] = np.clip(base[sparkle] * 0.4 + 0.6, 0, 1)
    if shiny_kind == "starry":
        stars = (np.sin(xx * 420) * np.cos(yy * 370) > 0.995) & body_mask
        base[stars] = (1.0, 0.97, 0.76)
    return _frame(base), silhouette


def _lower_fins(body, xx, yy):
    return yy > body.cy


def _ink(base, silhouette, side):
    dilated = _dilate(silhouette, 2)
    eroded = ~_dilate(~silhouette, 1)
    halo = dilated & ~silhouette
    base[halo] = base[halo] * 0.77 + side * 0.23
    edge = silhouette & ~eroded
    base[edge] = base[edge] * 0.40 + INK * 0.60


def _head(base, look, body, xx, yy, eye_scale, features):
    family = look["family"]
    head_u = 0.80 if family not in ("sculpin", "catfish", "salamander") else 0.76
    # Gill cover arc.
    if family not in ("salamander", "whale", "ray"):
        gx, gy = body.point(head_u - 0.04, 0.0)
        gh = body.h * float(body.shape(np.float32(head_u - 0.04))) * 0.78
        arc = (np.abs(((xx - gx) / 0.040) ** 2 + ((yy - gy) / gh) ** 2 - 1.0) < 0.06) & (xx > gx)
        base[arc] *= 0.55
        if "ear" in look:
            # The sunfish ear flap: the field mark that tells bluegill, redear and longear apart.
            long_ear = "long_ear" in features
            ex, ey = body.point(head_u - 0.055 - (0.012 if long_ear else 0.0), -0.12)
            rx, ry = (0.030 if long_ear else 0.017), body.h * (0.15 if long_ear else 0.19)
            flap = _ellipse(xx, yy, ex, ey, rx, ry)
            if "ear_edge" in look:
                rim = _ellipse(xx, yy, ex - rx * 0.12, ey, rx + 0.006, ry + 0.012) & ~flap
                base[rim] = _rgb(look["ear_edge"])
            base[flap] = _rgb(look["ear"])
    elif family == "whale":
        for k in range(5):
            gx, gy = body.point(0.70 - k * 0.04, 0.55 + k * 0.08)
            pleat = _segment(xx, yy, gx - 0.10, gy + 0.01, gx + 0.06, gy, 0.0025)
            base[pleat] *= 0.75
    # Mouth.
    mx, my = mouth_point(look, body)
    mouth = look["mouth"]
    if mouth == "terminal":
        line = _segment(xx, yy, mx - 0.045, my + 0.005, mx, my, 0.0028)
    elif mouth == "inferior":
        line = _segment(xx, yy, mx - 0.035, my, mx, my - 0.01, 0.0028)
    else:
        line = _segment(xx, yy, mx - 0.04, my + 0.02, mx, my - 0.012, 0.0028)
    base[line] = (0.12, 0.10, 0.08)
    if "kype" in features:
        hook = _segment(xx, yy, mx - 0.01, my + 0.025, mx + 0.012, my - 0.01, 0.005)
        base[hook] = base[hook] * 0.3 + np.asarray((0.25, 0.18, 0.15), np.float32) * 0.7
    for x0, y0, x1, y1 in barbel_segments(look, body):
        base[_segment(xx, yy, x0, y0, x1, y1, 0.0024)] = (0.20, 0.16, 0.11)
    # Eye with an iris ring.
    ex, ey, r = eye_geometry(look, body, eye_scale)
    iris = _rgb(look.get("eye", (0.86, 0.72, 0.40)))
    ring = ((xx - ex) / (r * 1.6)) ** 2 + ((yy - ey) / (r * 3.2)) ** 2 <= 1
    pupil = ((xx - ex) / r) ** 2 + ((yy - ey) / (r * 2.0)) ** 2 <= 1
    base[ring] = iris
    base[pupil] = (0.07, 0.06, 0.05)
    glint = ((xx - ex - r * 0.3) / (r * 0.32)) ** 2 + ((yy - ey + r * 0.6) / (r * 0.64)) ** 2 <= 1
    base[glint] = (0.96, 0.92, 0.74)
    if "gills" in features:
        for x0, y0, x1, y1 in gill_segments(body):
            base[_segment(xx, yy, x0, y0, x1, y1, 0.006)] = _rgb(look.get("band", (0.95, 0.45, 0.35)))
    if "lure" in features:
        (sx, sy, tx, ty), (bx, by) = lure_geometry(body)
        base[_segment(xx, yy, sx, sy, tx, ty, 0.0025)] = (0.25, 0.22, 0.30)
        bulb = _ellipse(xx, yy, bx, by, 0.012, 0.024)
        glow_rgb = _rgb(look.get("band", (1.0, 0.92, 0.55)))
        halo = _ellipse(xx, yy, bx, by, 0.03, 0.06) & ~bulb
        base[halo] = base[halo] * 0.5 + glow_rgb * 0.5
        base[bulb] = np.clip(glow_rgb * 1.1, 0, 1)
    if "halo" in features:
        hx, hy = halo_centre(body)
        ring = _ellipse(xx, yy, hx, hy, *HALO_OUTER) & ~_ellipse(xx, yy, hx, hy, *HALO_INNER)
        base[ring] = base[ring] * 0.3 + _rgb(look.get("band", (1.0, 0.95, 0.7))) * 0.7


def _paint_ray(look, base, xx, yy, top, side, belly, marks_rgb, fin_rgb, glow, scale, rng, shiny_kind):
    """A ray seen from above: a broad disc, eyes on top, and a whip tail."""
    cx, cy, a, b = RAY_DISC
    nx, ny = (xx - cx) / a, (yy - cy) / b
    # A rounded diamond whose snout points toward the head end.
    disc = (np.abs(nx) ** 1.5 + np.abs(ny) ** 1.5) <= 1.0
    disc |= _poly(xx, yy, [(cx + a * 0.80, cy - b * 0.25), (cx + a * 1.18, cy), (cx + a * 0.80, cy + b * 0.25)])
    tail = _segment(xx, yy, cx - a * 0.85, cy, 0.04, cy + 0.02, 0.008)
    tail |= _poly(xx, yy, [(0.20, cy), (0.24, cy - 0.06), (0.27, cy)])
    silhouette = disc | tail
    radial = np.clip(np.hypot(nx, ny), 0, 1)[..., None]
    fish = top * (1 - radial) + side * radial
    fish = fish * (1 - np.clip(radial - 0.8, 0, 1) * 2) + belly * np.clip(radial - 0.8, 0, 1) * 2
    if "band" in look and shiny_kind is None:
        # Prism rays carry spectral bands across the wings.
        hue = (np.arctan2(ny, nx) / math.tau + 0.5)[..., None]
        spectrum = np.concatenate([0.5 + 0.5 * np.cos(math.tau * (hue + o)) for o in (0.0, 0.33, 0.67)], axis=-1)
        weight = np.clip(radial - 0.35, 0, 0.6)
        fish = fish * (1 - weight) + spectrum.astype(np.float32) * weight
    u = (xx - (cx - a)) / (2 * a)
    v = ny
    marks, _halo = _pattern(look["scale_pattern"], u, v, xx, yy, scale, disc)
    if marks_rgb is None:
        fish[marks] *= 0.6
    else:
        fish[marks] = fish[marks] * 0.2 + marks_rgb * 0.8
    fish[tail] = fin_rgb
    fish = np.clip(fish * (1 + rng.normal(0.0, 0.03, (xx.shape[0], xx.shape[1], 1)).astype(np.float32)), 0, 1)
    if glow > 0:
        ring = _dilate(silhouette, 7) & ~silhouette
        colour = _rgb(look.get("band", look.get("marks", (0.8, 0.9, 1.0))))
        base[ring] = base[ring] * (1 - glow * 0.55) + colour * glow * 0.55
    base[silhouette] = fish[silhouette]
    _ink(base, silhouette, side)
    for ey in (cy - 0.06, cy + 0.06):
        eye = _ellipse(xx, yy, cx + a * 0.55, ey, 0.009, 0.018)
        base[eye] = (0.07, 0.06, 0.05)
    if look["scale_pattern"] == "stars":
        sparkle = marks & (_hash(np.floor(xx * 180), np.floor(yy * 90), 9.0) > 0.4)
        base[sparkle] = np.clip(base[sparkle] * 0.4 + 0.6, 0, 1)
    return _frame(base), silhouette


def _frame(base):
    card = np.clip(base * 255 + 0.5, 0, 255).astype(np.uint8)
    card[3:5, 3:-3] = (151, 133, 103)
    card[-5:-3, 3:-3] = (151, 133, 103)
    card[3:-3, 3:5] = (151, 133, 103)
    card[3:-3, -5:-3] = (151, 133, 103)
    card[6:7, 6:-6] = (202, 184, 148)
    card[6:-6, 6:7] = (202, 184, 148)
    return card


# --- The haul mesh: the same anatomy in three dimensions. -------------------------
# Card units map to mesh units so the side-on haul sprite lines up with the card:
# x across the card becomes mesh x, y down the card becomes mesh y (up), at one scale.
MESH_SCALE = 2.6
_DEPTH_RATIO = {"sunfish": 0.42, "gar": 0.55, "pike": 0.60, "eel": 0.60, "sucker": 0.60,
                "catfish": 0.78, "sculpin": 0.85, "sturgeon": 0.75, "salamander": 0.80,
                "whale": 0.80, "cosmic": 0.65}


class _MeshBuilder:
    def __init__(self, card):
        self.card = card
        self.verts, self.tris, self.colors = [], [], []

    def to_mesh(self, x, y, z=0.0):
        return ((x - 0.5) * MESH_SCALE, (0.5 - y) * MESH_SCALE * 0.5, z)

    def sample(self, x, y):
        height, width = self.card.shape[:2]
        px = min(width - 1, max(0, int(x * width)))
        py = min(height - 1, max(0, int(y * height)))
        return self.card[py, px].astype(np.float32) / 255.0

    def triangle(self, a, b, c, colour):
        base = len(self.verts)
        self.verts.extend((a, b, c))
        self.tris.append((base, base + 1, base + 2))
        self.colors.append(np.asarray(colour, np.float32))

    def polygon(self, points, z=0.0, colour=None):
        """Fan a star-shaped card polygon about its centroid, painted from the card."""
        cx = sum(p[0] for p in points) / len(points)
        cy = sum(p[1] for p in points) / len(points)
        centre = self.to_mesh(cx, cy, z)
        for a, b in zip(points, points[1:] + points[:1]):
            paint = colour if colour is not None else self.sample((a[0] + b[0] + cx) / 3, (a[1] + b[1] + cy) / 3)
            self.triangle(centre, self.to_mesh(*a, z), self.to_mesh(*b, z), paint)

    def strip(self, x0, y0, x1, y1, width, z, colour):
        dx, dy = x1 - x0, (y1 - y0) * 0.5
        length = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / length * width, dx / length * width * 2
        a, b = self.to_mesh(x0 + nx, y0 + ny, z), self.to_mesh(x0 - nx, y0 - ny, z)
        c, d = self.to_mesh(x1 - nx, y1 - ny, z), self.to_mesh(x1 + nx, y1 + ny, z)
        self.triangle(a, b, c, colour)
        self.triangle(a, c, d, colour)

    def disc(self, x, y, rx, ry, z, colour, n=10):
        centre = self.to_mesh(x, y, z)
        ring = [self.to_mesh(x + rx * math.cos(math.tau * k / n), y + ry * math.sin(math.tau * k / n), z)
                for k in range(n)]
        for k in range(n):
            self.triangle(centre, ring[k], ring[(k + 1) % n], colour)

    def annulus(self, x, y, outer, inner, z_of, colour, n=24):
        """A flat ring; z_of(angle) tilts it so its far half can pass behind the body."""
        for k in range(n):
            a0, a1 = math.tau * k / n, math.tau * (k + 1) / n
            p = [self.to_mesh(x + r[0] * math.cos(a), y + r[1] * math.sin(a), z_of(a))
                 for a in (a0, a1) for r in (outer, inner)]
            self.triangle(p[0], p[1], p[3], colour)
            self.triangle(p[0], p[3], p[2], colour)

    def arrays(self):
        return (np.asarray(self.verts, np.float32), np.asarray(self.tris, np.int32),
                np.asarray(self.colors, np.float32))


def haul_geometry(look, card, *, eye_scale=0.9, fin_height=0.2, stations=40, sides=18):
    """(vertices, triangles, colours) for a v2 look, painted from its own card."""
    if look["family"] == "ray":
        return _ray_geometry(look, card)
    mesh = _MeshBuilder(card)
    body = _Body(look)
    features = set(look.get("features", ()))
    depth_ratio = _DEPTH_RATIO.get(look["family"], 0.62)

    # Body rings: the card outline, then the snout tapering to its tip.
    rings = []
    for k in range(stations):
        u = k / (stations - 1)
        top, bottom = body.outline(np.float32(u))
        rings.append((body.x0 + u * (body.x1 - body.x0), float(top), float(bottom)))
    snout = snout_polygon(body, look)
    if snout:
        (sx0, top0), (sx1, top1), (_x2, bottom1), (_x3, bottom0) = snout
        for k in range(1, 5):
            t = k / 4
            rings.append((sx0 + (sx1 - sx0) * t, top0 + (top1 - top0) * t, bottom0 + (bottom1 - bottom0) * t))
    half_depth = []
    base = len(mesh.verts)
    for x, top, bottom in rings:
        mid, half = (top + bottom) * 0.5, max((bottom - top) * 0.5, 0.002)
        half_depth.append(half * MESH_SCALE * 0.5 * depth_ratio)
        for j in range(sides):
            theta = math.tau * j / sides
            px, py, _ = mesh.to_mesh(x, mid - half * math.cos(theta))
            mesh.verts.append((px, py, half * MESH_SCALE * 0.5 * depth_ratio * math.sin(theta)))
    for i in range(len(rings) - 1):
        x = (rings[i][0] + rings[i + 1][0]) * 0.5
        top = (rings[i][1] + rings[i + 1][1]) * 0.5
        bottom = (rings[i][2] + rings[i + 1][2]) * 0.5
        mid, half = (top + bottom) * 0.5, (bottom - top) * 0.5
        for j in range(sides):
            # Each quad takes the card's colour where the side view sees it.
            v = -math.cos(math.tau * (j + 0.5) / sides) * 0.97
            colour = mesh.sample(x, mid + v * half)
            a, b = base + i * sides + j, base + i * sides + (j + 1) % sides
            c, d = base + (i + 1) * sides + (j + 1) % sides, base + (i + 1) * sides + j
            for tri in ((a, b, c), (a, c, d)):
                mesh.tris.append(tri)
                mesh.colors.append(colour)

    def flank(x):
        """Half-width of the body at card x, so overlays sit just proud of the flank."""
        k = int(round(min(1.0, max(0.0, body.u(x))) * (stations - 1)))
        return half_depth[k] + 0.004

    shapes = fin_shapes(body, look, fin_height)
    for points in shapes.fins + shapes.tail:
        mesh.polygon(points)
    for points in shapes.pectoral:
        mesh.polygon(points, z=flank(shapes.pectoral_root[0]))
    ex, ey, r = eye_geometry(look, body, eye_scale)
    iris = look.get("eye", (0.86, 0.72, 0.40))
    for sign in (1, -1):
        z = sign * flank(ex)
        mesh.disc(ex, ey, r * 1.6, r * 3.2, z, iris)
        mesh.disc(ex, ey, r, r * 2.0, z + sign * 0.002, (0.07, 0.06, 0.05), n=8)
    whisker = (0.20, 0.16, 0.11)
    for k, (x0, y0, x1, y1) in enumerate(barbel_segments(look, body)):
        mesh.strip(x0, y0, x1, y1, 0.0026, (1 if k % 2 else -1) * flank(x0) * 0.6, whisker)
    if "gills" in features:
        for x0, y0, x1, y1 in gill_segments(body):
            mesh.strip(x0, y0, x1, y1, 0.006, flank(x0), look.get("band", (0.95, 0.45, 0.35)))
    if "lure" in features:
        (sx, sy, tx, ty), (bx, by) = lure_geometry(body)
        mesh.strip(sx, sy, tx, ty, 0.0028, 0.0, (0.25, 0.22, 0.30))
        mesh.disc(bx, by, 0.012, 0.024, 0.0, np.clip(_rgb(look.get("band", (1.0, 0.92, 0.55))) * 1.1, 0, 1))
    if "halo" in features:
        hx, hy = halo_centre(body)
        mesh.annulus(hx, hy, HALO_OUTER, HALO_INNER, lambda a: flank(hx) + 0.01,
                     look.get("band", (1.0, 0.95, 0.7)))
    if "rings" in features:
        rx, ry, reach, outer, inner = ring_geometry(body)
        tilt = max(half_depth) * 2.2
        mesh.annulus(rx, ry, (reach, outer), (reach * 0.86, inner), lambda a: tilt * math.sin(a),
                     look.get("band", (0.92, 0.78, 0.45)), n=32)
    if "ribbon" in features:
        points = ribbon_points(body)
        colour = look.get("band", look.get("fins", (0.8, 0.8, 0.9)))
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            mesh.strip(ax, ay, bx, by, 0.006, 0.0, colour)
    return mesh.arrays()


def _ray_geometry(look, card, rings=12, segments=56):
    """A ray held up to the camera: its painted back as a shallow dome, then the whip tail."""
    mesh = _MeshBuilder(card)
    cx, cy, a, b = RAY_DISC

    def rim(angle, r):
        c, s = math.cos(angle), math.sin(angle)
        # The card's rounded diamond: |x|^1.5 + |y|^1.5 = 1.
        return (cx + a * r * math.copysign(abs(c) ** (4 / 3), c),
                cy + b * r * math.copysign(abs(s) ** (4 / 3), s))

    def dome(r):
        return 0.16 * (1 - r * r) + 0.01

    for i in range(rings):
        r0, r1 = i / rings, (i + 1) / rings
        for j in range(segments):
            a0, a1 = math.tau * j / segments, math.tau * (j + 1) / segments
            mid = rim((a0 + a1) * 0.5, (r0 + r1) * 0.5)
            colour = mesh.sample(*mid)
            p00, p01 = mesh.to_mesh(*rim(a0, r0), dome(r0)), mesh.to_mesh(*rim(a1, r0), dome(r0))
            p10, p11 = mesh.to_mesh(*rim(a0, r1), dome(r1)), mesh.to_mesh(*rim(a1, r1), dome(r1))
            if i:
                mesh.triangle(p00, p10, p11, colour)
            mesh.triangle(p00, p11, p01, colour)
    mesh.polygon([(cx + a * 0.80, cy - b * 0.25), (cx + a * 1.18, cy), (cx + a * 0.80, cy + b * 0.25)], z=dome(0.95))
    tail = look.get("fins", (0.4, 0.36, 0.5))
    mesh.strip(cx - a * 0.85, cy, 0.04, cy + 0.02, 0.008, 0.0, tail)
    mesh.polygon([(0.20, cy), (0.24, cy - 0.06), (0.27, cy)], colour=tail)
    for ey in (cy - 0.06, cy + 0.06):
        mesh.disc(cx + a * 0.55, ey, 0.009, 0.018, dome(0.55) + 0.003, (0.07, 0.06, 0.05), n=8)
    return mesh.arrays()
