"""Five water definitions, read-only story travel gates and named places."""

import math

from .data import CEDAR_ZONES, LAKES, LAKE_ZONE_NAMES


def travel_unlocked(state, lake_id):
    lake = LAKES.get(lake_id)
    if lake is None:
        return False
    required = lake["unlock_chapter"]
    if required == 0:
        # Cedar stays available to existing saves, including their v1 migration.
        return True
    unlocks = state.v2.get("unlocks")
    if isinstance(unlocks, list) and f"travel:{lake_id}" in unlocks:
        return True  # a V1.0 reward can open a route (V1-31)
    story = state.v2.get("story", {})
    if not isinstance(story, dict):
        return False
    chapter = story.get("chapter", 0)
    completed = story.get("completed_chapters", [])
    return ((type(chapter) is int and chapter > required)
            or (isinstance(completed, list)
                and any(type(value) is int and value == required for value in completed)))


def travel_lock_reason(state, lake_id):
    if lake_id not in LAKES:
        return "That lake is not on the chart."
    if travel_unlocked(state, lake_id):
        return None
    return f"Finish chapter {LAKES[lake_id]['unlock_chapter']} to open this route."


def travel_caption(source, destination):
    if source == "nebula":
        return "You sail down the reflection and onto ordinary water."
    return LAKES[destination]["travel_caption"]


def place(ref: str) -> tuple[str, dict] | None:
    """A named area or waypoint from lakes.json, by its "<lake>:<id>" reference (06 §5)."""
    if not isinstance(ref, str):
        return None
    lake_id, _, place_id = ref.partition(":")
    lake = LAKES.get(lake_id)
    if lake is None:
        return None
    for kind, group in (("area", "areas"), ("waypoint", "waypoints")):
        for row in lake.get(group, ()):
            if row["id"] == place_id:
                return kind, row
    return None


def waypoints(lake_id: str) -> tuple[dict, ...]:
    return tuple((LAKES.get(lake_id) or {}).get("waypoints", ()))


def place_contains(row: dict, x: float, z: float) -> bool:
    """Circles (with an optional inner radius, a ring) and polygons, in world metres."""
    if "points" in row:
        inside = False
        points = row["points"]
        for (x0, z0), (x1, z1) in zip(points, points[1:] + points[:1]):
            if (z0 > z) != (z1 > z) and x < x0 + (z - z0) * (x1 - x0) / (z1 - z0):
                inside = not inside
        return inside
    distance = math.hypot(x - row["x"], z - row["z"])
    return row.get("inner_r", 0.0) <= distance <= row["r"]


def in_place(ref: str, lake_id: str, x, z) -> bool:
    """Whether a point on `lake_id` lies in the named place `ref`."""
    found = place(ref)
    if found is None or ref.partition(":")[0] != lake_id:
        return False
    try:
        x, z = float(x), float(z)
    except (TypeError, ValueError):
        return False
    return math.isfinite(x) and math.isfinite(z) and place_contains(found[1], x, z)
