"""Fireflies and a soft water ring drawn while Bot is off the boat."""

from __future__ import annotations

import math

import numpy as np

from .data import hour_of_day
from .calendar import weather_at
from .world import Face

# Blue stays under 0.3 so the mesh shader classifies these as lamps.
_LAMP = (1.0, 0.86, 0.29)
_RING = (0.62, 0.74, 0.70)
_UP = (0.0, 1.0, 0.0)


def extra_faces(state) -> list:
    """Small world-space faces drawn only while Bot is away from the boat.
    Fireflies at night and a soft ring on the water around Bot.
    """
    x = float(state.bot_x)
    z = float(state.bot_z)
    tx = float(state.bot_tx)
    tz = float(state.bot_tz)
    anim = float(state.anim)
    minutes = float(state.game_minutes)
    if not all(map(math.isfinite, (x, z, tx, tz, anim, minutes))):
        return []
    faces = _ring(x, z)
    hour = hour_of_day(minutes)
    if (hour < 5.5 or hour > 19.5) and weather_at(state, minutes) != "drizzle":
        faces.extend(_fireflies(tx, tz, anim))
    return faces


def _face(pts, normal, color) -> Face:
    n = np.asarray(normal, np.float32)
    n = n / np.float32(np.linalg.norm(n))
    return Face(
        np.asarray(pts, np.float32).reshape(4, 3),
        n,
        np.asarray(color, np.float32),
        "world",
    )


def _ring(x: float, z: float) -> list[Face]:
    faces: list[Face] = []
    inner, outer = 0.62, 0.78
    span = math.tau / 6.0 * 0.70
    for i in range(6):
        mid = (i + 0.5) * (math.tau / 6.0)
        a0, a1 = mid - span * 0.5, mid + span * 0.5
        pts = []
        for ang, rad in ((a0, inner), (a1, inner), (a1, outer), (a0, outer)):
            pts.append((x + math.cos(ang) * rad, 0.03, z + math.sin(ang) * rad))
        faces.append(_face(pts, _UP, _RING))
    return faces


def _fireflies(tx: float, tz: float, anim: float) -> list[Face]:
    faces: list[Face] = []
    half = 0.03
    for i in range(5):
        ang = i * (math.tau / 5.0) + anim * 0.17
        radius = 5.0 + 1.85 * math.sin(anim * 0.31 + i * 1.7)
        y = 0.95 + 0.42 * math.sin(anim * 0.53 + i * 2.1)
        cx = tx + math.cos(ang) * radius
        cz = tz + math.sin(ang) * radius
        side_x, side_z = -math.sin(ang), math.cos(ang)
        pts = (
            (cx - side_x * half, y - half, cz - side_z * half),
            (cx + side_x * half, y - half, cz + side_z * half),
            (cx + side_x * half, y + half, cz + side_z * half),
            (cx - side_x * half, y + half, cz - side_z * half),
        )
        faces.append(_face(pts, (math.cos(ang), 0.0, math.sin(ang)), _LAMP))
    return faces
