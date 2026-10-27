"""Measured, scrolling pantry menus and the quiet cooking vignette."""

from . import comfort, kitchen
from .data import BAIT_BY_ID, BAIT_RECIPES, DISHES, PANTRY, SPECIES_BY_ID


def draw(renderer, frame, state, ui):
    from .ui import DIM, GOLD, INK, WARN, comfort_controls
    h, w = frame.shape[:2]
    x = y = 12
    width, height = w - 24, h - 24
    renderer._round_fill(frame, x, y, width, height, (17, 31, 32), 1)
    head, body, small = (renderer._size(frame, key) for key in ('head', 'body', 'small'))
    def text(value, tx, ty, size, color=INK):
        renderer._text(frame, value, tx, ty, size, color, False, 'sans')
    def trim(value, size, available):
        if renderer._measure(value, size) <= available:
            return value
        while value and renderer._measure(value + '…', size) > available:
            value = value[:-1]
        return value + '…'
    title = 'Kitchen' if ui.mode == 'shop' else 'Pantry & galley'
    if ui.mode in ('cook_confirm', 'cooking'):
        title = ui.cook_label
    while head > 10 and renderer._measure(title, head) > width - 32:
        head -= 1
    text(title, x + 16, y + 12, head)
    top = y + 24 + renderer._render(title, head, INK, 'sans').shape[0]
    if ui.mode in ('cook_confirm', 'cooking'):
        if ui.mode == 'cook_confirm':
            if ui.cook_kind == 'dish':
                dish = DISHES[ui.cook_arg]
                candidates = kitchen.eligible_fish(state, dish.food)
                fish = state.well[candidates[ui.cook_fish % len(candidates)]] if candidates else None
                picked = (f'{fish.weight:.1f} lb {SPECIES_BY_ID[fish.species].name}' if fish else 'No eligible fish')
                message = f'Use {picked} + one {PANTRY[dish.ingredient].name}.\n{dish.blurb}'
                message += '\nUp / Down chooses a fish.' if ui.input_device != 'gamepad' else '\nD-pad Up / Down chooses a fish.'
            else:
                recipe = BAIT_RECIPES[ui.cook_arg]
                ingredients = ' + '.join('one ' + BAIT_BY_ID[parent].name for parent in recipe.parents)
                message = f'{ingredients} + one {PANTRY[recipe.ingredient].name} makes twelve {BAIT_BY_ID[ui.cook_arg].name}.'
            buff = comfort.active_buff(state)
            if ui.cook_kind == 'dish' and buff:
                message += '\nReplaces ' + buff.name + '.'
            message += '\n' + renderer._controls(ui, 'Left / Right · Enter confirms · Esc back',
                                                  'Left / Right · A confirms · B back')
            if ui.note:
                message = ui.note + '\n' + message
        else:
            message = ui.cook_text + '\nAny key or click finishes the scene.'
            # A bowl and three gentle steam trails; reduced motion keeps them still.
            import math
            phase = 0.0 if state.v2['settings'].get('reduced_motion') else 2.0 - ui.cook_timer
            cx, cy = w // 2, int(h * .72)
            bowl_w, bowl_h = max(64, w // 8), max(24, h // 18)
            renderer._round_fill(frame, cx - bowl_w // 2, cy, bowl_w, bowl_h, (199, 165, 104), 1)
            renderer._fill(frame, cx - bowl_w // 2 + 5, cy + 3, bowl_w - 10, 4, GOLD, 1)
            for strand in range(3):
                for step in range(8):
                    sx = cx + (strand - 1) * 16 + int(math.sin(phase + step * .5 + strand) * 3)
                    renderer._fill(frame, sx, cy - 5 - step * 3, 2, 2, DIM, .65)
        buttons = comfort_controls((w, h))
        limit = buttons[0][1] - 10 if ui.mode == 'cook_confirm' else int(h * .53)
        size = body
        while size > 9:
            lines, line_h = renderer._comfort_lines(message, size, width - 32)
            if len(lines) * line_h <= limit - top:
                break
            size -= 1
        lines, line_h = renderer._comfort_lines(message, size, width - 32)
        for index, line in enumerate(lines):
            text(line, x + 16, top + index * line_h, size, DIM)
        if ui.mode == 'cook_confirm':
            for index, (label, box) in enumerate(zip(('Cook', 'Back'), buttons)):
                bx, by, bw, bh = box
                renderer._round_fill(frame, bx, by, bw, bh, GOLD if index == ui.comfort_i else (46, 66, 62), 1)
                glyph_h = renderer._render(label, body, INK, 'sans').shape[0]
                renderer._center(frame, label, bx + bw / 2, by + (bh - glyph_h) / 2, body,
                                 (22, 39, 39) if index == ui.comfort_i else INK)
        return
    buff = comfort.active_buff(state)
    meta = f'${state.money:.2f} · ' + (buff.name if buff else 'No picnic buff')
    rows = kitchen.rows(state, renderer.world)
    count = f'{ui.shop_i % len(rows) + 1} / {len(rows)}'
    count_w = renderer._measure(count, small)
    text(trim(meta, small, width - count_w - 48), x + 16, top, small, GOLD)
    text(count, x + width - 16 - count_w, top, small, DIM)
    top += renderer._render(meta, small, INK, 'sans').shape[0] + 10
    ui.shop_i %= max(1, len(rows))
    foot = renderer._controls(ui, 'Up / Down choose · Enter selects · Esc back',
                              'D-pad chooses · A selects · B back')
    if ui.mode == 'shop':
        foot = renderer._controls(ui, 'Up / Down choose · A/D tabs · Enter · Esc',
                                  'Up / Down choose · Left / Right tabs · A · B')
    foot_lines, foot_h = renderer._comfort_lines(foot, small, width - 32)
    foot_y = h - 24 - len(foot_lines) * foot_h
    detail_h = min(104, max(48, int(h * .22)))
    list_bottom = foot_y - detail_h - 12
    row_h = renderer._render('Mg', body, INK, 'sans').shape[0] + 8
    visible = max(1, (list_bottom - top) // row_h)
    start = max(0, min(ui.shop_i - visible // 2, len(rows) - visible))
    ui.kitchen_hitboxes = []
    for offset, row in enumerate(rows[start:start + visible]):
        index, ry = start + offset, top + offset * row_h
        chosen = index == ui.shop_i
        if chosen:
            renderer._round_fill(frame, x + 8, ry - 2, width - 16, row_h, (46, 66, 62), 1)
        color = GOLD if chosen else INK if row.enabled else DIM
        right_w = renderer._measure(row.right, body)
        label = trim(row.label, body, width - right_w - 56)
        text(label, x + 16, ry, body, color)
        text(row.right, x + width - 16 - right_w, ry, body, color)
        ui.kitchen_hitboxes.append((index, (x + 8, ry - 2, width - 16, row_h)))
    selected = rows[ui.shop_i]
    detail = ui.note or selected.label + '. ' + selected.blurb
    lines, line_h = renderer._comfort_lines(detail, small, width - 32)
    maximum = max(1, detail_h // line_h)
    if len(lines) > maximum:
        lines = (*lines[:maximum - 1], trim(' '.join(lines[maximum - 1:]), small, width - 32))
    for index, line in enumerate(lines):
        text(line, x + 16, list_bottom + 8 + index * line_h, small, WARN if ui.note else DIM)
    for index, line in enumerate(foot_lines):
        text(line, x + 16, foot_y + index * foot_h, small, DIM)


def kitchen_gallery(destination, *, text=None, world=None, background=None):
    """--shots fixtures and warmed kitchen UI composition timings."""
    import json
    from pathlib import Path
    import resource
    import time
    import numpy as np
    from .data import BAIT_RECIPES
    from .imageops import resize_rgb
    from .platform import Text
    from .pngsave import write_png
    from .sim import Catch, Hook, SetLine, State
    from .software import SoftwareRenderer
    from .ui import UI, UIState
    from .world import World

    own_text = text is None
    text = Text() if own_text else text
    world = World() if world is None else world
    out = Path(destination)
    out.mkdir(parents=True, exist_ok=True)
    state = State.new(world, seed=43015)
    state.money = 600
    state.v2['dishes_known'] = list(DISHES)
    state.v2['recipes'] = list(BAIT_RECIPES)
    state.v2['pantry'] = {item: 4 for item in PANTRY}
    state.bait.update({bait: 1 for recipe in BAIT_RECIPES.values() for bait in recipe.parents})
    state.well = [Catch('bluegill', .9, 1, 0, 'flats', 'worm', 8),
                  Catch('bluegill', 2, 1, 0, 'flats', 'worm', 8)]
    comfort.serve_dish(state, DISHES['pecan_chowder'])
    state.toasts.clear()
    state.tutorial = 4
    dish_row = next(i for i, row in enumerate(kitchen.rows(state, world)) if row.arg == 'pan_fritters')
    panels = (
        ('landing-pantry', UIState(mode='shop', shop_tab=6)),
        ('dish-menu', UIState(mode='kitchen', shop_i=dish_row)),
        ('fish-choice', UIState(mode='cook_confirm', cook_kind='dish', cook_arg='pan_fritters',
                                cook_label='Sunny Pan Fritters', cook_fish=1,
                                caption='A soft click sounds.', caption_timer=1)),
        ('recipe-bait', UIState(mode='cook_confirm', cook_kind='recipe', cook_arg='lantern_liver',
                                cook_label='Lantern Liver', caption='A soft click sounds.', caption_timer=1)),
        ('cooking', UIState(mode='cooking', cook_label='Sunny Pan Fritters', cook_timer=1,
                            cook_text=DISHES['pan_fritters'].blurb)),
        ('snack', UIState(mode='kitchen')),
    )
    painter = UI(text, world)
    def paint(panel, width, height):
        frame = (resize_rgb(background, width, height).copy() if background is not None
                 else np.full((height, width, 3), (48, 79, 87), np.uint8))
        painter.draw(frame, state, panel)
        return frame
    contact = []
    software = None
    try:
        for width, height, size, font, suffix in ((1280, 720, 1, False, 'standard'),
                                                 (1280, 720, 2, True, 'accessible'),
                                                 (480, 270, 2, True, 'compact-accessible')):
            state.v2['settings'].update({'text_size': size, 'dyslexia_font': font})
            for name, panel in panels:
                frame = paint(panel, width, height)
                write_png(out / f'kitchen-{name}-{suffix}.png', frame)
                if suffix == 'standard':
                    contact.append(resize_rgb(frame, 640, 360))
        write_png(out / 'kitchen-contact-sheet.png', np.concatenate([
            np.concatenate(contact[i:i+2], axis=1) for i in range(0, len(contact), 2)]))
        state.v2['settings'].update({'text_size': 2, 'dyslexia_font': True})
        timings = []
        for i in range(150):
            start = time.perf_counter()
            paint(panels[i % len(panels)][1], 1280, 720)
            if i >= 10:
                timings.append((time.perf_counter() - start) * 1000)
        report = {'frames': len(timings), 'resolution': [1280, 720],
                  'p50_ms': round(float(np.percentile(timings, 50)), 2),
                  'p95_ms': round(float(np.percentile(timings, 95)), 2),
                  'text_size': 2, 'accessibility_font': True,
                  'peak_rss_mib': round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
                  'text_cache_mb': round(text.cache_bytes / 1e6, 2),
                  'scope': 'Warmed kitchen UI composition, including scrolling lists, fish confirmation and steam; excludes lake rendering'}
        (out / 'kitchen-benchmark.json').write_text(json.dumps(report, indent=2) + '\n')
        software = SoftwareRenderer(world, 480, 270)
        state.v2['buff'] = None
        state.game_minutes = 1080
        fx, fz = np.sin(state.yaw), np.cos(state.yaw)
        state.lines = [SetLine('std', 'worm', state.x + fx * 18, state.z + fz * 18,
                               state.x + fx * 30, state.z + fz * 30, 'open', [Hook(True)])]
        normal = software.render(state).copy()
        comfort.serve_dish(state, DISHES['starlight_soup'])
        glowing = software.render(state).copy()
        write_png(out / 'kitchen-glow-comparison.png', np.concatenate((normal, glowing), axis=1))
        state.game_minutes, state.v2['buff'] = 0, None
        normal = software.render(state).copy()
        comfort.serve_dish(state, DISHES['mineral_broth'])
        clearer = software.render(state).copy()
        write_png(out / 'kitchen-fog-comparison.png', np.concatenate((normal, clearer), axis=1))
        print('kitchen shots / benchmark: ' + json.dumps(report))
        return report
    finally:
        if software is not None:
            software.close()
        if own_text:
            text.close()
