"""Boat shop rules: chapter unlocks, landing-exclusive boats and display order (02 §9, 03 §6)."""

from __future__ import annotations

from .boat import BOATS
from .lakes import LAKES

# The four boats from before V1.0 stay buyable from the start at their prices.
LEGACY_BOATS = ("jon", "sail", "pontoon", "rowboat")
# New boats of each tier go on sale once this chapter is finished (0: from the start).
UNLOCK_AFTER_CHAPTER = {1: 0, 2: 0, 3: 2, 4: 2, 5: 3, 6: 3, 7: 4, 8: 5}


def unlock_chapter(boat_id: str) -> int:
    return 0 if boat_id in LEGACY_BOATS else UNLOCK_AFTER_CHAPTER[BOATS[boat_id].tier]


def chapter_finished(state, number: int) -> bool:
    """Same reading as dish cards: past the chapter, or listed as completed."""
    if number <= 0:
        return True
    story = state.v2.get("story", {})
    chapter = story.get("chapter", 0) if isinstance(story, dict) else 0
    completed = story.get("completed_chapters", []) if isinstance(story, dict) else []
    return (type(chapter) is int and chapter > number) or (isinstance(completed, list) and number in completed)


def shop_error(state, lake_id: str, boat_id: str) -> str | None:
    """Why this boat can't be bought at this landing, or None. Owned boats always switch."""
    if boat_id in state.owned_boats:
        return None
    chapter = unlock_chapter(boat_id)
    if not chapter_finished(state, chapter):
        return f"Unlocks after chapter {chapter}."
    sold_at = BOATS[boat_id].sold_at
    if sold_at and lake_id not in sold_at:
        return "Sold only at " + " and ".join(LAKES[lake]["landing"] for lake in sold_at) + "."
    return None


def shop_boats():
    """The four older boats in their old order, then new boats by tier and price."""
    newer = sorted((model for model in BOATS.values() if model.id not in LEGACY_BOATS),
                   key=lambda model: (model.tier, model.price, model.id))
    return [BOATS[boat_id] for boat_id in LEGACY_BOATS] + newer
