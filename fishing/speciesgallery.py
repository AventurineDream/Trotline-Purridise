"""Species-data captures: all cards, new Book pages, stock and flat-water chart."""

import json
from pathlib import Path
import time

import numpy as np

from .bookview import ENTRY_IDS
from .data import SPECIES_BY_ID
from .fishmesh import cache_bytes, clear_caches, fish_card_contact_sheet
from .imageops import resize_rgb
from .platform import Text
from .pngsave import write_png
from .render import Renderer
from .sim import Catch, State
from .ui import UI, UIState
from .verify import MEMORY_LIMIT_BYTES, rss_bytes
from .world import World


def gallery(dest, *, software=False):
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    clear_caches()
    world = World('flathead')
    renderer = Renderer(world, 1280, 720, software=software)
    native = hasattr(renderer, 'scene_fb')
    if not software and not native:
        renderer.close()
        raise AssertionError('Native species capture fell back to software')
    text, state = Text(), State.new(world, seed=724)
    state.v2['story']['chapter'] = 5
    state.game_minutes = 360
    state.toasts.clear()
    ui = UI(text, world)
    ui.fish_card_renderer = getattr(renderer, 'fish_card', None)
    try:
        start = time.perf_counter()
        sheet = fish_card_contact_sheet(ui.fish_card_renderer)
        for index, page in enumerate(np.array_split(sheet, 2)):
            write_png(out / f'field-and-shiny-page-{index+1}.png', page)
        (out / 'all-144-field-and-shiny.png').unlink(missing_ok=True)
        contact_ms = (time.perf_counter()-start)*1000
        panels = []
        for sid, count, name in (('lake_trout', 0, 'trout-rumor'),
                                 ('glasswing_trout', 5, 'glasswing-verified'),
                                 ('bull_trout', 1, 'protected-trout'),
                                 ('comet_tail_betta', 5, 'nebula-verified')):
            fish = SPECIES_BY_ID[sid]
            for _ in range(count):
                state._note_journal(Catch(sid, fish.min_lb, 1, 0, fish.zones[0], fish.baits[0],
                                          12, lake_id=fish.lakes[0], depth_m=sum(fish.depth)/2))
            panel = UIState(mode='journal', journal_page=1, book_entry_i=ENTRY_IDS.index(sid))
            panels.append(panel)
            frame = resize_rgb(renderer.render(state), 1280, 720)
            ui.draw(frame, state, panel)
            write_png(out / (name + '.png'), frame)
        panels += [UIState(mode='shop', shop_tab=1, shop_i=6), UIState(mode='map')]
        for name, panel in zip(('roe-stock', 'flathead-soundings'), panels[-2:]):
            frame = resize_rgb(renderer.render(state), 1280, 720)
            ui.draw(frame, state, panel)
            write_png(out / (name + '.png'), frame)
        for index in range(12):
            frame = resize_rgb(renderer.render(state), 1280, 720)
            ui.draw(frame, state, panels[index % len(panels)])
        objects = len(renderer._objects) if native else 0
        times = []
        for index in range(60):
            start = time.perf_counter()
            frame = resize_rgb(renderer.render(state), 1280, 720)
            ui.draw(frame, state, panels[index % len(panels)])
            times.append((time.perf_counter()-start)*1000)
        if native and len(renderer._objects) != objects:
            raise AssertionError('Species pages grew persistent graphics resources')
        if rss_bytes() >= MEMORY_LIMIT_BYTES:
            raise AssertionError('Species gallery exceeded 3 GB')
        result = dict(backend=renderer.backend, render_size=[renderer.w, renderer.h],
                      presentation_size=[1280, 720], species=144, card_variants=288,
                      contact_sheet_ms=round(contact_ms, 3), frames=60, warmup_frames=12,
                      median_ms=round(float(np.median(times)), 3), p95_ms=round(float(np.percentile(times, 95)), 3),
                      peak_rss_bytes=rss_bytes(), memory_limit_bytes=MEMORY_LIMIT_BYTES,
                      cpu_card_cache_bytes=cache_bytes(), persistent_graphics_objects=objects,
                      scope='All normal/shiny cards, then warmed full lake/resize/new Book, stock and chart frames')
        (out / 'benchmark.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, indent=2))
        return result
    finally:
        text.close()
        renderer.close()
        clear_caches()
