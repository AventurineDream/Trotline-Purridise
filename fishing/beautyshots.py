"""Key-art review frames for every lake (06 §9, V1-42).

python -m fishing --shots shots/beauty --beauty [--software] [--lakes=briar,crater]

For each lake, two views (the slip's opening view, and back toward the landing) at
dawn, noon, dusk and night in calm weather, plus the lake's signature weather. Each
frame is the scene alone, with no HUD, at 1280x720. contact.png is a labelled grid of
every frame, and beauty.json records the minute, weather and backend of each.
"""

from __future__ import annotations

import gc
import json
import math
from pathlib import Path

import numpy as np

from . import calendar
from .content import load_content
from .fishshots import _sheet, _tiny_label
from .imageops import resize_rgb
from .lakes import LAKES
from .npcs import active_npcs
from .pngsave import write_png
from .render import Renderer
from .sim import State
from .world import World

SIZE = (1280, 720)
THUMB = (384, 216)
SEED = 723
DAY = 1440
WEEKS = 12
# Clock minutes after 06:00, each mid-hour (outside the hourly weather crossfade), in order
# of preference. The forecasts band weather by hour, so a lake whose dawn is always misty
# takes its next calm hour, and a lake whose evenings are aurora takes the small hours.
TIMES = (("dawn", (30, 90)), ("noon", (390,)), ("dusk", (795, 750)),
         ("night", (1050, 1230, 1170)))
CALM = ("clear", "fair")
# The weather that makes each lake its own, at an hour its forecast gives it.
SIGNATURE = {"briar": ("mist", (30, 90)), "cedar": ("drizzle", (510, 390)),
             "flathead": ("snow_mist", (30, 1050)), "crater": ("fog", (30, 1170)),
             "nebula": ("aurora", (1050,))}
VIEWS = (("slip", 0.0), ("back", math.pi))


def _minute(seed, lake, clocks, wanted):
    """The first game minute at one of these clock times whose planned weather is wanted."""
    for clock in clocks:
        for day in range(1, WEEKS * 7):
            minute = day * DAY + clock
            if calendar.planned_weather(seed, lake, minute) in wanted:
                return minute
    return None


def moments(seed, lake):
    """(name, game minute, weather) for each frame of a lake, in contact-sheet order."""
    rows = []
    for name, clocks in TIMES:
        minute = _minute(seed, lake, clocks, CALM)
        if minute is not None:
            rows.append((name, minute, calendar.planned_weather(seed, lake, minute)))
    weather, clocks = SIGNATURE[lake]
    minute = _minute(seed, lake, clocks, (weather,))
    if minute is not None:
        rows.append((weather, minute, weather))
    return rows


def shots(dest, *, software=False, lakes=None):
    lakes = tuple(LAKES) if lakes is None else tuple(lakes)
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    content = load_content()
    cells, records = [], []
    for lake in lakes:
        world = World(lake)
        renderer = Renderer(world, *SIZE, software=software)
        try:
            state = State.new(world, seed=SEED)
            state.v2["story"]["chapter"] = 5
            state.toasts.clear()
            seed = calendar.forecast_seed(state)
            state.v2.setdefault("calendar", {})["seed"] = seed
            home = (state.x, state.z, state.yaw)
            for view, turn in VIEWS:
                for name, minute, weather in moments(seed, lake):
                    state.x, state.z = home[0], home[1]
                    state.yaw = (home[2] + turn + math.pi) % math.tau - math.pi
                    state.game_minutes = minute
                    state.light = name == "night" or (name == weather and minute % DAY >= 900)
                    state.npcs = active_npcs(state, world, content)
                    state.anim = 2.0
                    frame = resize_rgb(renderer.render(state), *SIZE)
                    label = f"{lake}-{view}-{name}"
                    write_png(out / f"{label}.png", frame)
                    cell = resize_rgb(frame, *THUMB).copy()
                    _tiny_label(cell, f"{lake} {view} {name} ({weather})", 8, 8)
                    cells.append(cell)
                    records.append({"frame": label, "lake": lake, "view": view, "moment": name,
                                    "game_minutes": minute, "weather": weather,
                                    "backend": renderer.backend})
                    print(f"{label:28s} {weather:10s} {renderer.backend}")
        finally:
            renderer.close()
            del renderer, world
            gc.collect()
    per_row = len(TIMES) + 1
    write_png(out / "contact.png", _sheet(cells, per_row, (24, 28, 30)))
    (out / "beauty.json").write_text(json.dumps({"size": SIZE, "frames": records}, indent=2) + "\n")
    return records


def side_by_side(before_dir, after_dir, dest):
    """A before/after contact sheet: each frame's before beside its after (V1-42 PR evidence)."""
    before_dir, after_dir = Path(before_dir), Path(after_dir)
    names = sorted(p.stem for p in after_dir.glob("*.png") if p.stem != "contact" and (before_dir / p.name).exists())
    from .pngsave import read_png
    cells = []
    if not names:
        raise ValueError("no frame is in both folders")
    for name in names:
        for side, folder in (("before", before_dir), ("after", after_dir)):
            cell = resize_rgb(read_png(folder / f"{name}.png"), *THUMB).copy()
            _tiny_label(cell, f"{name} {side}", 8, 8)
            cells.append(cell)
    sheet = _sheet(cells, 4, (24, 28, 30))
    write_png(Path(dest), sheet)
    return names
