"""Five water definitions and read-only story travel gates."""

from .data import CEDAR_ZONES, LAKES, LAKE_ZONE_NAMES


def travel_unlocked(state, lake_id):
    lake = LAKES.get(lake_id)
    if lake is None:
        return False
    required = lake["unlock_chapter"]
    if required == 0:
        # Cedar stays available to existing saves, including their v1 migration.
        return True
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
