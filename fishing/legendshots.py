"""--shots <dir> --legendary: each caught legendary's encounter as a keyframe sequence (V1-37).

Each of the ten caught legendaries is drawn on its own lake, at the start of its next real
eligible window (so the hour and the weather are its own), with its hook at the top of the
haul. The scene is drawn as the water stills, as the line hums, as the fish surfaces, and as it
holds with its name, then its book page with the photo. The Zero-G Winch variant is drawn
for the Nebula Weaver (it needs the winch) and once more for Old Lantern. Old Lantern is
also drawn under Reduced Motion, and on its page in the book.

Part 2 adds the ten trophy replicas, three boats' rails hung with them, the book's Trophy page,
and the Star-Whale coming back after the finale (and once under Reduced Motion). A contact
sheet and `legendary-encounters.json` (each frame's beats, the scene's length, whether it can be
skipped the first time and after, the rails, and the whale's return) go beside them.
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


RAIL_BOATS = ("deepv_skiff", "party_barge", "nebula_cruiser")
WHALE_TIMES = (0.0, 1.5, 6.0, 8.5, 12.5, 15.0)


def _thumb(ui, thumbs, frame, label):
    thumb = resize_rgb(frame, 320, 180)
    ui._text(thumb, label, 6, 4, 11, (255, 236, 180))
    thumbs.append(thumb)


def _trophies(out, text, thumbs, *, software) -> dict:
    """Part 2: the ten replicas, three boats' rails hung with them, and the Trophy page."""
    from . import replica
    from .bookview import trophy_items
    world = World("briar")
    renderer = Renderer(world, 640, 360, software=software)
    ui = UI(text, world)
    try:
        cells = []
        for legendary_id in encounter.caught_ids():
            cell = replica.picture("legendary", legendary_id, 320, 200).copy()
            ui._text(cell, LEGENDARY_DATA[legendary_id]["name"], 6, 4, 11, (40, 30, 20), shadow=False)
            cells.append(cell)
        sheet = np.concatenate([np.concatenate(cells[i:i + 5], axis=1) for i in range(0, 10, 5)])
        write_png(out / "legendary-replicas.png", sheet)
        _thumb(ui, thumbs, sheet, "replicas")
        rails = {}
        for boat in RAIL_BOATS:
            state = State.new(world, seed=37)
            state.toasts.clear()
            state.tutorial = 4
            state.owned_boats = list(dict.fromkeys(list(state.owned_boats) + [boat]))
            state.boat_id = boat
            state._park(world)
            state.game_minutes = 1440 + 300
            for legendary_id in ("old_lantern", "caldera_fire_lizard", "nebula_weaver"):
                state._note_journal(Catch(legendary_id, LEGENDARY_DATA[legendary_id]["weight_lb"], 1.0, 0.0, "open",
                                          LEGENDARY_DATA[legendary_id]["bait"], 21.0, legendary=True))
                state.mount_legendary_replica(legendary_id)
            state._note_journal(Catch("bluegill", 0.8, 1.0, 0.0, "flats", "worm", 9.0, shiny=True))
            state.mount_shiny_trophy("bluegill")
            view = replica.rail_view(state, 360)
            write_png(out / f"legendary-rail-{boat}.png", view)
            _thumb(ui, thumbs, view, f"rail {boat}")
            rails[boat] = [list(t) for t in state.rail_trophies()]
            if boat == RAIL_BOATS[0]:
                page = resize_rgb(renderer.render(state), W, H)
                ui.draw(page, state, UIState(mode="journal", has_save=True, journal_page=2, book_shelf=2,
                                             book_collection_i=1))
                write_png(out / "legendary-trophy-page.png", page)
                _thumb(ui, thumbs, page, "trophy page")
                items = [list(item[:2]) for item in trophy_items(state)]
        return {"rails": rails, "trophy_page": items, "rail_slots": replica.RAIL_SLOTS}
    finally:
        renderer.close()


def _whale_return(out, text, thumbs, *, software) -> dict:
    """Part 2: the Star-Whale coming back to a Skipper settled by the reflection, after the finale."""
    from . import staging, whale
    from .lakes import place
    world = World("nebula")
    renderer = Renderer(world, 640, 360, software=software)
    ui = UI(text, world)
    frames = []
    try:
        for reduced in (False, True):
            state = State.new(world, seed=37)
            state.toasts.clear()
            state.tutorial = 4
            state.anim = 14.0
            row = place("nebula:calm_reflection")[1]
            state.x, state.z, state.yaw, state.anchored, state.speed = row["x"], row["z"], 0.6, True, 0.0
            state.v2["story"]["completed_chapters"] = [1, 2, 3, 4, 5]
            state.set_scene_status("story_c5_whale", "done")
            start, _end = calendar.next_legendary_window(calendar.forecast_seed(state), "star_whale", 1440.0)
            state.game_minutes = int(start) + 10
            state.v2["settings"]["reduced_motion"] = reduced
            ready = whale.can_return(state, world)
            for i, t in enumerate((0.0, 8.5) if reduced else WHALE_TIMES):
                clock = staging.Clock("whale_return", t=t, repeat=True)
                state.stage_light = staging.light_overrides(clock, reduced=reduced)
                cam = staging.staged_camera(renderer, state, clock, reduced=reduced)
                frame = resize_rgb(renderer.render(state, cam), W, H)
                ui.draw(frame, state, UIState(mode="play", has_save=True, whale_return=True,
                                              stage_fx=staging.sample(clock, reduced=reduced)), cam)
                name = f"legendary-whale-return{'-reduced' if reduced else ''}-{i}"
                write_png(out / f"{name}.png", frame)
                _thumb(ui, thumbs, frame, f"whale return{' reduced' if reduced else ''} {t:.1f}s")
                frames.append({"t": t, "reduced": reduced, "ready": ready,
                               **{k: round(float(v), 3) for k, v in (state.stage_light or {}).items()}})
        return {"wait_s": whale.WAIT_S, "risen_s": whale.RISEN_S,
                "duration_s": staging.PLAY_STAGES["whale_return"].duration, "frames": frames}
    finally:
        renderer.close()


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
        renderer.close()
        renderer = None
        report["trophies"] = _trophies(out, text, thumbs, software=software)
        report["whale-return"] = _whale_return(out, text, thumbs, software=software)
        columns = 6
        rows = math.ceil(len(thumbs) / columns)
        sheet = np.zeros((rows * 180, columns * 320, 3), np.uint8)
        for i, thumb in enumerate(thumbs):
            sheet[(i // columns) * 180:(i // columns + 1) * 180, (i % columns) * 320:(i % columns + 1) * 320] = thumb
        write_png(out / "legendary-contact-sheet.png", sheet)
        (out / "legendary-encounters.json").write_text(json.dumps(report, indent=2) + "\n")
        scenes = sum(len(v["frames"]) for k, v in report.items() if k not in ("trophies", "whale-return"))
        print(f"legendary encounter shots: {scenes} scene frames, {len(encounter.caught_ids())} book pages, "
              f"{len(RAIL_BOATS)} rails, {len(report['whale-return']['frames'])} whale-return frames in {out}")
        return report
    finally:
        if renderer is not None:
            renderer.close()
        text.close()
