"""--shots <dir> --story: each staged story scene as a keyframe sequence (V1-35).

Every staged scene is drawn at its keyframes, with its first bubble on screen, on the lake
and at the hour it plays: the prologue's arrival at Briar, the fog lifting off Crater's
survey marker, the Star-Whale and "Draw it" on the Lagoon, the ending at the landing and the
credits rising over the dawn. Settle In's three cues are drawn as the HUD shows them. The
prologue is drawn once more under Reduced Motion, where nothing moves. A contact sheet
and `story-staging.json` (each frame's time, fade, letterbox, light and camera) go beside
them.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from .content import load_content
from .imageops import resize_rgb
from .lakes import place
from .platform import Text
from .pngsave import write_png
from .render import Renderer
from .sim import State
from . import staging
from .story import scene_conversation
from .ui import UI, UIState
from .world import World

W, H = 1280, 720


def _sequence(scene_id: str, stage_id: str) -> tuple[float, ...]:
    """The stage's keyframes, plus its midpoints, so every ease is seen once."""
    times = [key.t for key in staging.STAGES[stage_id].keys]
    mids = [(a + b) / 2 for a, b in zip(times, times[1:]) if b - a > 1.0]
    return tuple(sorted(set(times + mids)))


def _setups():
    """(name, lake, scene, how to place the boat) for each staged scene, in story order."""
    def landing(state, world):
        state._park(world)
        state.game_minutes = 30  # 06:30, the prologue's dawn

    def marker(state, world):
        # A safe cove on Crater, after the fog has lifted (Fog Lift mornings clear at 07:00).
        row = place("crater:safe_cove_1")[1]
        state.x, state.z = row["x"], row["z"]
        state.anchored = True
        state.game_minutes = 4 * 1440 + 75

    def ending(state, world):
        state._park(world)
        state.game_minutes = 1440 + 600

    def credits(state, world):
        ending(state, world)
        state.set_scene_status("ending", "done")  # the author line as the credits show it

    def lagoon(state, world):
        # Anchored at the calm reflection, the whale step read through to its last cue.
        _at_reflection(state, settled=45.0, status="ready")

    return (("prologue-arrival", "briar", "pro_01", landing),
            ("fog-lifting", "crater", "story_c4_clear", marker),
            ("star-whale", "nebula", "story_c5_whale", lagoon),
            ("draw-it", "nebula", "story_c5_drawn", lagoon),
            ("ending", "briar", "end_01", ending),
            ("credits", "briar", "credits", credits))


def _at_reflection(state, *, settled: float, status: str = "active"):
    row = place("nebula:calm_reflection")[1]
    state.x, state.z, state.yaw = row["x"], row["z"], 0.6
    state.anchored, state.speed = True, 0.0
    state.game_minutes = 2 * 1440 + 960  # the Lagoon's Deep band
    state.narrative.quest("story_c5_s2").status = status
    cues = sum(settled >= cue for cue in (15.0, 30.0, 45.0))
    state.v2["story"]["settle"] = {"seconds": settled, "cues": cues, "together": False}


def _frame(renderer, ui, state, content, scene_id, clock, *, reduced):
    state.stage_light = staging.light_overrides(clock, reduced=reduced)
    cam = staging.staged_camera(renderer, state, clock, reduced=reduced)
    frame = resize_rgb(renderer.render(state, cam), W, H)
    fx = staging.sample(clock, reduced=reduced)
    if scene_id == "credits":
        panel = UIState(mode="credits", has_save=True, credits_s=clock.t, stage_fx=fx,
                        credits_rise=staging.credits_rise(clock, reduced=reduced))
    else:
        chat = scene_conversation(state, content, scene_id)
        panel = UIState(mode="dialogue", has_save=True, conversation=chat, dialogue_content=content,
                        stage_fx=fx)
    ui.draw(frame, state, panel, cam)
    record = {"t": round(clock.t, 2), "camera": [round(float(v), 3) for v in (cam.x, cam.y, cam.z, cam.yaw, cam.pitch)],
              **{key: round(float(value), 3) for key, value in (fx or {}).items()}}
    return frame, record


def _settle_cues(renderer, ui, world, out, thumbs) -> dict:
    """Settle In's three cues, as the HUD and the water show them with no sound: before, at
    15 s (still water), 30 s (the lilies in) and 45 s (the deep glow)."""
    from .story import SETTLE_LINES
    frames = []
    for i, seconds in enumerate((5.0, 15.0, 30.0, 45.0)):
        state = State.new(world, seed=35)
        state.toasts.clear()
        state.tutorial = 4
        state.anim = 14.0
        _at_reflection(state, settled=seconds)
        cues = state.v2["story"]["settle"]["cues"]
        if cues:
            state.toast(f"Bot: {SETTLE_LINES[cues - 1]}")  # the cue's caption, as the session shows it
        cam = renderer.camera_for(state)
        frame = resize_rgb(renderer.render(state, cam), W, H)
        panel = UIState(mode="play", has_save=True, settling=True,
                        settle_prompt=f"Settling in. Keep still.  ({cues} of 3)  {{key}} Stop")
        ui.draw(frame, state, panel, cam)
        write_png(out / f"story-settle-in-{i}.png", frame)
        from .finale import settle_look
        frames.append({"seconds": seconds, "cues": cues, **{k: round(v, 3) for k, v in settle_look(state).items()}})
        thumb = resize_rgb(frame, 320, 180)
        ui._text(thumb, f"settle-in {seconds:.0f}s", 6, 4, 11, (255, 236, 180))
        thumbs.append(thumb)
    return {"scene": "settle", "lake": "nebula", "frames": frames}


def shots(dest, *, software: bool = False) -> dict:
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    content = load_content()
    text = Text()
    report, thumbs = {}, []
    renderer, world = None, None
    try:
        for name, lake, scene_id, setup in _setups():
            if world is None or world.id != lake:
                if renderer is not None:
                    renderer.close()
                world = World(lake)
                renderer = Renderer(world, 640, 360, software=software)
            ui = UI(text, world)
            stage_id = staging.stage_of(scene_id)
            runs = [(False, "")] + ([(True, "-reduced")] if scene_id == "pro_01" else [])
            for reduced, suffix in runs:
                state = State.new(world, seed=35)
                state.toasts.clear()
                state.tutorial = 4
                state.anim = 14.0
                state.v2["settings"]["reduced_motion"] = reduced
                setup(state, world)
                frames = []
                times = (0.0, staging.STAGES[stage_id].duration) if reduced else _sequence(scene_id, stage_id)
                for i, t in enumerate(times):
                    clock = staging.Clock(stage_id, t=t)
                    frame, record = _frame(renderer, ui, state, content, scene_id, clock, reduced=reduced)
                    write_png(out / f"story-{name}{suffix}-{i}.png", frame)
                    frames.append(record)
                    thumb = resize_rgb(frame, 320, 180)
                    ui._text(thumb, f"{name}{suffix} {t:.1f}s", 6, 4, 11, (255, 236, 180))
                    thumbs.append(thumb)
                report[name + suffix] = {"scene": scene_id, "lake": lake, "frames": frames}
            if lake == "nebula" and "settle-in" not in report:
                report["settle-in"] = _settle_cues(renderer, ui, world, out, thumbs)
        columns = 5
        rows = math.ceil(len(thumbs) / columns)
        sheet = np.zeros((rows * 180, columns * 320, 3), np.uint8)
        for i, thumb in enumerate(thumbs):
            sheet[(i // columns) * 180:(i // columns + 1) * 180, (i % columns) * 320:(i % columns + 1) * 320] = thumb
        write_png(out / "story-contact-sheet.png", sheet)
        (out / "story-staging.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"story staging shots: {sum(len(v['frames']) for v in report.values())} frames in {out}")
        return report
    finally:
        if renderer is not None:
            renderer.close()
        text.close()
