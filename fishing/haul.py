"""Timing shared by the haul simulation and its progress display."""

from __future__ import annotations


def haul_cadence(state) -> float:
    """Return the time for one hook at the current speed and fatigue level."""
    v2 = state.v2 if isinstance(getattr(state, "v2", None), dict) else {}
    settings = v2.get("settings", {})
    if not isinstance(settings, dict):
        settings = {}
    cadence = {"normal": 0.25, "quick": 0.10}.get(
        settings.get("haul_speed"), 0.25,
    )

    needs = v2.get("needs", {})
    try:
        awake_hours = float(needs.get("awake_h", 0.0)) if isinstance(needs, dict) else 0.0
    except (TypeError, ValueError, OverflowError):
        awake_hours = 0.0
    mode = settings.get("mode", v2.get("mode", "cozy"))
    if mode == "old_salt" and awake_hours >= 16.0:
        cadence *= 1.25
    return cadence
