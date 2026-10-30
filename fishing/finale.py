"""V1-35: what the Settle In finale looks like (02 §13.5, 05 §2.5).

The three cues are seen, not only heard: Bot's lines come as captions, and the water shows
each one where the Skipper keeps still.
- At 15 s the stars stop rippling: the Lagoon's water turns mirror-still (`settle_still`,
  which both renderers read through `caldera.reflection_strength`).
- By 30 s the star-lilies have drifted in around the boat.
- At 45 s a deep glow has risen under the water ahead.
The Star-Whale then rises out of that glow, as far as the staging's `whale` value says.

All of it is world-space faces drawn by both renderers with the Lagoon's ambient motes, inside
`ambient.MAX_FACES` with them (at most 89 of its own), and it follows the saved Settle In progress, so a reload shows the same water. Away from the calm
reflection it fades out, and once the whale is drawn the Lagoon is itself again.
"""

from __future__ import annotations

import math

import numpy as np

from .world import Face

LILIES = 8
LILY_FAR, LILY_NEAR = 26.0, 7.0      # metres from where they gather, before and after the second cue
LILY_AHEAD = 9.0                     # they gather this far ahead of the bow
GLOW_AHEAD, GLOW_RADIUS = 22.0, 9.0  # where the deep glow rises, and how wide it grows
WHALE_LENGTH = 16.0


def _smooth(t: float) -> float:
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


def _nearby(state) -> float:
    """1 within 200 m of the calm reflection, fading out by 260 m; 0 off the Lagoon."""
    if state.lake_id != "nebula":
        return 0.0
    from .lakes import place
    from .story import SETTLE_AREA, SETTLE_RADIUS_M
    found = place(SETTLE_AREA)
    if found is None:
        return 0.0
    d = math.hypot(state.x - found[1]["x"], state.z - found[1]["z"])
    return min(1.0, max(0.0, (SETTLE_RADIUS_M + 60.0 - d) / 60.0))


def settle_look(state) -> dict:
    """How far each cue shows: still water, lilies drawn in, the deep glow. 0..1 each."""
    none = {"still": 0.0, "lilies": 0.0, "glow": 0.0}
    progress = state.narrative.quests.get("story_c5_s2")
    if progress is None or progress.status not in ("active", "ready"):
        return none
    near = _nearby(state)
    if near <= 0.0:
        return none
    story = state.v2.get("story", {}) if isinstance(state.v2, dict) else {}
    settle = story.get("settle") if isinstance(story, dict) else None
    seconds = settle.get("seconds", 0.0) if isinstance(settle, dict) else 0.0
    if progress.status == "ready" or not isinstance(seconds, (int, float)) or not math.isfinite(seconds):
        seconds = 45.0 if progress.status == "ready" else 0.0
    return {"still": near * _smooth((seconds - 10.0) / 5.0),
            "lilies": near * _smooth((seconds - 12.0) / 18.0),
            "glow": near * _smooth((seconds - 30.0) / 15.0)}


def settle_still(state) -> float:
    """The mirror-still water of the first cue, for `caldera.reflection_strength`."""
    return settle_look(state)["still"]


def _frame(state):
    """The boat's position, its ahead and its right, on the water."""
    fx, fz = math.sin(state.yaw), math.cos(state.yaw)
    return state.x, state.z, (fx, fz), (fz, -fx)


def _disc(out, cx, cz, y, radius, color, emissive, segments=12):
    """A flat polygon on the water, as few quads as it takes: a fan of quads from one corner,
    (segments - 2) / 2 of them, so the finale stays inside the ambient face budget."""
    ring = [(cx + math.cos(i / segments * math.tau) * radius, y, cz + math.sin(i / segments * math.tau) * radius)
            for i in range(segments)]
    for i in range(1, segments - 1, 2):
        quad = [ring[0], ring[i], ring[i + 1], ring[min(i + 2, segments - 1)]]
        out.append(Face(np.array(quad, np.float32), np.array([0, 1, 0], np.float32),
                        np.asarray(color, np.float32), "world", emissive))


def _lilies(out, state, amount: float, t: float):
    x, z, (fx, fz), _right = _frame(state)
    x, z = x + fx * LILY_AHEAD, z + fz * LILY_AHEAD  # they gather where the Skipper is looking
    radius = LILY_FAR + (LILY_NEAR - LILY_FAR) * amount
    size = 0.9 * min(1.0, amount * 4.0)
    for i in range(LILIES):
        angle = i / LILIES * math.tau + 0.37 * i + t * 0.02
        wobble = 1.0 + 0.18 * math.sin(i * 2.3)
        lx, lz = x + math.cos(angle) * radius * wobble, z + math.sin(angle) * radius * wobble
        _disc(out, lx, lz, 0.04, size, (0.62, 0.46, 0.86), 0.6, segments=6)
        _disc(out, lx, lz, 0.07, size * 0.28, (1.0, 0.94, 0.70), 1.0, segments=4)  # the star at its heart


def glow_centre(state) -> tuple[float, float]:
    x, z, (fx, fz), _right = _frame(state)
    return x + fx * GLOW_AHEAD, z + fz * GLOW_AHEAD


def _glow(out, state, amount: float):
    cx, cz = glow_centre(state)
    _disc(out, cx, cz, 0.02, GLOW_RADIUS * amount, (0.30, 0.70, 0.85), 0.7, segments=12)
    _disc(out, cx, cz, 0.03, GLOW_RADIUS * 0.45 * amount, (0.75, 0.97, 1.0), 1.0, segments=8)


def _whale_radius(u: float) -> float:
    """The body's half-height along its length, head (0) to tail (1)."""
    return 2.1 * math.sin(math.pi * min(1.0, 0.06 + u * 0.92)) ** 0.75 * (1.0 - 0.55 * u)


def _whale(out, state, rise: float):
    """The Star-Whale, side-on across the view: it rises from the glow and arcs over the water."""
    cx, cz = glow_centre(state)
    _x, _z, (fx, fz), (rx, rz) = _frame(state)
    lift = _smooth(rise)
    y0 = -5.0 + 6.6 * lift
    tilt = 0.45 * math.sin(math.pi * min(1.0, rise * 1.3))  # nose up as it breaches, level at rest
    rings, sides = 8, 6
    body = (0.36, 0.48, 0.94)  # starlight blue, glowing in the Lagoon's dark

    def point(u, a):
        along = (u - 0.5) * WHALE_LENGTH
        r = _whale_radius(u)
        up = math.sin(a) * r * 0.8 + along * -math.sin(tilt)
        side = math.cos(a) * r
        return (cx + rx * along + fx * side, y0 + up, cz + rz * along + fz * side)

    grid = [[point(i / rings, j / sides * math.tau) for j in range(sides)] for i in range(rings + 1)]
    for i in range(rings):
        for j in range(sides):
            a, b = grid[i][j], grid[i][(j + 1) % sides]
            c, d = grid[i + 1][(j + 1) % sides], grid[i + 1][j]
            pts = np.array([a, b, c, d], np.float32)
            n = np.cross(pts[1] - pts[0], pts[3] - pts[0])
            out.append(Face(pts, n / (np.linalg.norm(n) + 1e-8), np.asarray(body, np.float32), "world", 0.8))
    tail = point(1.0, 0.0)
    for side in (-1.0, 1.0):  # the flukes, spread flat
        tip = (tail[0] + rx * 2.2 + fx * 3.4 * side, tail[1] + 0.4, tail[2] + rz * 2.2 + fz * 3.4 * side)
        back = (tail[0] - rx * 1.2, tail[1], tail[2] - rz * 1.2)
        out.append(Face(np.array([back, tail, tip, tip], np.float32), np.array([0, 1, 0], np.float32),
                        np.asarray(body, np.float32), "world", 0.8))
    for k in range(7):  # stars on the flank the Skipper sees, a little proud of the skin
        u = 0.12 + k * 0.11
        a = math.pi * (0.62 + 0.14 * (k % 3))
        px, py, pz = point(u, a)
        px, pz = px - fx * 0.12, pz - fz * 0.12
        s = 0.22 + 0.10 * (k % 2)
        out.append(Face(np.array([(px - s * rx, py, pz - s * rz), (px, py + s, pz),
                                  (px + s * rx, py, pz + s * rz), (px, py - s, pz)], np.float32),
                        np.array([-fx, 0, -fz], np.float32), np.asarray((1.0, 0.97, 0.82), np.float32), "world", 1.0))


def faces(state, world) -> list:
    """The finale's lilies, glow and whale, for `ambient.faces` on the Lagoon."""
    out = []
    if not world.nebula:
        return out
    look = settle_look(state)
    reduced = bool(state.v2.get("settings", {}).get("reduced_motion", False))
    t = 0.0 if reduced else float(state.anim)
    if look["lilies"] > 0.0:
        _lilies(out, state, look["lilies"], t)
    if look["glow"] > 0.0:
        _glow(out, state, look["glow"])
    staged = getattr(state, "stage_light", None) or {}
    if staged.get("whale", 0.0) > 0.0:
        _whale(out, state, float(staged["whale"]))
    return out


# The Skipper's drawing of the whale, as pencil strokes in a unit box (x right, y down), in
# the order they are drawn: the back, the belly, the tail, the eye, then the stars.
SKETCH = (
    ((0.08, 0.55), (0.18, 0.36), (0.36, 0.26), (0.58, 0.28), (0.76, 0.38), (0.88, 0.47)),
    ((0.08, 0.55), (0.20, 0.66), (0.42, 0.70), (0.64, 0.64), (0.80, 0.54), (0.88, 0.47)),
    ((0.88, 0.47), (0.95, 0.34), (0.99, 0.30)),
    ((0.88, 0.47), (0.96, 0.58), (0.99, 0.62)),
    ((0.20, 0.50), (0.22, 0.49)),
    ((0.40, 0.33), (0.42, 0.31)), ((0.52, 0.30), (0.54, 0.28)), ((0.64, 0.33), (0.66, 0.31)),
)


def sketch_strokes(progress: float) -> list:
    """The strokes drawn so far, the last one partly: progress 0..1 over the whole drawing."""
    lengths = [sum(math.dist(a, b) for a, b in zip(s, s[1:])) for s in SKETCH]
    budget = min(1.0, max(0.0, progress)) * sum(lengths)
    drawn = []
    for stroke, length in zip(SKETCH, lengths):
        if budget <= 0.0:
            break
        if budget >= length:
            drawn.append(list(stroke))
            budget -= length
            continue
        part = [stroke[0]]
        for a, b in zip(stroke, stroke[1:]):
            step = math.dist(a, b)
            if budget >= step:
                part.append(b)
                budget -= step
            else:
                k = budget / step if step else 0.0
                part.append((a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k))
                budget = 0.0
                break
        drawn.append(part)
        break
    return drawn
