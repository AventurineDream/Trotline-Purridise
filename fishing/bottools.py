"""Bot tool rules for the bite loop, the scanner readout and Nebula currents.

Thermocline depth and the species factors are pure functions of hour, weather,
depth and the owned tools, so the bite loop, the HUD and the tests read the same
numbers. Lakes without a thermocline get factor 1.0 everywhere, so Briar and
Cedar rates stay exactly as they were.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .lakes import LAKES

# Cold-layer depth d(h) = base + amp * sin(2π(h − 15) / 24) + weather, in metres.
COLD_LAYER = {"flathead": (12.0, 3.0), "crater": (18.0, 4.0)}
COLD_WEATHER_M = {"fog": 1.5, "snow_mist": 1.5, "clear": -1.0}
COLD_BAND_M = 6.0
COLD_OUTSIDE = 0.35
MIN_COLD_LAYER_M = 3.0
COLD_LAYER_CAP = 0.8  # fraction of the lake's deepest authored depth

CHIME_RADIUS_M = 30.0
CHIME_SLOW_MPS = 0.5
CHIME_LAST_MINUTES = 60.0
CHIME_COOLDOWN_MINUTES = 120.0
CHIME_SURFACE_MULT = 1.6
WINCH_CURRENT_MULT = 1.2
SILENT_SHY_MULT = 1.15  # a `silent` hull, for `shy` species (02 §9)

FLOW_M_PER_MINUTE = 0.5
DRIFT_CAP_M = 60.0
DRIFT_MIN_GAP_M = 16.0  # the same spacing try_set enforces between lines


@dataclass(frozen=True)
class ToolState:
    """What the owned tools and the boat's hull do to one line's bites during one span."""

    cold_layer_m: float | None = None  # None on lakes without a thermocline
    chime: bool = False
    winch: bool = False
    silent: bool = False


def cold_layer_m(lake_id: str, hour: float, weather: str) -> float | None:
    if lake_id not in COLD_LAYER:
        return None
    base, amp = COLD_LAYER[lake_id]
    depth = base + amp * math.sin(2 * math.pi * (hour - 15.0) / 24.0)
    depth += COLD_WEATHER_M.get(weather, 0.0)
    deepest = max(hi for _lo, hi in LAKES[lake_id]["placeholder_depths"].values())
    return min(max(depth, MIN_COLD_LAYER_M), COLD_LAYER_CAP * deepest)


def species_factor(tags, depth: float, tool: ToolState | None) -> float:
    if tool is None:
        return 1.0
    factor = 1.0
    if "cold" in tags and tool.cold_layer_m is not None:
        inside = tool.cold_layer_m <= depth <= tool.cold_layer_m + COLD_BAND_M
        factor *= 1.0 if inside else COLD_OUTSIDE
    if "surface" in tags and tool.chime:
        factor *= CHIME_SURFACE_MULT
    if "current" in tags and tool.winch:
        factor *= WINCH_CURRENT_MULT
    if "shy" in tags and tool.silent:
        factor *= SILENT_SHY_MULT
    return factor


def flow_at(x: float, z: float) -> tuple[float, float]:
    """Nebula current, metres per game minute. Smooth, deterministic, never zero."""
    heading = 1.7 * math.sin(x / 190.0 + 0.6) + 1.1 * math.cos(z / 150.0 - 0.4)
    return (math.cos(heading) * FLOW_M_PER_MINUTE, math.sin(heading) * FLOW_M_PER_MINUTE)


def scanner_text(owns_scanner: bool, lake_id: str, hour: float, weather: str) -> str | None:
    """The Thermocline Scanner readout for the HUD. None without the tool or a thermocline."""
    depth = cold_layer_m(lake_id, hour, weather) if owns_scanner else None
    return None if depth is None else f"Cold layer {depth:.0f} m"
