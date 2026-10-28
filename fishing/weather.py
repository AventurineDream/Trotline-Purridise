"""Continuous sky and weather lighting, sampled directly from the lake clock."""

from __future__ import annotations

import math

import numpy as np

from .data import hour_of_day, weather_at


# Crossfade for an hour on the lake, centered on each scheduled change.
# This is five real seconds at 12x, and needs no retained frame history.
BLEND_MINUTES = 60.0
_WEATHER = {
    "clear": dict(cloud_cover=0.40, cloud_shade=0.0, overcast=0.0,
                  rain=0.0, ripple=0.75, transmission=1.0),
    "fair": dict(cloud_cover=0.72, cloud_shade=0.0, overcast=0.0,
                 rain=0.0, ripple=0.90, transmission=1.0),
    "overcast": dict(cloud_cover=1.10, cloud_shade=1.0, overcast=0.58,
                     rain=0.0, ripple=1.20, transmission=0.30),
    "drizzle": dict(cloud_cover=1.20, cloud_shade=1.0, overcast=0.70,
                    rain=1.0, ripple=1.75, transmission=0.30),
}
for _name, _base, _mist in (("mist", "overcast", .65), ("snow_mist", "overcast", .85),
                           ("fog", "overcast", 1.0), ("aurora", "clear", 0.0)):
    _WEATHER[_name] = {**_WEATHER[_base], "mist": _mist}
for _properties in _WEATHER.values():
    _properties.setdefault("mist", 0.0)
    _properties["snow"] = float(_properties is _WEATHER["snow_mist"])


def weather_visuals(game_minutes: float, state=None) -> dict:
    """Blend visual properties without changing the fishing weather schedule.

    Midnight changes the hour branch, while 6 AM changes the schedule's day
    index. Both boundaries must be included, along with the daytime changes.
    """
    minutes = max(0.0, game_minutes)
    if state is not None:
        from .calendar import weather_at as planned
        boundary = round(minutes / 60) * 60
        if boundary > 0 and abs(minutes-boundary) < BLEND_MINUTES / 2:
            before = _WEATHER[planned(state, boundary - .001)]
            after = _WEATHER[planned(state, boundary + .001)]
            t = (minutes-boundary) / BLEND_MINUTES + .5
            t = t*t*(3-2*t)
            return {key: before[key]*(1-t) + after[key]*t for key in before}
        return dict(_WEATHER[planned(state, minutes)])
    solar_day = math.floor((minutes + 360.0) / 1440.0)
    for day in (solar_day - 1, solar_day, solar_day + 1):
        for clock_minute in (0.0, 360.0, 600.0, 990.0, 1230.0):
            boundary = day * 1440.0 + clock_minute - 360.0
            if boundary <= 0.0 or abs(minutes - boundary) >= BLEND_MINUTES / 2:
                continue
            before = _WEATHER[weather_at(boundary - 0.001)]
            after = _WEATHER[weather_at(boundary + 0.001)]
            t = (minutes - boundary) / BLEND_MINUTES + 0.5
            t = t * t * (3.0 - 2.0 * t)
            return {key: before[key] * (1.0 - t) + after[key] * t for key in before}
    return dict(_WEATHER[weather_at(minutes)])


def _lerp(a, b, t):
    return a * (1.0 - t) + b * t


def celestial(hour: float):
    """Unit direction and intensity on a continuous, repeating 24-hour orbit."""
    elapsed = (hour - 5.65) % 24.0
    if elapsed <= 13.55:
        az = elapsed * math.pi / 13.55
        height = max(0.0, math.sin(az))
        elev = height * 0.92
        # The disc and illumination fade at the horizon, including sunrise.
        fade = min(1.0, elev / 0.08)
        fade = fade * fade * (3.0 - 2.0 * fade)
        intensity = (0.18 + 0.82 * height ** 0.75) * fade
    else:
        az = math.pi + (elapsed - 13.55) * math.pi / 10.45
        elev = math.sin(az) * 0.75
        intensity = 0.0
    horiz = math.sqrt(max(0.0, 1.0 - elev * elev))
    d = np.array([math.cos(az) * horiz, elev, -math.sin(az) * horiz], np.float32)
    return d, float(intensity)


def frame_light(hour: float, weather: str, conditions: dict | None = None) -> dict:
    conditions = _WEATHER[weather] if conditions is None else conditions
    sun, sun_i = celestial(hour)
    moon, moon_i = celestial(hour + 12.2)
    moon_i *= max(0.0, 1.0 - sun_i * 1.5) * 0.5
    night = float(np.clip((0.10 - float(sun[1])) / 0.40, 0.0, 1.0))
    gold = math.exp(-((float(sun[1]) - 0.05) ** 2) / 0.012)
    gold *= float(np.clip((float(sun[1]) + 0.10) / 0.15, 0.0, 1.0))
    zenith = _lerp(np.array([0.31, 0.53, 0.72], np.float32),
                   np.array([0.014, 0.024, 0.050], np.float32), night)
    horizon = _lerp(np.array([0.77, 0.84, 0.86], np.float32),
                    np.array([0.04, 0.055, 0.085], np.float32), night)
    zenith = _lerp(zenith, np.array([0.32, 0.36, 0.58], np.float32), gold * 0.4)
    horizon = _lerp(horizon, np.array([0.95, 0.67, 0.43], np.float32), gold)
    # Cloudy skies have night colors too; a midnight weather change should
    # never introduce the bright gray of a daytime storm.
    cloud_zenith = _lerp(np.array([0.40, 0.44, 0.48], np.float32),
                         np.array([0.018, 0.029, 0.045], np.float32), night)
    cloud_horizon = _lerp(np.array([0.55, 0.58, 0.60], np.float32),
                          np.array([0.045, 0.060, 0.080], np.float32), night)
    zenith = _lerp(zenith, cloud_zenith, conditions["overcast"])
    horizon = _lerp(horizon, cloud_horizon, conditions["overcast"])
    sun_i *= conditions["transmission"]
    moon_i *= conditions["transmission"]
    gold *= 1.0 - conditions["cloud_shade"] * 0.75
    return {
        **conditions, "sun": sun, "sun_i": sun_i, "moon": moon, "moon_i": moon_i,
        "night": night, "gold": gold, "zenith": zenith.astype(np.float32),
        "horizon": horizon.astype(np.float32),
    }


def lighting_at(game_minutes: float, state=None) -> dict:
    from .calendar import weather_at as planned
    weather = weather_at(game_minutes) if state is None else planned(state, game_minutes)
    light = frame_light(hour_of_day(game_minutes), weather, weather_visuals(game_minutes, state))
    if state is not None:
        from .lakes import LAKES
        environment = LAKES[state.lake_id].get("environment")
        if environment:
            strength = (1-light["night"])*(1-light["gold"])*(1-light["overcast"])*.65
            for key in ("zenith", "horizon"):
                light[key] = _lerp(light[key], np.array(environment["sky_"+key], np.float32), strength)
    return light


def wind_at(game_minutes: float, state=None) -> tuple[float,float]:
    """Direction the wind blows toward, in heading radians, and metres/second."""
    conditions = weather_visuals(game_minutes, state)
    heading = 0.85 + 0.30*math.sin(game_minutes*math.tau/1440.0) + 0.10*math.sin(game_minutes/210.0)
    speed = 4.6 + 1.3*conditions["cloud_shade"] + 1.5*conditions["rain"] + 0.65*math.sin(game_minutes/170.0)
    if state is not None and state.lake_id == "flathead":
        speed += .7 + .45*math.sin(game_minutes/37.0)
    return heading,speed
