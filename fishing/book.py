"""Book stages, attributed folklore, observations, and page state."""

from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
import math

from .content import (BOOK_CONTENT_PATH, LegendaryStory, Rumor,
                      load_book_content)
from .data import BAIT_MATCH, SPECIES_BY_ID, bait_mult, band_of


BOOK_DATA_PATH = BOOK_CONTENT_PATH
BOOK_STAGES = ((10, "mastered"), (5, "verified"), (3, "bait_known"),
               (1, "identified"), (0, "rumor"))
BOOK_STAGE_THRESHOLDS = tuple(sorted(threshold for threshold, _stage in BOOK_STAGES))
BOOK_TITLE_STATES = ("fishypedia", "book_of_five_waters", "pescapedia")
BOOK_STAGE_TOAST = "Shall we add that?"
BOOK_TOAST_SECONDS = 3.0
SHINY_CHANCE = 1 / 64
SHINY_PITY_CATCHES = 50
SHINY_VALUE_MULTIPLIER = 3


_CONTENT = load_book_content(species_ids=SPECIES_BY_ID)
SPECIES_RUMORS, LEGENDARY_STORIES = _CONTENT.rumors, _CONTENT.legendaries
BOOK_SPECIES_IDS = tuple(SPECIES_RUMORS)
LEGENDARY_IDS = tuple(LEGENDARY_STORIES)


def _catch_count(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def book_stage(count: int) -> str:
    """Return the highest entry stage earned by a catch count."""
    count = _catch_count(count)
    return next(stage for threshold, stage in BOOK_STAGES if count >= threshold)


stage_for_count = book_stage


def stage_transitions(previous_count: int, current_count: int) -> tuple[tuple[int, str], ...]:
    """List thresholds newly crossed while moving between two journal counts."""
    previous_count = _catch_count(previous_count)
    current_count = _catch_count(current_count)
    if current_count <= previous_count:
        return ()
    stage_by_threshold = {threshold: stage for threshold, stage in BOOK_STAGES}
    return tuple((threshold, stage_by_threshold[threshold])
                 for threshold in BOOK_STAGE_THRESHOLDS
                 if threshold > 0 and previous_count < threshold <= current_count)


def _book_record(book: dict, species_id: str) -> dict:
    pages = book.setdefault("species", {})
    if not isinstance(pages, dict):
        pages = book["species"] = {}
    entry = pages.get(species_id)
    if not isinstance(entry, dict):
        entry = {"found": [], "shiny": 0, "since_shiny": 0}
        pages[species_id] = entry
    entry.setdefault("found", [])
    entry.setdefault("shiny", 0)
    entry.setdefault("since_shiny", 0)
    if not isinstance(entry["found"], list):
        entry["found"] = []
    return entry


def tracker_unlocked(journal: dict, species_id: str) -> bool:
    """Only a Verified standard species can be a Shiny Tracker target."""
    if not isinstance(species_id, str) or species_id not in SPECIES_RUMORS:
        return False
    record = journal.get(species_id)
    return isinstance(record, dict) and _catch_count(record.get("count", 0)) >= 5


def set_shiny_target(book: dict, journal: dict, species_id: str | None) -> bool:
    """Change the one saved target, leaving every species' counter intact."""
    if species_id is not None and not tracker_unlocked(journal, species_id):
        return False
    book["tracked"] = species_id
    return True


def shiny_tracker(book: dict, journal: dict, species_id: str) -> dict:
    """Read tracker progress without creating or changing a book page."""
    pages = book.get("species", {})
    entry = (pages.get(species_id, {})
             if isinstance(pages, dict) and species_id in SPECIES_RUMORS else {})
    if not isinstance(entry, dict):
        entry = {}
    since = _catch_count(entry.get("since_shiny", 0))
    unlocked = tracker_unlocked(journal, species_id)
    return {"unlocked": unlocked,
            "tracked": unlocked and book.get("tracked") == species_id,
            "since_shiny": since,
            "remaining": max(1, SHINY_PITY_CATCHES - since),
            "shiny": _catch_count(entry.get("shiny", 0))}


def roll_shiny(book: dict, journal: dict, species_id: str, rng, *,
               legendary: bool = False) -> bool:
    """Roll once at catch creation, using the saved gameplay RNG.

    All standard catches advance their species' counter; any shiny resets it.
    The guarantee applies only to the current Verified target. Even a forced
    shiny consumes its normal random roll so the RNG sequence is predictable.
    Simulation catches save the reset as a reservation, refunded on escape.
    """
    if legendary or species_id not in SPECIES_RUMORS:
        return False
    entry = _book_record(book, species_id)
    since = _catch_count(entry.get("since_shiny", 0)) + 1
    shiny = rng.chance(SHINY_CHANCE)
    if (book.get("tracked") == species_id and tracker_unlocked(journal, species_id)
            and since >= SHINY_PITY_CATCHES):
        shiny = True
    entry["since_shiny"] = 0 if shiny else since
    return shiny


def confirm_shiny(book: dict, catch: object) -> None:
    """Credit a pending shiny once it is kept or deliberately released."""
    if not getattr(catch, "shiny", False) or getattr(catch, "shiny_since_before", None) is None:
        return
    entry = _book_record(book, catch.species)
    index = catch.shiny_observation
    if type(index) is int and 0 <= index < len(entry["found"]):
        observation = entry["found"][index]
        if isinstance(observation, dict):
            observation["shiny"] = True
    entry["shiny"] = _catch_count(entry.get("shiny", 0)) + 1
    catch.shiny_since_before = None
    catch.shiny_observation = None


def lose_shiny(book: dict, catch: object, pending: Iterable[object]) -> None:
    """Refund an escaped shiny's reservation without undoing newer progress.

    Transfer its saved counter to the next pending shiny, or add it to today's
    counter if this was the last reservation. A newer confirmed shiny already
    consumed that history. Observation indices keep this independent of hook
    traversal, landing order, target changes, and save/reload.
    """
    before = getattr(catch, "shiny_since_before", None)
    index = getattr(catch, "shiny_observation", None)
    if (not getattr(catch, "shiny", False) or type(before) is not int or before < 0
            or type(index) is not int or index < 0):
        return
    entry = _book_record(book, catch.species)
    found = entry["found"]
    newer_confirmed = any(isinstance(found[i], dict) and found[i].get("shiny")
                          for i in range(len(found) - 1, index, -1))
    if not newer_confirmed:
        later = [other for other in pending
                 if other.species == catch.species and other.shiny
                 and other.shiny_since_before is not None
                 and other.shiny_observation is not None
                 and other.shiny_observation > index]
        if later:
            following = min(later, key=lambda other: other.shiny_observation)
            following.shiny_since_before += before
        else:
            entry["since_shiny"] = _catch_count(entry.get("since_shiny", 0)) + before
    catch.shiny_since_before = None
    catch.shiny_observation = None


def remember_rumor(book: dict, species_id: str) -> dict | None:
    """Write a species rumor to the page once, preserving its original wording."""
    rumor = SPECIES_RUMORS.get(species_id)
    if rumor is None or not isinstance(book, dict):
        return None
    entry = _book_record(book, species_id)
    heard = entry.get("heard")
    if (isinstance(heard, dict) and isinstance(heard.get("text"), str)
            and isinstance(heard.get("teller"), str)):
        return deepcopy(heard)
    entry["heard"] = {"text": rumor.text, "teller": rumor.teller}
    return deepcopy(entry["heard"])


def record_observation(book: dict, catch: object) -> dict | None:
    """Append the conditions of one catch to its What we found history."""
    species_id = getattr(catch, "species", None)
    if (not isinstance(book, dict) or not isinstance(species_id, str)
            or species_id not in SPECIES_RUMORS):
        return None
    entry = _book_record(book, species_id)
    remember_rumor(book, species_id)
    observation = {
        "zone": getattr(catch, "zone", ""),
        "bait": getattr(catch, "bait", ""),
        "band": band_of(getattr(catch, "hour", 0.0)),
        "lake_id": getattr(catch, "lake_id", "briar"),
    }
    depth = getattr(catch, "depth_m", None)
    if type(depth) in (int, float) and math.isfinite(depth) and depth >= 0:
        observation["depth_m"] = round(float(depth), 3)
    weight = getattr(catch, "weight", None)
    try:
        if type(weight) in (int, float) and math.isfinite(weight):
            observation["weight"] = round(float(weight), 3)
    except OverflowError:
        pass
    catch_minute = getattr(catch, "catch_game_minute", None)
    try:
        if type(catch_minute) in (int, float) and math.isfinite(catch_minute):
            observation["game_minute"] = round(float(catch_minute), 3)
    except OverflowError:
        pass
    if getattr(catch, "shiny", False) and not getattr(catch, "legendary", False):
        if getattr(catch, "shiny_since_before", None) is not None:
            catch.shiny_observation = len(entry["found"])
        else:
            observation["shiny"] = True
            entry["shiny"] = _catch_count(entry.get("shiny", 0)) + 1
    entry["found"].append(observation)
    return deepcopy(observation)


def claim_stage_up(v2: dict, species_id: str, stage: str) -> bool:
    """Claim one stage-up key in the v2 reward ledger, once per species."""
    if (not isinstance(v2, dict) or species_id not in SPECIES_RUMORS
            or stage not in {name for threshold, name in BOOK_STAGES if threshold > 0}):
        return False
    rewards = v2.setdefault("reward_claims", {})
    if not isinstance(rewards, dict):
        rewards = v2["reward_claims"] = {}
    claims = rewards.setdefault("book_stage_up", [])
    if not isinstance(claims, list):
        claims = rewards["book_stage_up"] = []
    key = f"{species_id}:{stage}"
    if key in claims:
        return False
    claims.append(key)
    return True


def stage_up_events(v2: dict, species_id: str, previous_count: int,
                    current_count: int) -> tuple[dict, ...]:
    """Return and claim all newly crossed stage events for one catch."""
    events = []
    for threshold, stage in stage_transitions(previous_count, current_count):
        if not claim_stage_up(v2, species_id, stage):
            continue
        events.append({
            "type": "book.stage_up",
            "species": species_id,
            "stage": stage,
            "threshold": threshold,
            "toast": BOOK_STAGE_TOAST,
            "toast_seconds": BOOK_TOAST_SECONDS,
        })
    return tuple(events)


def seed_stage_claims(v2: dict, journal: dict) -> None:
    """Consume historical stages on migration without replaying their rewards."""
    for species_id, record in journal.items():
        if isinstance(record, dict):
            for _threshold, stage in stage_transitions(0, record.get("count", 0)):
                claim_stage_up(v2, species_id, stage)


def all_species_verified(journal: dict) -> bool:
    """Whether every authored species page has reached the Verified stage."""
    return (isinstance(journal, dict) and bool(BOOK_SPECIES_IDS)
            and all(isinstance(journal.get(species_id), dict)
                    and _catch_count(journal[species_id].get("count", 0)) >= 5
                    for species_id in BOOK_SPECIES_IDS))


def promote_title(book: dict, title: str, journal: dict | None = None) -> bool:
    """Move the book title forward; Pescapedia requires all 144 pages verified."""
    if not isinstance(book, dict) or title not in BOOK_TITLE_STATES:
        return False
    current = book.get("title", "fishypedia")
    if current not in BOOK_TITLE_STATES:
        current = "fishypedia"
    if BOOK_TITLE_STATES.index(title) != BOOK_TITLE_STATES.index(current) + 1:
        return False
    if title == "pescapedia" and (journal is None or not all_species_verified(journal)):
        return False
    book["title"] = title
    return True


def refresh_collection_title(book: dict, journal: dict) -> bool:
    """Finish the Pescapedia title transition after the final required verification."""
    if book.get("title") not in ("book_of_five_waters", "pescapedia"):
        return False
    return promote_title(book, "pescapedia", journal)


def set_dream_clue(book: dict, clue: object) -> bool:
    """Set the single unread dream-clue slot without replacing an unread clue."""
    if not isinstance(book, dict) or clue is None or book.get("dream_clue") is not None:
        return False
    book["dream_clue"] = deepcopy(clue)
    return True


def take_dream_clue(book: dict) -> object | None:
    """Read and clear the pending dream clue."""
    if not isinstance(book, dict):
        return None
    clue = book.get("dream_clue")
    if clue is None:
        return None
    book["dream_clue"] = None
    return deepcopy(clue)


def remember_dream_clue(book: dict, clue: dict) -> bool:
    """Keep a dream in its species' heard notes and reserve the unread slot."""
    sid = clue.get("species")
    if sid not in SPECIES_RUMORS or not set_dream_clue(book, clue):
        return False
    entry = _book_record(book, sid)
    dreams = entry.setdefault("dreams", [])
    if not isinstance(dreams, list):
        dreams = entry["dreams"] = []
    dreams.append(deepcopy(clue))
    return True


def _legendary_record(v2: dict, legendary_id: str) -> dict:
    pages = v2.setdefault("legendaries", {})
    if not isinstance(pages, dict):
        pages = v2["legendaries"] = {}
    page = pages.setdefault(legendary_id, {})
    if not isinstance(page, dict):
        page = pages[legendary_id] = {}
    heard = page.get("heard")
    if (not isinstance(heard, dict) or not isinstance(heard.get("story"), str)
            or not isinstance(heard.get("teller"), str)):
        story = LEGENDARY_STORIES[legendary_id]
        page["heard"] = {"story": story.story, "teller": story.teller}
    return page


def record_legendary(v2: dict, legendary_id: str, record: dict) -> bool:
    """Append a first-hand record to an authored legendary book page."""
    if (not isinstance(v2, dict) or legendary_id not in LEGENDARY_STORIES
            or not isinstance(record, dict)):
        return False
    page = _legendary_record(v2, legendary_id)
    records = page.setdefault("records", [])
    if not isinstance(records, list):
        records = page["records"] = []
    records.append(deepcopy(record))
    return True


def record_legendary_catch(v2: dict, catch: object) -> bool:
    """Store an authored legendary catch in its page, including non-species IDs."""
    if not getattr(catch, "legendary", False):
        return False
    species_id = getattr(catch, "species", None)
    hour = getattr(catch, "hour", 0.0)
    weight = getattr(catch, "weight", 0.0)
    try:
        weight = round(float(weight), 3) if math.isfinite(weight) else 0.0
        hour = round(float(hour), 3) if math.isfinite(hour) else 0.0
    except (TypeError, ValueError, OverflowError):
        weight, hour = 0.0, 0.0
    return record_legendary(v2, species_id, {
        "weight": weight,
        "zone": getattr(catch, "zone", ""),
        "bait": getattr(catch, "bait", ""),
        "band": band_of(hour),
        "lake_id": getattr(catch, "lake_id", "briar"),
        "hour": hour,
        "game_minute": getattr(catch, "catch_game_minute", None),
    })


def legendary_page(legendary_id: str, v2: dict, *, remember: bool = True) -> dict | None:
    """Return the authored story and saved sightings for one legendary page."""
    if legendary_id not in LEGENDARY_STORIES or not isinstance(v2, dict):
        return None
    # Presentation can preview an unopened page without writing to the save.
    source = v2 if remember else {"legendaries": {
        legendary_id: deepcopy(v2.get("legendaries", {}).get(legendary_id, {}))}}
    saved = _legendary_record(source, legendary_id)
    heard = saved["heard"]
    return {
        "id": legendary_id,
        "story": heard["story"],
        "teller": heard["teller"],
        "verified": isinstance(saved.get("records"), list) and bool(saved["records"]),
        "records": deepcopy(saved.get("records", []))
        if isinstance(saved.get("records", []), list) else [],
        "clues": deepcopy(saved.get("clues", []))
        if isinstance(saved.get("clues", []), list) else [],
    }


def species_page(book: dict, species_id: str, count: int,
                 journal_record: dict | None = None, *, remember: bool = True) -> dict | None:
    """Build the current data for a species page without introducing UI state."""
    if species_id not in SPECIES_RUMORS:
        return None
    count = _catch_count(count)
    source = book if remember else {"species": {
        species_id: deepcopy(book.get("species", {}).get(species_id, {}))}}
    heard = remember_rumor(source, species_id)
    entry = _book_record(source, species_id)
    species = SPECIES_BY_ID.get(species_id)
    found = deepcopy(entry["found"])
    best_bait = (max(BAIT_MATCH, key=lambda bait: bait_mult(bait, species_id))
                 if count >= 3 and species is not None else None)
    return {
        "id": species_id,
        "name": species.name if species and count >= 1 else None,
        "folk_name": SPECIES_RUMORS[species_id].folk_name,
        "count": count,
        "stage": book_stage(count),
        "heard": heard,
        "dreams": deepcopy(entry.get("dreams", [])) if isinstance(entry.get("dreams", []), list) else [],
        "found": found,
        "best_bait": best_bait,
        "tracker_unlocked": count >= 5,
        "mastered": count >= 10,
        "best_weight": (journal_record or {}).get("best", 0.0),
    }
