"""Measured landing controls for Bot's identity, earned shells and collar."""
from . import botidentity, kitchenview
from .data import BOT_COLLAR_STAGES, BOT_KNOTS


def draw(renderer, frame, state, ui):
    """Paint Bot stock into the RGB pixel frame through Kitchen's shared renderer.

    ``state`` supplies the profile and ``ui`` receives native row focus and
    measured tab/row pointer targets. Returns None; never purchases an item.
    """
    saved = botidentity.profile(state)
    collar = saved['collar']
    stage = BOT_COLLAR_STAGES.get(collar.get('stage'), 'Collar memory')
    knot = BOT_KNOTS.get(collar.get('knot'), '')
    meta = f'${state.money:.2f} · {stage}' + (' · ' + knot if knot else '')
    kitchenview.draw(renderer, frame, state, ui,
                     menu_rows=botidentity.rows(state, renderer.world),
                     menu_title=botidentity.name(state) + ' · Deckhand Unit 04', menu_meta=meta)


def bot_gallery(destination, *, text=None, world=None, background=None):
    """--shots identity matrix and bounded warmed menu benchmark."""
    from copy import deepcopy
    import json
    from pathlib import Path
    import resource
    import time
    import numpy as np
    from .data import BOT_TOOLS
    from .imageops import resize_rgb
    from .platform import Text
    from .pngsave import write_png
    from .sim import State
    from .ui import UI, UIState
    from .world import World

    own_text = text is None
    text = Text() if own_text else text
    world = World() if world is None else world
    out = Path(destination)
    out.mkdir(parents=True, exist_ok=True)
    fresh = State.new(world, seed=4517)
    fresh.toasts.clear()
    fresh.tutorial = 4
    earned = State.new(world, seed=4517)
    earned.tutorial, earned.finder, earned.money = 4, True, 2000
    earned.v2['story'].update(chapter=4, completed_chapters=[1, 2, 3], scene_states={'story_c4_knot': 'ready'})
    botidentity.sync_story_rewards(earned)
    botidentity.swap_shell(earned, world, 'frog')
    earned.toasts.clear()
    retied = deepcopy(earned, {id(world): world})
    botidentity.choose_knot(retied, 'bow')
    retied.toasts.clear()
    tools = deepcopy(retied, {id(world): world})
    for tool in ('sonar_grid', 'reed_anchor', 'wave_chime', 'thermo_scanner'):
        botidentity.buy_tool(tools, world, tool)
    ending = deepcopy(tools, {id(world): world})
    ending.v2['story']['scene_states']['end_02'] = 'done'
    panels = (
        ('save-slot', fresh, UIState(mode='title', has_save=True)),
        ('first-shell', fresh, UIState(mode='shop', shop_tab=7)),
        ('earned-shells', earned, UIState(mode='shop', shop_tab=7, shop_i=3)),
        ('tools', tools, UIState(mode='shop', shop_tab=7, shop_i=7)),
        ('knot', retied, UIState(mode='shop', shop_tab=7, shop_i=11)),
        ('book-author', ending, UIState(mode='journal')),
    )
    painter = UI(text, world)
    def paint(state, panel, width=1280, height=720):
        frame = (resize_rgb(background, width, height).copy() if background is not None
                 else np.full((height, width, 3), (48, 79, 87), np.uint8))
        painter.draw(frame, state, panel)
        return frame
    contact = []
    try:
        for width, height, size, font, suffix in ((1280, 720, 1, False, 'standard'),
                                                (1280, 720, 2, True, 'accessible'),
                                                (480, 270, 2, True, 'compact-accessible')):
            for label, state, panel in panels:
                state.v2['settings'].update(text_size=size, dyslexia_font=font)
                frame = paint(state, panel, width, height)
                write_png(out / f'bot-{label}-{suffix}.png', frame)
                if suffix == 'standard':
                    contact.append(resize_rgb(frame, 640, 360))
        write_png(out / 'bot-identity-contact-sheet.png', np.concatenate([
            np.concatenate(contact[i:i+2], axis=1) for i in range(0, len(contact), 2)]))
        timings = []
        for index in range(150):
            _label, state, panel = panels[1 + index % 4]
            state.v2['settings'].update(text_size=2, dyslexia_font=True)
            start = time.perf_counter()
            paint(state, panel)
            if index >= 10:
                timings.append((time.perf_counter()-start)*1000)
        report = dict(frames=len(timings), resolution=[1280, 720], text_size=2, accessibility_font=True,
                      p50_ms=round(float(np.percentile(timings, 50)), 2), p95_ms=round(float(np.percentile(timings, 95)), 2),
                      peak_rss_mib=round(__import__("fishing.verify", fromlist=["rss_bytes"]).rss_bytes()/1024**2, 1),
                      text_cache_mb=round(text.cache_bytes/1e6, 2),
                      scope='Warmed Bot shell/tool/collar menu composition; excludes lake rendering')
        (out / 'bot-identity-benchmark.json').write_text(json.dumps(report, indent=2)+'\n')
        print('Bot identity shots / benchmark: ' + json.dumps(report))
        return report
    finally:
        if own_text:
            text.close()
