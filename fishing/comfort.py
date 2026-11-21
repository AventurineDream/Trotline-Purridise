"""Optional routine, naps and positive comfort; no offline needs clock."""

from copy import deepcopy
import math

from .book import remember_dream_clue
from .data import (DISHES, LAKE_RATE_MULTIPLIERS, PANTRY, PANTRY_CAPACITY,
                   SPECIES, ZONE_MATCH, zone_mult)

MODES = ("cozy", "old_salt")
NAP_MINUTES = 120
RESTED_MINUTES = 360
PROMPT_INTERVAL = 600.0
SNOOZE_SECONDS = 1800.0
MAX_MEAL_HOURS = max([24.0, *(dish.value for dish in DISHES.values()
                            if dish.effect == "glow_buoys")])
DEFAULT_NEEDS = {
    "awake_h": 0.0, "since_meal_h": 0.0, "rested_until": None,
    "meal_hours": 24.0,
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


def _meal_hours(value):
    return min(MAX_MEAL_HOURS, max(24.0, number(value, 24.0)))


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
    needs["meal_hours"] = _meal_hours(needs.get("meal_hours"))
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
    limit = _meal_hours(_view(v2).get("meal_hours"))
    peckish = mode(v2) == "old_salt" and number(_view(v2).get("since_meal_h")) > limit
    return .8 if peckish else 1.0


def rested(v2, active_game_minutes):
    until = number(_view(v2).get("rested_until"))
    return until > active_game_minutes


def meal(v2, *, hours=24):
    """Reset hunger without shortening existing satiation or changing a buff."""
    needs = normalize_needs(v2)
    remaining = max(0.0, needs["meal_hours"] - needs["since_meal_h"])
    needs["since_meal_h"] = 0.0
    needs["meal_hours"] = max(_meal_hours(hours), remaining)
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


def dream_clue(state, world, *, extra=False):
    """One reproducible, previously unoffered habitat lead on this lake."""
    book = state.v2["book"]
    unread = book.get("dream_clue")
    if unread is not None and not extra:
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
    if unread is not None:
        book["dream_clue"] = None
    if not remember_dream_clue(book, clue):
        book["dream_clue"] = unread
        return None
    if unread is not None:
        queue = book.setdefault("dream_queue", [])
        if not isinstance(queue, list):
            queue = book["dream_queue"] = []
        queue.append(clue)
        book["dream_clue"] = unread
    return clue


def finish_nap(state, world, eligible):
    needs = normalize_needs(state.v2)
    if mode(state.v2) == "old_salt":
        needs["awake_h"] = 0.0
        needs["prompted"]["energy"] = False
        needs["snooze_until"]["energy"] = 0.0
    bonus = has_buff(state, "extra_dream")
    if bonus:
        consume_buff(state)
    if eligible:
        needs["rested_until"] = state.narrative.active_play_game_minutes + RESTED_MINUTES
    if eligible or bonus:
        return dream_clue(state, world, extra=bonus)
    return None


def normalize_food(v2):
    pantry = v2.get("pantry")
    if not isinstance(pantry, dict):
        pantry = v2["pantry"] = {}
    for item_id in PANTRY:
        value = pantry.get(item_id, 0)
        pantry[item_id] = min(PANTRY_CAPACITY, max(0, value)) if type(value) is int else 0


def active_buff(state):
    """Read-only effect query; unknown future buffs remain intact in saves."""
    buff = state.v2.get("buff")
    if not isinstance(buff, dict):
        return None
    dish_id = buff.get("dish")
    dish = DISHES.get(dish_id) if isinstance(dish_id, str) else None
    if dish is None:
        return None
    if dish.minutes:
        if number(buff.get("until_active_minutes")) <= state.narrative.active_play_game_minutes:
            return None
    elif number(buff.get("charges")) <= 0:
        return None
    if dish.effect == "weather_invitation" and buff.get("day") != int(state.game_minutes // 1440):
        return None
    return dish


def has_buff(state, effect):
    dish = active_buff(state)
    return dish is not None and dish.effect == effect


def serve_dish(state, dish):
    meal(state.v2, hours=dish.value if dish.effect == "glow_buoys" else 24)
    state.v2["buff"] = {"dish": dish.id, "charges": dish.charges,
                        "until_active_minutes": state.narrative.active_play_game_minutes + dish.minutes,
                        "day": int(state.game_minutes // 1440)}
    state.toast(dish.name + ". " + dish.blurb)


def consume_buff(state):
    buff = state.v2.get("buff")
    if isinstance(buff, dict):
        buff["charges"] = max(0, int(number(buff.get("charges"))) - 1)
        if not buff["charges"]:
            state.v2["buff"] = None


def fuel_factor(state):
    """Return the active-mode and dish multiplier for litres burned per game hour.

    Cozy and Old Salt provide 2× and 1.5× fuel economy; dish effects multiply
    that economy's corresponding burn factor. This query does not mutate state.
    """
    factor = 0.5 if mode(state.v2) == "cozy" else (2.0 / 3.0)
    dish = active_buff(state)
    return factor * dish.value if dish and dish.effect == "fuel_saver" else factor


def scout_range_factor(state, weather):
    dish = active_buff(state)
    return dish.value if dish and dish.effect == "steady_scout" and weather != "snow_mist" else 1.0


def gust_factor(state, weather, *, using_sail=False):
    """Scale snow-mist drift without reducing wind-driven sailing.

    Args:
        state: Current save state, used to read mode and picnic effects.
        weather: Current weather identifier.
        using_sail: Whether the sail is raised.

    Returns:
        A multiplier for the boat's snow-mist gust displacement.
    """
    if weather == "snow_mist" and has_buff(state, "steady_scout"):
        return 0.0
    if mode(state.v2) == "cozy" and not using_sail:
        return 0.5
    return 1.0

def fog_radius(state):
    dish = active_buff(state)
    return dish.value if dish and dish.effect == "clear_fog" else 0.0


def fog_factor(state, distance):
    import numpy as np
    radius = fog_radius(state)
    return np.where(np.asarray(distance) <= radius, .25, 1.) if radius else 1.


def haul_factor(state):
    dish = active_buff(state)
    return dish.value if dish and dish.effect == "quick_haul" else 1.0


def begin_haul(state, line):
    """Snapshot one nonempty check's perk before spending a saved charge."""
    dish = active_buff(state)
    if dish is None or not line.hooks or dish.effect not in {"quick_haul", "keep_bait", "shiny_credit"}:
        return 1.0
    if dish.effect == "keep_bait":
        for hook in line.hooks:
            if hook.catch is None:
                hook.baited = True
    if dish.effect == "shiny_credit":
        from .book import tracker_unlocked
        book = state.v2["book"]
        tracked = book.get("tracked")
        if tracker_unlocked(state.journal, tracked):
            for hook in line.hooks:
                catch = hook.catch
                if (catch is not None and catch.species == tracked and not catch.shiny
                        and not catch.legendary and not catch.extra_fields.get("picnic_pity_credited")):
                    page = book.setdefault("species", {}).setdefault(tracked, {})
                    page["since_shiny"] = int(number(page.get("since_shiny"))) + int(dish.value) - 1
                    catch.extra_fields["picnic_pity_credited"] = True
    consume_buff(state)
    return dish.value if dish.effect == "quick_haul" else 1.0


def weather_spot(state):
    """Find nearby water favored by the current weather and time, or stay silent."""
    from .data import band_of, hour_of_day, weather_mult, time_mult
    from . import calendar
    from .sim import species_rates
    world = state._world
    if world is None:
        return None
    hour, weather = hour_of_day(state.game_minutes), calendar.weather_at(state)
    candidates = []
    for zone, x, z, _radius in world.zones:
        if math.hypot(x - state.x, z - state.z) > 300 or zone in ('shore', 'landing'):
            continue
        depth = float(world.depth(x, z))
        if depth <= 0:
            continue
        rates = species_rates(zone, state.preferred_bait, hour, weather, depth, world.id, game_minutes=state.game_minutes)
        favorable = [sp for sp in SPECIES if (weather_mult(sp.id, weather) > 1
                         or calendar.rate_multiplier(world.id, state.game_minutes, sp.id, zone) > 1)
                     and time_mult(sp.pref_time, hour) == 1 and rates.get(sp.id, 0) > .004]
        if favorable:
            candidates.append((sum(rates[sp.id] for sp in favorable), zone, x, z))
    if not candidates:
        return None
    _rate, zone, x, z = max(candidates)
    return {'lake_id': world.id, 'zone': zone, 'x': float(x), 'z': float(z),
            'band': band_of(hour), 'until_game_minutes': state.game_minutes + 120}


def weather_invitation(state):
    """Offer a favorable-water mark once a day, plus the tacos' one extra."""
    calendar = state.v2["calendar"]
    day = int(state.game_minutes // 1440)
    used = int(number(calendar.get("invitations_used"))) if calendar.get("invitation_day") == day else 0
    bonus = has_buff(state, "weather_invitation")
    if used >= 1 + int(bonus):
        return "Today's weather invitations have been used."
    spot = weather_spot(state)
    if spot is None:
        return None
    note = f"Bot: The {state._world.zone_name(spot['zone']).lower()} is having a good {spot['band']}. I've marked it on your chart."
    calendar['invitation_mark'] = spot
    calendar['invitation_day'], calendar['invitations_used'] = day, used + 1
    if used and bonus:
        consume_buff(state)
    state.narrative.record_bot_note(note)
    state.toast(note)
    return None
