"""Dawn-based weeks, Lake Days and reproducible weather opportunities.

Plans use a private fork of the saved schedule seed, never the fishing RNG.
Every day reserves the full rare-weather opportunities before filling in the
remaining forecast. Eligibility can therefore change without rewriting a plan.
This module plans opportunities; legendary equipment/story gates remain with
the legendary encounter system.
"""
from __future__ import annotations

from functools import lru_cache
import hashlib
import math

from .data import (CALENDAR_DATA, LAKE_DAYS, LEGENDARY_WINDOWS, PANTRY,
                   PANTRY_CAPACITY, SPECIES_BY_ID, WEATHER_RESERVATIONS,
                   band_of, clock_string, hour_of_day)

WEEKDAYS = ('Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday')
LAKE_IDS = ('briar', 'cedar', 'flathead', 'crater', 'nebula')
PLAN_VERSION = 1
DAY_MINUTES = 1440
WEEK_MINUTES = 7 * DAY_MINUTES


def day_number(minutes):
    """Game days begin at 06:00, matching the existing NPC schedule."""
    return max(0, math.floor(minutes / DAY_MINUTES))


def weekday(minutes):
    return day_number(minutes) % 7


def day_name(minutes):
    return WEEKDAYS[weekday(minutes)]


def in_hours(hour, start, end):
    return start <= hour < end if start < end else hour >= start or hour < end


def lake_day(lake_id, minutes):
    return next((row for row in LAKE_DAYS if row.lake == lake_id and row.weekday == weekday(minutes)), None)


def rate_multiplier(lake_id, minutes, species_id, zone):
    special = lake_day(lake_id, minutes)
    species = SPECIES_BY_ID.get(species_id)
    if special is None or (special.band != 'any' and special.band != band_of(hour_of_day(minutes))):
        return 1.0
    if special.zones and zone not in special.zones:
        return 1.0
    if special.species or special.foods:
        if species_id not in special.species and (species is None or species.food not in special.foods):
            return 1.0
    return special.multiplier


def apply_rates(state, rates, zone):
    return {sid: rate * rate_multiplier(state.lake_id, state.game_minutes, sid, zone)
            for sid, rate in rates.items()}


def _fork(seed, purpose):
    from .sim import RNG
    digest = hashlib.sha256(f'calendar:{PLAN_VERSION}:{seed}:{purpose}'.encode()).digest()
    return RNG(int.from_bytes(digest[:8], 'big'))


@lru_cache(maxsize=32)
def weekly_plan(seed, lake_id, week):
    """168 immutable hourly conditions, including both dawn and midnight seams."""
    if lake_id not in LAKE_IDS:
        raise ValueError('Unknown forecast lake: ' + str(lake_id))
    rng = _fork(seed, f'{lake_id}:{week}')
    hours = []
    for day in range(7):
        minute = (week * 7 + day) * DAY_MINUTES
        special = lake_day(lake_id, max(0, minute))
        reserved = [(row, row.weathers[min(len(row.weathers)-1, int(rng.u01()*len(row.weathers)))])
                    for row in WEATHER_RESERVATIONS if row.lake == lake_id]
        for slot in range(24):
            if slot % 2 == 0:
                condition = rng.pick({'clear': 3, 'fair': 4, 'overcast': 2, 'drizzle': 1})
            hour = (slot + 6) % 24
            biased = special and special.weather_bias and (special.band == 'any' or special.band == band_of(hour))
            value = special.weather_bias if biased else condition
            if value == 'fog_clear':
                # Fog Lift's two dawn hours: the mist clears after 06:00.
                value = 'fog' if hour == 6 else 'clear'
            for reservation, weather in reserved:
                if in_hours(hour, reservation.start_hour, reservation.end_hour):
                    value = weather
            hours.append(value)
    return tuple(hours)


def planned_weather(seed, lake_id, minutes):
    hour = math.floor(minutes / 60)
    week, slot = divmod(hour, 168)
    return weekly_plan(seed, lake_id, week)[slot]


def weather_spans(state, start, end):
    """The planned weather between two game minutes, as [weather, minutes] spans in order."""
    spans = []
    minute = start
    while minute < end:
        boundary = min(end, (math.floor(minute / 60) + 1) * 60)
        weather = weather_at(state, minute)
        if spans and spans[-1][0] == weather:
            spans[-1][1] += boundary - minute
        else:
            spans.append([weather, boundary - minute])
        minute = boundary
    return spans


def forecast_seed(state):
    value = state.v2.get("calendar", {}).get("seed")
    return value if type(value) is int else state.rng.s


def weather_at(state, minutes=None):
    """Read-only: safe in paused UI, rendering and future forecast previews."""
    return planned_weather(forecast_seed(state), state.lake_id,
                           state.game_minutes if minutes is None else minutes)


def ensure_plans(state):
    """Persist two weeks per lake; preserve unknown future calendar fields."""
    calendar = state.v2.setdefault('calendar', {})
    if not isinstance(calendar, dict):
        calendar = state.v2['calendar'] = {}
    calendar['seed'] = forecast_seed(state)
    windows = calendar.get('weather_windows')
    if not isinstance(windows, dict):
        windows = calendar['weather_windows'] = {}
    week = int(state.game_minutes // WEEK_MINUTES)
    wanted = {f'{lake}:{w}' for lake in LAKE_IDS for w in (week, week + 1)}
    for key in list(windows):
        if isinstance(key, str) and key.split(':', 1)[0] in LAKE_IDS and key not in wanted:
            del windows[key]
    for lake in LAKE_IDS:
        for w in (week, week + 1):
            key = f'{lake}:{w}'
            row = windows.get(key)
            row = dict(row) if isinstance(row, dict) else {}
            row.update(version=PLAN_VERSION, seed=forecast_seed(state), week=w,
                       hours=list(weekly_plan(forecast_seed(state), lake, w)))
            windows[key] = row


def window_favorable(seed, window, minutes):
    hour = hour_of_day(minutes)
    if not in_hours(hour, window.start_hour, window.end_hour):
        return False
    weather = planned_weather(seed, window.lake, minutes)
    if window.weathers and weather not in window.weathers:
        return False
    if window.recent_rain:
        # Include exactly the preceding six hours, never a future rain slot.
        first = math.floor((minutes - 360) / 60)
        last = math.floor(minutes / 60)
        return any(planned_weather(seed, window.lake, h * 60) == 'drizzle'
                   for h in range(first, last + 1))
    return True


def next_legendary_window(seed, legendary_id, eligible_minute):
    """Return a real >=120-minute opportunity starting within three game days.

    Start at the eligibility instant, including fractional hours; do not count
    the already elapsed portion of an active opportunity toward its duration.
    """
    window = LEGENDARY_WINDOWS[legendary_id]
    minute = float(eligible_minute)
    deadline = minute + 3 * DAY_MINUTES
    start = None
    while minute <= deadline + window.minimum_minutes:
        boundary = (math.floor(minute / 60) + 1) * 60
        favorable = window_favorable(seed, window, minute)
        if favorable:
            if start is None:
                start = minute
            if boundary - start >= window.minimum_minutes and start <= deadline:
                return start, start + window.minimum_minutes
        else:
            start = None
        minute = boundary
    raise ValueError(f'No three-day weather opportunity for {legendary_id}')


def cookout_active(minutes):
    event = CALENDAR_DATA['cookout']
    return weekday(minutes) == event['weekday'] and in_hours(hour_of_day(minutes), event['start_hour'], event['end_hour'])


def cookout_friends(content, lake_id):
    return tuple(row for row in content.npcs.values() if row['anchor_id'].startswith(lake_id + ':'))


def cookout_gift(state):
    """The same preview on every visit/reload; independent of fishing draws."""
    pool = tuple(item.id for item in PANTRY.values() if item.lake in ('all', state.lake_id))
    rng = _fork(forecast_seed(state), f'cookout:{state.lake_id}:{day_number(state.game_minutes)}')
    return pool[min(len(pool)-1, int(rng.u01()*len(pool)))]


def cookout_error(state, world, fish_index=None):
    from .kitchen import at_landing, eligible_fish
    if state.lake_id != world.id or not cookout_active(state.game_minutes) or not at_landing(state, world):
        return 'Join the landing cookout on Sunday, 17:00–20:00.'
    claims = state.v2['calendar'].get('cookout_gifts', {})
    if isinstance(claims, dict) and claims.get(world.id) == day_number(state.game_minutes):
        return 'Your fish is already on the table. Stay for the company.'
    fish = eligible_fish(state, 'any', food_only=False)
    if not fish or (fish_index is not None and fish_index not in fish):
        return 'Bring one ordinary fish. Special fish stay safe.'
    if state.v2['pantry'].get(cookout_gift(state), 0) >= PANTRY_CAPACITY:
        return 'Make room for the pantry gift before sharing your fish.'
    return None


def share_fish(state, world, fish_index=None):
    from .kitchen import eligible_fish
    error = cookout_error(state, world, fish_index)
    if error:
        return error
    chosen = eligible_fish(state, 'any', food_only=False)[0] if fish_index is None else fish_index
    gift = cookout_gift(state)
    state.well.pop(chosen)
    state.v2['pantry'][gift] = state.v2['pantry'].get(gift, 0) + CALENDAR_DATA['cookout']['gift_count']
    ledger = state.v2['calendar'].get('cookout_gifts')
    if not isinstance(ledger, dict):
        ledger = state.v2['calendar']['cookout_gifts'] = {}
    ledger[world.id] = day_number(state.game_minutes)
    state.toast('A fish for the table. A gift of ' + PANTRY[gift].name + ' for your pantry.')
    return None


def chat(state, world, npc_id, content):
    from .kitchen import at_landing
    if not cookout_active(state.game_minutes) or not at_landing(state, world):
        return False
    if npc_id not in {row['id'] for row in cookout_friends(content, world.id)}:
        return False
    ledger = state.v2['calendar'].get('cookout_chats')
    if not isinstance(ledger, dict):
        ledger = state.v2['calendar']['cookout_chats'] = {}
    if ledger.get(npc_id) == day_number(state.game_minutes):
        return False
    ledger[npc_id] = day_number(state.game_minutes)
    row = content.npcs[npc_id]
    state.toast(row['name'] + ': ' + CALENDAR_DATA['cookout_lines'][npc_id], 8)
    return True


def active_tick(state, before):
    """Only actual online world time can cause an invitation or morning note."""
    if state.game_minutes <= before:
        return
    from . import comfort
    calendar = state.v2['calendar']
    today = day_number(state.game_minutes)
    special = lake_day(state.lake_id, state.game_minutes)
    notes = calendar.get('lake_day_notes')
    if not isinstance(notes, dict):
        notes = calendar['lake_day_notes'] = {}
    if special and notes.get(state.lake_id) != today:
        state.toast(f'It is {day_name(state.game_minutes)}. On {state._world.name}, that means {special.name}.')
        notes[state.lake_id] = today
    if calendar.get('invitation_day') != today or not calendar.get('invitations_used', 0):
        comfort.weather_invitation(state)


def forecast_day(state, day):
    """Merged clock spans for a single dawn-to-dawn journal row."""
    start = day * DAY_MINUTES
    spans = []
    for slot in range(24):
        weather = weather_at(state, start + slot * 60)
        if spans and spans[-1][2] == weather:
            spans[-1] = (spans[-1][0], start + (slot + 1) * 60, weather)
        else:
            spans.append((start + slot * 60, start + (slot + 1) * 60, weather))
    return tuple(spans)


def forecast_text(state, day):
    return [f'{clock_string(start)}–{clock_string(end)}: {weather.replace("_", " ")}'
            for start, end, weather in forecast_day(state, day)]
