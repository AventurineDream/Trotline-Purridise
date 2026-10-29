"""The boat tips gently into starlight: the travel transition shared with Crater.

Travel to or from the Lagoon plays this short sequence. It is built from the
last frame shown on the source water and the first frame on the destination,
so it reads no simulation state and changes nothing: the world stays paused
while it plays. The tip into the reflection runs first, the new lake loads
under the full starfield, and the boat then rights itself on the new water.
Reduced Motion replaces the tip and the streaming stars with a still crossfade.

Crater's chapter-four reading of the reflection can call `frame` too; this
module needs no lake beyond the two frames it is given.
"""

from __future__ import annotations

import math

import numpy as np

DURATION = 2.4  # seconds for the whole sequence
TIP_END = 0.45  # the tip completes; the destination loads under the stars here
RISE_START = 0.6  # the destination begins to surface
_STARS = 420


def touches_starlight(source: str, destination: str) -> bool:
    return "nebula" in (source, destination)


def _ease(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3.0 - 2.0 * t)


def _starfield(h, w, t, reduced_motion):
    """Deep violet sky with stars streaming outward from the centre."""
    yy = np.linspace(0, 1, h, dtype=np.float32)[:, None, None]
    sky = (np.array([.05, .03, .12], np.float32) * (1 - yy)
           + np.array([.16, .07, .28], np.float32) * yy) * np.ones((1, w, 1), np.float32)
    rng = np.random.default_rng(1729)
    angle = rng.uniform(0, math.tau, _STARS)
    reach = rng.uniform(.03, 1.0, _STARS)
    warmth = rng.uniform(0, 1, _STARS)
    if not reduced_motion:
        # Stars race outward as the boat falls through the reflection.
        reach = np.mod(reach + t * 1.3, 1.0) + .02
    x = (w * .5 + np.cos(angle) * reach * w * .62).astype(np.int64)
    y = (h * .5 + np.sin(angle) * reach * h * .62).astype(np.int64)
    inside = (x >= 0) & (x < w - 1) & (y >= 0) & (y < h - 1)
    colour = (np.array([.80, .86, 1.0], np.float32) * (1 - warmth[:, None])
              + np.array([1.0, .78, .95], np.float32) * warmth[:, None]) * (.45 + reach[:, None] * .75)
    for dy in (0, 1):
        for dx in (0, 1):
            np.add.at(sky, (y[inside] + dy, x[inside] + dx), colour[inside])
    return np.clip(sky, 0, 1)


def frame(source: np.ndarray, destination: np.ndarray | None, t: float, *,
          reduced_motion: bool = False) -> np.ndarray:
    """One RGB8 frame at progress t in [0, 1].

    `destination` may be None until RISE_START; the tip needs only the source.
    """
    h, w = source.shape[:2]
    stars = _starfield(h, w, t, reduced_motion)
    src = source.astype(np.float32) / 255.0
    if reduced_motion:
        if t < RISE_START or destination is None:
            out = src * (1 - _ease(t / RISE_START)) + stars * _ease(t / RISE_START)
        else:
            a = _ease((t - RISE_START) / (1 - RISE_START))
            out = stars * (1 - a) + destination.astype(np.float32) / 255.0 * a
        return np.rint(np.clip(out, 0, 1) * 255).astype(np.uint8)
    if t < RISE_START or destination is None:
        tip = _ease(t / TIP_END)
        # The view pitches down: the horizon rises, the mirror fills the frame.
        shift = int(tip * h * .55)
        mirrored = np.concatenate((src[shift:], src[::-1][:shift]), axis=0) if shift else src
        out = mirrored * (1 - tip * .85) + stars * tip * .85
        if t > TIP_END:
            out = stars
        return np.rint(np.clip(out, 0, 1) * 255).astype(np.uint8)
    rise = _ease((t - RISE_START) / (1 - RISE_START))
    dst = destination.astype(np.float32) / 255.0
    # The boat rights itself: the destination's horizon settles from above.
    shift = int((1 - rise) * h * .35)
    settled = np.concatenate((dst[::-1][h - shift:], dst[:h - shift]), axis=0) if shift else dst
    out = stars * (1 - rise) + settled * rise
    return np.rint(np.clip(out, 0, 1) * 255).astype(np.uint8)
