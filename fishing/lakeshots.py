"""Repeatable five-water captures and warmed full-frame allocation evidence.

python -m fishing --shots shots/lakes --lake-framework [--software]
Use --lakes=briar,flathead,crater,nebula only when Cedar's asset is unavailable.
"""

from __future__ import annotations

import gc
import json
import os
from pathlib import Path
import time
import weakref

import numpy as np

from .imageops import resize_rgb
from .lakes import LAKES
from .platform import Text
from .pngsave import write_png
from .render import Renderer
from .sim import State
from .ui import UI, UIState
from .verify import MEMORY_LIMIT_BYTES, _finite_scene_check, rss_bytes
from .world import World


def _resident_bytes():
    return int(Path("/proc/self/statm").read_text().split()[1]) * os.sysconf("SC_PAGE_SIZE")


def shots(dest, *, software=False, lakes=None, frames=60):
    lakes = tuple(LAKES) if lakes is None else tuple(lakes)
    if not lakes or any(lake not in LAKES for lake in lakes) or frames < 60:
        raise ValueError("Choose known lakes and at least 60 warmed frames")
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    text, results = Text(), []
    live_maps = []
    try:
        for lake in lakes:
            gc.collect()
            if any(ref() is not None for ref in live_maps):
                raise AssertionError("Previous lake remains resident")
            world = World(lake)
            live_maps.append(weakref.ref(world))
            renderer = Renderer(world, 1280, 720, software=software)
            if not software and not hasattr(renderer, "scene_fb"):
                raise AssertionError("Native capture fell back to software")
            state, ui = State.new(world, seed=723), UI(text, world)
            state.v2["story"]["chapter"] = 5
            state.toasts.clear()
            state.game_minutes = 360
            panel = UIState(mode="play", has_save=True)

            def compose():
                low = renderer.render(state)
                big = resize_rgb(low, 1280, 720)
                ui.draw(big, state, panel)
                return big

            try:
                for minute, name in ((360, "day"), (900, "night")):
                    state.game_minutes = minute
                    state.light = minute == 900
                    write_png(out / f"{lake}-{name}.png", compose())
                state.game_minutes = 360
                panel.mode = "map"
                write_png(out / f"{lake}-chart.png", compose())
                if lake == "briar":
                    panel.mode, panel.shop_tab, panel.shop_i = "shop", 5, 2
                    state.v2["story"]["chapter"] = 0
                    write_png(out / "routes-locked.png", compose())
                    state.v2["story"]["chapter"] = 5
                    write_png(out / "routes-open.png", compose())
                native = hasattr(renderer, "scene_fb")
                if native:
                    _finite_scene_check(renderer, world)
                modes = ("play", "map", "shop")
                panel.shop_tab, panel.shop_i = 5, 0
                for index in range(9):
                    panel.mode = modes[index % len(modes)]
                    compose()
                resident_before = _resident_bytes()
                objects = len(renderer._objects) if native else 0
                times = []
                for index in range(frames):
                    panel.mode = modes[index % len(modes)]
                    state.anim = index / 30
                    start = time.perf_counter()
                    compose()
                    times.append((time.perf_counter() - start) * 1000)
                resident_after = _resident_bytes()
                if native and len(renderer._objects) != objects:
                    raise AssertionError("Frame loop grew persistent graphics resources")
                if rss_bytes() > MEMORY_LIMIT_BYTES:
                    raise AssertionError("Lake capture exceeded the 3 GB budget")
                results.append({"lake": lake, "placeholder": world.placeholder,
                                "backend": renderer.backend, "render_size": [renderer.w, renderer.h],
                                "presentation_size": [1280, 720], "frames": frames,
                                "median_ms": round(float(np.median(times)), 3),
                                "p95_ms": round(float(np.percentile(times, 95)), 3),
                                "rss_before_bytes": resident_before, "rss_after_bytes": resident_after,
                                "persistent_graphics_objects": objects, "finite_scene_probes": 4 if native else 0})
            finally:
                renderer.close()
                del compose, renderer, ui, state, world
            gc.collect()
        if any(ref() is not None for ref in live_maps):
            raise AssertionError("Closed lake capture retained its world")
    finally:
        text.close()
    result = {"scope": "Warmed full frames: lake render, resize and play/map/Lakes UI; one map at a time",
              "warmup_frames_per_lake": 9, "memory_limit_bytes": MEMORY_LIMIT_BYTES,
              "peak_rss_bytes": rss_bytes(), "maps_released": len(live_maps), "lakes": results}
    (out / "benchmark.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return result
