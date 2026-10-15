"""Weather continuity, menu controls, and accelerated lake-clock regressions."""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import numpy as np

from .data import BAITS, SPECIES
from .game import Keys, Session
from .platform import Input
from .sim import Catch, HeldLine, State
from .ui import HELP_N, check_rows
from .weather import celestial, lighting_at, weather_visuals


def interface_checks(world):
    with tempfile.TemporaryDirectory(prefix="briar-menus-") as temp:
        state = State.new(world, seed=51)
        state.x = state.z = state.yaw = 0.0
        state.held.extend([HeldLine("std"), HeldLine("std")])
        error = state.try_set(world, 0, "worm")
        if error:
            raise AssertionError(error)
        state.well = [Catch("bluegill", 0.5, 1, 0, "flats", "worm", 6),
                      Catch("bullhead", 1.5, 1, 0, "flats", "worm", 6)]
        session = Session(world, Path(temp) / "save.json", state, True)

        # Every selectable menu accepts W/S and wraps just like the arrows.
        for mode, field, count in (
            ("title", "title_i", 2), ("pause", "pause_i", 4),
            ("shop", "shop_i", len(BAITS)), ("setbait", "set_bait", len(BAITS)),
            ("check", "check_i", len(check_rows(state, 0))),
            ("journal", "journal_i", len(SPECIES)), ("well", "well_i", 2),
        ):
            session.ui.mode = mode
            session.ui.shop_tab = 1
            setattr(session.ui, field, 0)
            session.tick(Keys(pressed={"s", "down"}), 0.05)
            if getattr(session.ui, field) != 1:
                raise AssertionError(f"{mode}: S/down did not move exactly one row")
            session.tick(Keys(pressed={"w"}), 0.05)
            session.tick(Keys(pressed={"w"}), 0.05)
            if getattr(session.ui, field) != count - 1:
                raise AssertionError(f"{mode}: W did not wrap to the last row")
            session.tick(Keys(pressed={"s"}), 0.05)
            if getattr(session.ui, field) != 0:
                raise AssertionError(f"{mode}: S did not wrap to the first row")
            if state.throttle_setting or state.look:
                raise AssertionError(f"{mode}: navigation changed the boat controls")

        session.ui.mode = "shop"
        session.ui.shop_tab = 0
        session.tick(Keys(pressed={"d", "right"}), 0.05)
        if session.ui.shop_tab != 1:
            raise AssertionError("D/right advanced more than one shop tab")
        session.tick(Keys(pressed={"a"}), 0.05)
        if session.ui.shop_tab != 0:
            raise AssertionError("A did not return to the previous shop tab")
        session.ui.mode = "setbait"
        session.ui.set_line = 0
        session.tick(Keys(pressed={"d"}), 0.05)
        if session.ui.set_line != 1:
            raise AssertionError("D did not choose the next held line")
        session.tick(Keys(pressed={"a"}), 0.05)
        if session.ui.set_line:
            raise AssertionError("A did not return to the previous held line")

        session.ui.mode = "help"
        for key in ("d", "s", "a", "w", "right", "down", "left", "up"):
            session.ui.help_page = 0
            session.tick(Keys(pressed={key}), 0.05)
            expected = 1 if key in {"d", "s", "right", "down"} else HELP_N-1
            if session.ui.help_page != expected:
                raise AssertionError(f"{key} did not turn the field guide page")

        # Exercise the actual keyboard repeat implementation, rather than the
        # headless Keys helper, including releasing and pressing the key again.
        session.ui.mode = "journal"
        session.ui.journal_i = 0
        keys = Input()
        keys.pressed = keys.held = {"s"}
        session.tick(keys, 0.05)
        keys.pressed = set()
        for _ in range(9):
            session.tick(keys, 0.1)
        if session.ui.journal_i < 3:
            raise AssertionError("holding S did not repeat menu navigation")
        keys.held = set()
        session.tick(keys, 0.1)
        previous = session.ui.journal_i
        keys.pressed = keys.held = {"s"}
        session.tick(keys, 0.05)
        if session.ui.journal_i != previous + 1:
            raise AssertionError("menu key repeat did not reset after release")

        session.ui.mode = "pause"
        state.anchored = False
        session.tick(Keys(held={"w"}), 0.05)
        session.tick(Keys(pressed={"esc"}, held={"w"}), 0.05)
        session.tick(Keys(held={"w"}), 0.1)
        if session.ui.mode != "play" or state.throttle_setting:
            raise AssertionError("a held menu key became boat throttle on exit")
        session.tick(Keys(), 0.05)
        session.tick(Keys(held={"w"}), 0.1)
        if state.throttle_setting <= 0:
            raise AssertionError("W did not resume driving after being released")
        session.tick(Keys(held={"shift"}), 0.05)
        session.ui.mode = "map"
        session.tick(Keys(held={"w"}), 0.1)
        if state.throttle_setting <= 0:
            raise AssertionError("chart mode lost its boat throttle controls")

        state.anchored = True
        state.speed = state.throttle = state.throttle_setting = 0.0
        state.time_scale = 1
        session.ui.mode = "play"
        for expected in (3, 6, 12, 1):
            session.tick(Keys(pressed={"t"}), 0.05)
            if state.time_scale != expected:
                raise AssertionError("T did not cycle 1x, 3x, 6x, 12x, 1x")
        state.time_scale = 12
        state.minute_acc = 0
        start = state.game_minutes
        state.advance(1.0, False)
        if state.game_minutes - start != 12:
            raise AssertionError("12x did not advance twelve minutes in one second")
        state.anchored = False
        state.speed = 2.0
        start = state.game_minutes
        state.advance(1.0, False)
        if state.game_minutes - start != 1 or state.cycle_scale() is None:
            raise AssertionError("accelerated time was available while driving")
        session.ui.mode = "pause"
        clock = (state.game_minutes, state.minute_acc)
        session.tick(Keys(), 1.0)
        if (state.game_minutes, state.minute_acc) != clock:
            raise AssertionError("12x bypassed a frozen menu")
        session.save()
        if State.load(session.save_path, world).time_scale != 12:
            raise AssertionError("12x did not survive a save roundtrip")
    print("menus/time ok  WASD, arrows, repeat, held keys on exit, chart driving, "
          "12x cycle, clock, driving restriction and saves")


def weather_checks(renderer, world):
    # The two weather schedules repeat together every twenty game days.
    # Check both sides of every boundary and both ends of every crossfade.
    worst = 0.0
    for day in range(20):
        for clock_minute in (0, 360, 600, 990, 1230):
            boundary = day * 1440 + clock_minute - 360
            for point in (boundary - 30, boundary, boundary + 30):
                if point <= 0:
                    continue
                before, after = lighting_at(point - 0.0001), lighting_at(point + 0.0001)
                for key in before:
                    delta = float(np.max(np.abs(np.asarray(before[key]) - after[key])))
                    worst = max(worst, delta)
                    if delta > 0.00003:
                        raise AssertionError(f"{key} jumped at lake minute {point}: {delta}")
    for hour in (0, 5.65, 19.2, 24):
        before, ib = celestial(hour - 0.00001)
        after, ia = celestial(hour + 0.00001)
        if np.linalg.norm(before - after) > 0.00003 or abs(ib - ia) > 0.00003:
            raise AssertionError(f"celestial orbit jumped at hour {hour}")
        if not math.isclose(float(np.linalg.norm(after)), 1.0, abs_tol=0.00001):
            raise AssertionError("celestial direction is not normalized")
    midnight = 3 * 1440 + 1080
    amounts = [weather_visuals(midnight + offset)["rain"] for offset in (-30, -15, 0, 15, 30)]
    if amounts[0] != 1 or amounts[-1] != 0 or any(a <= b for a, b in zip(amounts, amounts[1:])):
        raise AssertionError("midnight rain did not fade steadily")
    if np.max(lighting_at(midnight)["zenith"]) > 0.1:
        raise AssertionError("clouds made the midnight sky as bright as daytime")
    if weather_visuals(0)["rain"]:
        raise AssertionError("a new morning inherited weather from before the game started")

    # Actual images catch categorical shader switches even when Python's
    # lighting properties are continuous. Include the fractional-minute wrap.
    state = State.new(world, seed=52)
    state.x = state.z = state.yaw = 0.0
    state.look = 0.12
    state.anim = 7.0
    pixel_delta = 0.0
    for point in (348, 792, 1080, 1419, 2 * 1440 + 1080, midnight, 3 * 1440 + 630):
        state.game_minutes = point - 1
        state.minute_acc = 0.999
        before = renderer.render(state).copy()
        state.game_minutes = point
        state.minute_acc = 0.001
        after = renderer.render(state)
        delta = float(np.abs(before.astype(np.float32) - after).mean())
        pixel_delta = max(pixel_delta, delta)
        if delta > 0.3:
            raise AssertionError(f"rendered lighting jumped at lake minute {point}: {delta}")
    print(f"weather ok  twenty-day schedule, midnight, sunrise, sunset and moon; "
          f"max lighting step {worst:.6f}, max pixel step {pixel_delta:.4f}/255")
