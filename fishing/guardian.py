"""Optional, non-blocking Whiskered Guardian sighting."""

from __future__ import annotations

import math

import numpy as np

from .data import hour_of_day

SIGHTING_SECONDS = 8.0
WATERLINE_OFFSET = 0.15


def maybe_start_sighting(state, world, mode: str) -> bool:
    """Latch the journal note when the player is present for an eligible sunset."""
    if mode != "play" or state.narrative.guardian_seen:
        return False
    if world.id != "cedar" or world.zone_at(state.x, state.z) != "deep":
        return False
    if len(set(state.narrative.ripples)) < 8:
        return False
    hour = hour_of_day(state.game_minutes + state.minute_acc)
    if not 18.0 <= hour < 20.0:
        return False

    state.narrative.guardian_seen = True
    state.guardian_sighting_pending = True
    state.guardian_sighting_started_at = None
    state.guardian_sighting_last_anim = float(state.anim)
    # The sighting is the Guardian's record, for a quest that asks to witness it (V1-32).
    state.emit_quest_event({"type": "legendary.witnessed", "species_id": "whiskered_guardian",
                            "lake_id": world.id, "zone_id": f"{world.id}:deep",
                            "game_minute": state.game_minutes})
    return True


def pause_sighting_clock(state) -> None:
    """Keep hidden time from consuming the one-time visual."""
    now = float(state.anim)
    started = getattr(state, "guardian_sighting_started_at", None)
    last = getattr(state, "guardian_sighting_last_anim", None)
    if (not getattr(state, "guardian_sighting_pending", False)
            and type(started) in (int, float) and math.isfinite(float(started))
            and type(last) in (int, float) and math.isfinite(float(last))):
        state.guardian_sighting_started_at = float(started) + max(0.0, now - float(last))
    state.guardian_sighting_last_anim = now


def _progress(state) -> float | None:
    started = getattr(state, "guardian_sighting_started_at", None)
    if type(started) not in (int, float):
        return None
    age = float(state.anim) - float(started)
    if not math.isfinite(age) or age < 0.0 or age >= SIGHTING_SECONDS:
        return None
    return age / SIGHTING_SECONDS


def _sighting_center(frame: np.ndarray, camera) -> tuple[float, float] | None:
    height, width = frame.shape[:2]
    if camera is None:
        return width * 0.5, height * 0.60
    pitch = getattr(camera, "pitch", None)
    tany = getattr(camera, "tany", None)
    if (type(pitch) not in (int, float) or type(tany) not in (int, float)
            or not math.isfinite(float(pitch)) or not math.isfinite(float(tany))
            or float(tany) <= 0.0):
        return None

    # The waterline is the camera horizon. Keep the ripple on the water side
    # of it as the player looks up or down, and defer it if water is off-screen.
    horizon_y = height * (0.5 + math.tan(float(pitch)) / (2.0 * float(tany)))
    center_y = horizon_y + height * WATERLINE_OFFSET
    if not math.isfinite(center_y) or not 0.0 <= center_y < height:
        return None
    return width * 0.5, center_y


def _blend(frame, x0: int, y0: int, mask: np.ndarray,
           color: tuple[int, int, int], alpha: float) -> None:
    if alpha <= 0.0 or not np.any(mask):
        return
    region = frame[y0:y0 + mask.shape[0], x0:x0 + mask.shape[1]]
    source = np.asarray(color, dtype=np.float32)
    region[mask] = np.clip(
        region[mask].astype(np.float32) * (1.0 - alpha) + source * alpha,
        0.0, 255.0,
    ).astype(np.uint8)


def _ellipse_region(frame, center_x: float, center_y: float,
                    radius_x: float, radius_y: float,
                    color: tuple[int, int, int], alpha: float) -> None:
    height, width = frame.shape[:2]
    pad = 3
    x0 = max(0, int(center_x - radius_x - pad))
    x1 = min(width, int(math.ceil(center_x + radius_x + pad + 1)))
    y0 = max(0, int(center_y - radius_y - pad))
    y1 = min(height, int(math.ceil(center_y + radius_y + pad + 1)))
    if x0 >= x1 or y0 >= y1:
        return
    yy, xx = np.mgrid[y0:y1, x0:x1]
    distance = np.sqrt(((xx - center_x) / radius_x) ** 2
                       + ((yy - center_y) / radius_y) ** 2)
    thickness = max(1.3, min(radius_x, radius_y) * 0.055)
    _blend(frame, x0, y0, np.abs(distance - 1.0) * min(radius_x, radius_y) <= thickness,
           color, alpha)


def _draw_guardian_shadow(frame, center_x: float, center_y: float,
                          width: int, height: int, progress: float) -> None:
    # Keep the form low contrast and broad: a passing shadow, not a creature reveal.
    half_length = width * 0.16
    half_height = max(2.0, height * 0.024)
    x0 = max(0, int(center_x - half_length - 2))
    x1 = min(width, int(center_x + half_length + 2))
    y0 = max(0, int(center_y - half_height - 2))
    y1 = min(height, int(center_y + half_height + 2))
    if x0 >= x1 or y0 >= y1:
        return

    yy, xx = np.mgrid[y0:y1, x0:x1]
    dx = xx - center_x
    dy = yy - center_y
    body = (dx / (width * 0.105)) ** 2 + (dy / half_height) ** 2 <= 1.0
    tail_t = (dx + width * 0.16) / (width * 0.075)
    tail = ((tail_t >= 0.0) & (tail_t <= 1.0)
            & (np.abs(dy) <= half_height * tail_t))
    head = ((dx - width * 0.09) / (width * 0.035)) ** 2 \
        + (dy / (height * 0.030)) ** 2 <= 1.0

    whisker_start = width * 0.115
    whisker_end = width * 0.19
    whisker_t = (dx - whisker_start) / max(1.0, whisker_end - whisker_start)
    whisker_width = max(1.0, height * 0.002)
    whiskers = ((whisker_t >= 0.0) & (whisker_t <= 1.0)
                & ((np.abs(dy - height * 0.014 * whisker_t) <= whisker_width)
                   | (np.abs(dy + height * 0.014 * whisker_t) <= whisker_width)))

    fade_in = min(1.0, progress / 0.06)
    fade_out = max(0.0, 1.0 - progress / 0.62)
    _blend(frame, x0, y0, body | tail | head | whiskers,
           (20, 39, 48), 0.24 * fade_in * fade_out)


def draw_sighting(frame: np.ndarray, state, camera=None) -> bool:
    """Draw a brief surface ripple and low-contrast under-hull silhouette."""
    center = _sighting_center(frame, camera)
    if center is None:
        pause_sighting_clock(state)
        return False
    if getattr(state, "guardian_sighting_pending", False):
        state.guardian_sighting_pending = False
        state.guardian_sighting_started_at = float(state.anim)
    state.guardian_sighting_last_anim = float(state.anim)
    progress = _progress(state)
    if progress is None:
        return False
    height, width = frame.shape[:2]
    center_x, center_y = center
    _draw_guardian_shadow(frame, center_x, center_y + height * 0.045,
                          width, height, progress)

    for index in range(3):
        delay = index * 0.10
        if progress < delay:
            continue
        phase = min(1.0, (progress - delay) / (1.0 - delay))
        radius_x = width * (0.055 + 0.235 * phase)
        radius_y = height * (0.018 + 0.052 * phase)
        alpha = 0.24 * (1.0 - progress) * (0.82 ** index)
        _ellipse_region(frame, center_x, center_y, radius_x, radius_y,
                        (158, 205, 197), alpha)
    return True
