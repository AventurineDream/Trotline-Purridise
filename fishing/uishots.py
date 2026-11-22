"""The UI screenshot matrix (V1-43): every screen, at every text size, for keyboard and gamepad.

python -m fishing --shots shots/ui --ui-matrix [--software] [--dyslexia] [--screens=play,pause]

Each screen is drawn at 1280x720 over the same lake frame (Little Briar's slip at mid
morning), so the UI is judged against a real scene rather than black. The tool writes:

- contact-<size>-<device>.png: a labelled sheet of every screen for one text size and one
  input device;
- key-<screen>.png: for each key screen, its six versions side by side (three text sizes,
  keyboard above gamepad), at half size so the text can still be read;
- matrix.json: every frame drawn, with its screen, size and device.

--screens limits the run to the named screens (their names are in matrix.json).
"""

from __future__ import annotations

from dataclasses import replace
import json
import math
from pathlib import Path

import numpy as np

from . import uiscreens
from .fishshots import _sheet, _tiny_label
from .imageops import resize_rgb
from .platform import Text
from .pngsave import write_png
from .render import Renderer
from .sim import State
from .ui import UI
from .world import World

SIZE = (1280, 720)
THUMB = (320, 180)
HALF = (640, 360)
TEXT_SIZES = (("small", 0), ("standard", 1), ("large", 2))
DEVICES = ("keyboard", "gamepad")
BACKDROP_MINUTE = 1440 + 4 * 60  # day one, 10:00
SEED = 723
# The screens whose six versions the PR review looks at side by side.
KEY_SCREENS = ("play", "map", "dialogue", "shop Bait", "haul card", "check", "kitchen menu",
               "journal Fish", "well with a fish", "pause", "settings", "your skipper", "help page 24")


def _backdrop(software: bool) -> np.ndarray:
    world = World("briar")
    renderer = Renderer(world, *SIZE, software=software)
    try:
        state = State.new(world, seed=SEED)
        state.game_minutes = BACKDROP_MINUTE
        state.toasts.clear()
        state.anim = 2.0
        return resize_rgb(renderer.render(state), *SIZE).copy()
    finally:
        renderer.close()


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


def matrix(dest, *, software=False, dyslexia_font=False, only=None):
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    backdrop = _backdrop(software)
    world = World("briar")
    text = Text()
    records, sheets, key_cells = [], {}, {}
    try:
        ui = UI(text, world)
        for size_name, size in TEXT_SIZES:
            for name, state, panel in uiscreens.screens(ui, world, dyslexia_font, size):
                if only is not None and name not in only:
                    continue
                for device in DEVICES:
                    frame = backdrop.copy()
                    ui.draw(frame, state, replace(panel, input_device=device))
                    cell = resize_rgb(frame, *THUMB).copy()
                    _tiny_label(cell, f"{name} · {size_name} · {device}", 6, 6)
                    sheets.setdefault((size_name, device), []).append(cell)
                    if name in KEY_SCREENS:
                        half = resize_rgb(frame, *HALF).copy()
                        _tiny_label(half, f"{name} · {size_name} · {device}", 8, 8)
                        key_cells.setdefault(name, {})[(size_name, device)] = half
                    records.append({"screen": name, "text_size": size_name, "device": device,
                                    "dyslexia_font": dyslexia_font})
    finally:
        text.close()
    for (size_name, device), cells in sheets.items():
        cols = min(8, max(1, math.ceil(math.sqrt(len(cells) * 1.6))))
        write_png(out / f"contact-{size_name}-{device}.png", _sheet(cells, cols, (24, 28, 30)))
    for name, cells in key_cells.items():
        ordered = [cells[(size_name, device)] for device in DEVICES for size_name, _ in TEXT_SIZES
                   if (size_name, device) in cells]
        write_png(out / f"key-{_slug(name)}.png", _sheet(ordered, len(TEXT_SIZES), (24, 28, 30)))
    (out / "matrix.json").write_text(json.dumps({
        "size": SIZE, "backdrop": "briar slip, day 1 10:00", "software": software,
        "screens": sorted({row["screen"] for row in records}),
        "frames": records}, indent=2) + "\n")
    print(f"{len(records)} frames: {len({r['screen'] for r in records})} screens x "
          f"{len(TEXT_SIZES)} text sizes x {len(DEVICES)} devices")
    return records
