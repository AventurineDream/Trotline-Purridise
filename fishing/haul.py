"""Timing shared by the haul simulation and its progress display."""

from __future__ import annotations

from .comfort import drowsy

def haul_cadence(state) -> float:
    """Return the time for one hook at the current speed and fatigue level."""
    v2 = state.v2 if isinstance(getattr(state, "v2", None), dict) else {}
    settings = v2.get("settings", {})
    if not isinstance(settings, dict):
        settings = {}
    cadence = {"normal": 0.25, "quick": 0.10}.get(
        settings.get("haul_speed"), 0.25,
    )

    if drowsy(v2):
        cadence *= 1.25
    return cadence
