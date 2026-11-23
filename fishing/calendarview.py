"""Calendar --shots fixtures and a bounded, warmed UI benchmark."""
def calendar_gallery(destination, *, text=None, world=None, background=None):
    """Write calendar panels and UI timings to `destination`; reuse supplied render resources."""
    import json
    from pathlib import Path
    import resource
    import time
    import numpy as np
    from . import calendar
    from .imageops import resize_rgb
    from .platform import Text
    from .pngsave import write_png
    from .sim import Catch, State
    from .ui import UI, UIState
    from .world import World

    own_text = text is None
    text = Text() if own_text else text
    world = World() if world is None else world
    out = Path(destination)
    out.mkdir(parents=True, exist_ok=True)
    state = State.new(world, seed=44016)
    state.game_minutes = 660
    state.well = [Catch('bluegill', .9, 1, 0, 'flats', 'worm', 17),
                  Catch('gar', 3., 1, 0, 'open', 'minnow', 17)]
    state.toasts.clear()
    state.tutorial = 4
    painter = UI(text, world)
    panels = (
        ('week', UIState(mode='journal', journal_page=5, book_week_i=2)),
        ('sunday', UIState(mode='journal', journal_page=5, book_week_i=0)),
        ('cookout', UIState(mode='kitchen')),
        ('share', UIState(mode='cook_confirm', cook_kind='cookout', cook_label='Sunday landing cookout')),
    )
    def paint(panel, width=1280, height=720):
        frame = (resize_rgb(background, width, height).copy() if background is not None
                 else np.full((height, width, 3), (48, 79, 87), np.uint8))
        painter.draw(frame, state, panel)
        return frame
    contact = []
    try:
        for width, height, size, font, suffix in ((1280, 720, 1, False, 'standard'),
                                                (1280, 720, 2, True, 'accessible'),
                                                (480, 270, 2, True, 'compact-accessible')):
            state.v2['settings'].update(text_size=size, dyslexia_font=font)
            for name, panel in panels:
                panel.book_detail_page = 0
                frame = paint(panel, width, height)
                write_png(out / f'calendar-{name}-{suffix}.png', frame)
                if suffix == 'standard':
                    contact.append(resize_rgb(frame, 640, 360))
        write_png(out / 'calendar-contact-sheet.png', np.concatenate([
            np.concatenate(contact[:2], axis=1), np.concatenate(contact[2:], axis=1)]))
        state.v2['settings'].update(text_size=2, dyslexia_font=True)
        timings = []
        for index in range(150):
            start = time.perf_counter()
            paint(panels[index % len(panels)][1])
            if index >= 10:
                timings.append((time.perf_counter()-start)*1000)
        report = dict(frames=len(timings), resolution=[1280, 720], text_size=2, accessibility_font=True,
                      p50_ms=round(float(np.percentile(timings, 50)), 2),
                      p95_ms=round(float(np.percentile(timings, 95)), 2),
                      peak_rss_mib=round(__import__("fishing.verify", fromlist=["rss_bytes"]).rss_bytes()/1024**2, 1),
                      text_cache_mb=round(text.cache_bytes/1e6, 2),
                      scope='Warmed week view and cookout UI composition; excludes lake rendering')
        (out / 'calendar-benchmark.json').write_text(json.dumps(report, indent=2)+'\n')
        print('calendar shots / benchmark: ' + json.dumps(report))
        return report
    finally:
        if own_text:
            text.close()
