"""Optional routine, naps and positive comfort; no offline needs clock."""

from copy import deepcopy
import math

from .book import remember_dream_clue
from .data import LAKE_RATE_MULTIPLIERS, SPECIES, ZONE_MATCH, zone_mult

MODES = ("cozy", "old_salt")
NAP_MINUTES = 120
RESTED_MINUTES = 360
PROMPT_INTERVAL = 600.0
SNOOZE_SECONDS = 1800.0
DEFAULT_NEEDS = {
    "awake_h": 0.0, "since_meal_h": 0.0, "rested_until": None,
    "last_prompt_real_s": 0.0, "active_real_s": 0.0, "prompt_shown": False,
    "prompted": {"energy": False, "hunger": False},
    "snooze_until": {"energy": 0.0, "hunger": 0.0},
}


def number(value, default=0.0):
    try:
        value = float(value)
        return max(0.0, value) if math.isfinite(value) else default
    except (ValueError, TypeError, OverflowError):
        return default


def mode(v2):
    settings = v2.get("settings", {})
    selected = settings.get("mode") if isinstance(settings, dict) else None
    if selected not in MODES:
        selected = v2.get("mode")
    return selected if selected in MODES else "cozy"


def normalize_needs(v2):
    """Repair known fields while preserving future fields in the save."""
    needs = v2.get("needs")
    if not isinstance(needs, dict):
        needs = v2["needs"] = {}
    for key, default in DEFAULT_NEEDS.items():
        needs.setdefault(key, deepcopy(default))
    for key in ("awake_h", "since_meal_h", "last_prompt_real_s", "active_real_s"):
        needs[key] = number(needs[key])
    if needs["rested_until"] is not None:
        needs["rested_until"] = number(needs["rested_until"], None)
    needs["prompt_shown"] = needs["prompt_shown"] is True
    for key in ("prompted", "snooze_until"):
        if not isinstance(needs[key], dict):
            needs[key] = deepcopy(DEFAULT_NEEDS[key])
        for kind in ("energy", "hunger"):
            needs[key][kind] = (needs[key].get(kind) is True if key == "prompted"
                                else number(needs[key].get(kind)))
    return needs


def change_mode(v2, selected):
    if selected not in MODES:
        return False
    previous = mode(v2)
    v2["mode"] = selected
    if not isinstance(v2.get("settings"), dict):
        v2["settings"] = {}
    v2["settings"]["mode"] = selected
    if selected != previous:
        needs = normalize_needs(v2)
        needs["awake_h"] = needs["since_meal_h"] = 0.0
        for kind in ("energy", "hunger"):
            needs["prompted"][kind] = False
            needs["snooze_until"][kind] = 0.0
    return True


def advance_needs(v2, game_hours):
    if mode(v2) == "old_salt":
        needs = normalize_needs(v2)
        needs["awake_h"] += number(game_hours)
        needs["since_meal_h"] += number(game_hours)


def _view(v2):
    needs = v2.get("needs", {})
    return needs if isinstance(needs, dict) else {}


def drowsy(v2):
    return mode(v2) == "old_salt" and number(_view(v2).get("awake_h")) >= 16.0


def doze_due(v2):
    return mode(v2) == "old_salt" and number(_view(v2).get("awake_h")) > 20.0


def speed_factor(v2):
    peckish = mode(v2) == "old_salt" and number(_view(v2).get("since_meal_h")) > 24.0
    return .8 if peckish else 1.0


def rested(v2, active_game_minutes):
    until = number(_view(v2).get("rested_until"))
    return until > active_game_minutes


def meal(v2):
    """Kitchen/snack hook; a meal clears hunger without changing any buff."""
    needs = normalize_needs(v2)
    needs["since_meal_h"] = 0.0
    needs["prompted"]["hunger"] = False
    needs["snooze_until"]["hunger"] = 0.0


def tow_fee(v2, cash, boat_price):
    if mode(v2) == "cozy":
        return 0.0
    available = math.floor(number(cash) * 100 + 1e-8) / 100
    return min(available, round(25 + .02 * number(boat_price), 2))


def active_time(v2, seconds):
    normalize_needs(v2)["active_real_s"] += number(seconds)


def next_prompt(v2):
    if mode(v2) != "old_salt":
        return None
    needs = normalize_needs(v2)
    now = needs["active_real_s"]
    if needs["prompt_shown"] and now - needs["last_prompt_real_s"] < PROMPT_INTERVAL:
        return None
    for kind, due in (("energy", drowsy(v2)), ("hunger", speed_factor(v2) < 1)):
        if due and not needs["prompted"][kind] and now >= needs["snooze_until"][kind]:
            needs["prompted"][kind] = True
            needs["prompt_shown"] = True
            needs["last_prompt_real_s"] = now
            return kind
    return None


def snooze(v2, kind):
    if mode(v2) == "old_salt" and kind in ("energy", "hunger"):
        needs = normalize_needs(v2)
        needs["prompted"][kind] = False
        needs["snooze_until"][kind] = needs["active_real_s"] + SNOOZE_SECONDS


def dream_clue(state, world):
    """One reproducible, previously unoffered habitat lead on this lake."""
    book = state.v2["book"]
    if book.get("dream_clue") is not None:
        return None
    pages = book.get("species", {})
    candidates = []
    for species in SPECIES:
        if LAKE_RATE_MULTIPLIERS.get(world.id, {}).get(species.id, 0) <= 0:
            continue
        page = pages.get(species.id, {})
        found = page.get("found", []) if isinstance(page, dict) else []
        record = state.journal.get(species.id, {})
        caught_here = any(isinstance(row, dict) and row.get("lake_id") == world.id for row in found)
        caught_here |= bool(record.get("count") and record.get("lake_id", world.id) == world.id)
        dreams = page.get("dreams", []) if isinstance(page, dict) else []
        offered = any(isinstance(row, dict) and row.get("lake_id") == world.id for row in dreams)
        if not caught_here and not offered:
            candidates.append(species)
    if not candidates:
        return None
    sid = state.rng.pick({species.id: 1.0 for species in candidates})
    species = next(species for species in candidates if species.id == sid)
    zone = max(ZONE_MATCH, key=lambda value: zone_mult(value, sid))
    clue = {"species": sid, "lake_id": world.id, "zone": zone,
            "teller": "Bot's dream",
            "text": f"I dreamed of {species.folk_name or species.name} near {world.zone_name(zone).lower()}."}
    return clue if remember_dream_clue(book, clue) else None


def finish_nap(state, world, eligible):
    needs = normalize_needs(state.v2)
    if mode(state.v2) == "old_salt":
        needs["awake_h"] = 0.0
        needs["prompted"]["energy"] = False
        needs["snooze_until"]["energy"] = 0.0
    if eligible:
        needs["rested_until"] = state.narrative.active_play_game_minutes + RESTED_MINUTES
        return dream_clue(state, world)
    return None
