"""--shots <dir> --legendary: each caught legendary's encounter as a keyframe sequence (V1-37).

Each of the ten caught legendaries is drawn on its own lake, at the start of its next real
eligible window (so the hour and the weather are its own), with its hook at the top of the
haul. The scene is drawn as the water stills, as the line hums, as the fish surfaces, and as it
holds with its name, then its book page with the photo. The Zero-G Winch variant is drawn
for the Nebula Weaver (it needs the winch) and once more for Old Lantern. Old Lantern is
also drawn under Reduced Motion, and on its page in the book. A contact sheet and
`legendary-encounters.json` (each frame's beats, the scene's length, and whether it can be
skipped the first time and after) go beside them.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from . import calendar, encounter
from .imageops import resize_rgb
from .legendary import LEGENDARY_DATA, roll_legendary_weight
from .platform import Text
from .pngsave import write_png
from .render import Renderer
from .sim import Catch, Hook, SetLine, State
from .ui import UI, UIState
from .world import World

W, H = 1280, 720
TIMES = (0.0, 1.0, 2.2, 3.2, 4.6)   # stilling, humming, surfacing, surfaced, named
HOOK = 2


def _staged(world, legendary_id: str, *, winch: bool = False, reduced: bool = False) -> State:
    """A save on the legendary's lake, at its next eligible window, its line up to the hook."""
    from .data import hour_of_day
    state = State.new(world, seed=37)
    state.toasts.clear()
    state.tutorial = 4
    state.anim = 14.0
    state._park(world)
    start, _end = calendar.next_legendary_window(calendar.forecast_seed(state), legendary_id, 1440.0)
    state.game_minutes = int(start) + 20
    state.v2["settings"]["reduced_motion"] = reduced
    if winch:
        state.v2["profile"].setdefault("tools", []).append("zero_g_winch")
    row = LEGENDARY_DATA[legendary_id]
    zone = (row.get("zones") or (row.get("area_id", ":open").partition(":")[2],))[0]
    catch = Catch(legendary_id, roll_legendary_weight(legendary_id, state.rng), 1.0, 0.0, zone,
                  row["bait"], hour_of_day(state.game_minutes), lake_id=world.id,
                  catch_game_minute=state.game_minutes, legendary=True, disposition="release")
    hooks = [Hook(True) for _ in range(8)]
    hooks[HOOK] = Hook(False, catch)
    state.lines = [SetLine("heavy", row["bait"], state.x + 6, state.z + 6, state.x + 44, state.z + 10, zone, hooks)]
    state._note_journal(catch)  # the record its book page and photo caption show
    return state


def _panel(legendary_id: str, phase: str, t: float = 0.0) -> UIState:
    return UIState(mode="haul", has_save=True, check_line=0, haul_index=HOOK, haul_phase=phase,
                   haul_phase_timer=t, haul_timer=1.0, haul_legendary=legendary_id)


def _draw(renderer, ui, state, panel) -> np.ndarray:
    reduced = bool(state.v2["settings"].get("reduced_motion", False))
    state.encounter_still = encounter.water_still(panel, reduced=reduced)
    frame = resize_rgb(renderer.render(state), W, H)
    ui.draw(frame, state, panel)
    return frame


def _sequence(renderer, ui, state, legendary_id, name, out, thumbs, times) -> list:
    reduced = bool(state.v2["settings"].get("reduced_motion", False))
    frames = []
    for i, t in enumerate(times):
        frame = _draw(renderer, ui, state, _panel(legendary_id, "encounter", t))
        write_png(out / f"legendary-{name}-{i}.png", frame)
        beats = encounter.look(t, reduced=reduced)
        frames.append({"t": t, "still": round(state.encounter_still, 3),
                       **{k: round(float(v), 3) for k, v in beats.items() if k != "still"}})
        thumb = resize_rgb(frame, 320, 180)
        ui._text(thumb, f"{name} {t:.1f}s", 6, 4, 11, (255, 236, 180))
        thumbs.append(thumb)
    return frames


def shots(dest, *, software: bool = False) -> dict:
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    text = Text()
    report, thumbs = {}, []
    renderer, world = None, None
    try:
        for legendary_id in encounter.caught_ids():
            lake = LEGENDARY_DATA[legendary_id]["lake"]
            if world is None or world.id != lake:
                if renderer is not None:
                    renderer.close()
                world = World(lake)
                renderer = Renderer(world, 640, 360, software=software)
            ui = UI(text, world)
            ui.fish_card_renderer = getattr(renderer, "fish_card", None)
            winch = legendary_id == "nebula_weaver"   # its gate is the winch (03 §3)
            state = _staged(world, legendary_id, winch=winch)
            first = not encounter.presented(state.v2, legendary_id)
            frames = _sequence(renderer, ui, state, legendary_id, legendary_id, out, thumbs, TIMES)
            page = _draw(renderer, ui, state, _panel(legendary_id, "card"))
            write_png(out / f"legendary-{legendary_id}-page.png", page)
            thumb = resize_rgb(page, 320, 180)
            ui._text(thumb, f"{legendary_id} page", 6, 4, 11, (255, 236, 180))
            thumbs.append(thumb)
            encounter.mark_presented(state.v2, legendary_id)
            report[legendary_id] = {
                "lake": lake, "game_minute": state.game_minutes,
                "clock": calendar.clock_string(state.game_minutes),
                "weather": calendar.weather_at(state, state.game_minutes),
                "variant": encounter.variant(state), "scene_s": encounter.SCENE_S,
                "skippable_first_time": not first,
                "skippable_after": encounter.presented(state.v2, legendary_id),
                "stamp": encounter.bespoke(legendary_id).get("stamp", encounter.STAMP),
                "frames": frames,
            }
            if legendary_id == "old_lantern":
                extra = _staged(world, legendary_id, winch=True)
                report["old_lantern-winch"] = {"variant": encounter.variant(extra), "frames": _sequence(
                    renderer, ui, extra, legendary_id, "old_lantern-winch", out, thumbs, (2.2, 4.6))}
                still = _staged(world, legendary_id, reduced=True)
                report["old_lantern-reduced"] = {"variant": encounter.variant(still), "frames": _sequence(
                    renderer, ui, still, legendary_id, "old_lantern-reduced", out, thumbs, (0.0,))}
                from .bookview import ENTRY_IDS
                book = resize_rgb(renderer.render(state), W, H)
                ui.draw(book, state, UIState(mode="journal", has_save=True, journal_page=1,
                                             book_entry_i=ENTRY_IDS.index(legendary_id)))
                write_png(out / "legendary-book-page.png", book)
                thumb = resize_rgb(book, 320, 180)
                ui._text(thumb, "book page", 6, 4, 11, (255, 236, 180))
                thumbs.append(thumb)
        columns = 6
        rows = math.ceil(len(thumbs) / columns)
        sheet = np.zeros((rows * 180, columns * 320, 3), np.uint8)
        for i, thumb in enumerate(thumbs):
            sheet[(i // columns) * 180:(i // columns + 1) * 180, (i % columns) * 320:(i % columns + 1) * 320] = thumb
        write_png(out / "legendary-contact-sheet.png", sheet)
        (out / "legendary-encounters.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"legendary encounter shots: {sum(len(v['frames']) for v in report.values())} scene frames, "
              f"{len(encounter.caught_ids())} book pages in {out}")
        return report
    finally:
        if renderer is not None:
            renderer.close()
        text.close()
