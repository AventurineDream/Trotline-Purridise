"""Nebula bands, aurora, currents, habitats and the starlight transition.

python -m fishing --shots docs/issue-55/native --nebula [--software]
"""

from __future__ import annotations

import gc
import json
import math
import os
from pathlib import Path
import time
import weakref

import numpy as np

from .bottools import flow_at
from .calendar import weather_at
from .camera import Camera
from .imageops import resize_rgb
from .nebula import band_label
from .platform import Text
from .pngsave import write_png
from .render import Renderer
from .sim import State
from .software import FOV
from .specieschecks import lake_witnesses
from . import starlight
from .data import hour_of_day
from .ui import UI, UIState
from .verify import MEMORY_LIMIT_BYTES, rss_bytes
from .weather import lighting_at
from .world import World

OVERLOOK = (-300.0, -160.0, 0.9)
BANDS = (("rising", 30), ("bright", 360), ("fading", 750), ("deep", 1200))


def resident_bytes():
    return int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')


def calm_minute(state, offset, days=range(7)):
    """The first day whose forecast at this clock offset is clear or fair."""
    for day in days:
        minute = day*1440+offset
        if day % 7 != 5 and weather_at(state, minute) in ('clear', 'fair'):
            return minute
    return offset


def _lane_point(world, index):
    lane = [row for row in world.zones if row[0] == 'current']
    return lane[index][1], lane[index][2]


def _hide_boat(renderer):
    """Top-down probes look at open water only; the cockpit would fill the lens."""
    import fishing.bot as bot
    original_bot = bot.faces
    if hasattr(renderer, 'scene_fb'):
        renderer._boat_vertices = lambda state, cam: np.zeros((3, 10), np.float32)
    else:
        renderer._boat_faces = lambda state: []
    bot.faces = lambda state: []

    def restore():
        bot.faces = original_bot
        for name in ('_boat_vertices', '_boat_faces'):
            renderer.__dict__.pop(name, None)
    return restore


def flow_alignment(renderer, world, state, lanes=(4, 8, 12, 16, 20), height=18.0, pitch=-1.15):
    """Angle between the rendered current streaks and `bottools.flow_at`.

    The camera looks down steeply over a lane at night. The structure tensor of
    the bright streaks in the far half of the frame gives their axis, which is
    compared with the flow axis at the centre of that region, foreshortened by
    the view. Returns one row per lane point.
    """
    native = hasattr(renderer, 'scene_fb')
    restore = _hide_boat(renderer)
    rows = []
    try:
        for k in lanes:
            x, z = _lane_point(world, k)
            yaw = 0.3*k
            state.x, state.z, state.yaw = x, z, yaw
            cam = Camera(x, height, z, yaw, pitch, 0.0, FOV, renderer.w, renderer.h, build_rays=not native)
            img = renderer.render(state, cam).astype(np.float32).mean(axis=2)
            top = np.clip(img[:int(renderer.h*.55)]-np.median(img[:int(renderer.h*.55)]), 0, None)
            gy, gx = np.gradient(top)
            jxx, jyy, jxy = float((gx*gx).sum()), float((gy*gy).sum()), float((gx*gy).sum())
            streak = .5*math.atan2(2*jxy, jxx-jyy)+math.pi/2
            coherence = math.sqrt((jxx-jyy)**2+4*jxy**2)/(jxx+jyy+1e-9)
            ray = pitch+math.atan(renderer.h/renderer.w*math.tan(FOV/2)*.45)
            reach = height/math.tan(-ray)
            fx, fz = flow_at(x+math.sin(yaw)*reach, z+math.cos(yaw)*reach)
            u = fx*math.cos(yaw)-fz*math.sin(yaw)
            v = fx*math.sin(yaw)+fz*math.cos(yaw)
            expected = math.atan2(-v*math.sin(-ray), u)
            error = abs((streak-expected+math.pi/2) % math.pi-math.pi/2)
            rows.append(dict(lane_point=k, x=round(x, 1), z=round(z, 1),
                             angle_error_deg=round(math.degrees(error), 2), coherence=round(coherence, 3)))
    finally:
        restore()
    return rows


def flow_figure(renderer, world, state):
    """A steep view over the main lane with the flow field drawn as arrows."""
    native = hasattr(renderer, 'scene_fb')
    restore = _hide_boat(renderer)
    try:
        x, z = _lane_point(world, 8)
        yaw, height, pitch = 1.2, 30.0, -1.25
        state.x, state.z, state.yaw = x, z, yaw
        cam = Camera(x, height, z, yaw, pitch, 0.0, FOV, renderer.w, renderer.h, build_rays=not native)
        frame = renderer.render(state, cam)
    finally:
        restore()
    frame = resize_rgb(frame, 1280, 720)
    scale = 1280/cam.w
    for gx in np.linspace(x-60, x+60, 13):
        for gz in np.linspace(z-60, z+60, 13):
            fx, fz = flow_at(gx, gz)
            n = math.hypot(fx, fz)
            a = cam.project_world(gx, 0.0, gz)
            b = cam.project_world(gx+fx/n*3.0, 0.0, gz+fz/n*3.0)
            if a is None or b is None:
                continue
            (ax, ay, _), (bx, by, _) = a, b
            for t in np.linspace(0, 1, 24):
                px, py = int((ax+(bx-ax)*t)*scale), int((ay+(by-ay)*t)*scale)
                if 1 <= px < 1279 and 1 <= py < 719:
                    frame[py-1:py+1, px-1:px+1] = (255, 214, 120) if t > .7 else (255, 170, 60)
    return frame


def finite_band_check(renderer, world):
    """Every band and the aurora stay finite in the float scene pass."""
    original = renderer.draw_fb
    with renderer.ctx:
        color = renderer.ctx.texture((renderer.w, renderer.h), 3, dtype='f4')
        depth = renderer.ctx.depth_renderbuffer((renderer.w, renderer.h))
        target = renderer.ctx.framebuffer([color], depth)
    probes = 0
    try:
        renderer.draw_fb = target
        state = State.new(world, seed=4)
        x, z = _lane_point(world, 8)
        for minute in (30, 360, 750, 900, 1200):
            for speed in (0.0, 2.0):
                state.game_minutes, state.speed = minute, speed
                state.x, state.z, state.yaw = x, z, 1.5
                with renderer.ctx:
                    renderer.render(state)
                with renderer.ctx:
                    pixels = np.frombuffer(target.read(components=3, dtype='f4', alignment=1), np.float32)
                if not np.isfinite(pixels).all() or float(pixels.max()) < .05:
                    raise AssertionError(f'Non-finite Nebula scene at minute {minute}')
                probes += 1
    finally:
        renderer.draw_fb = original
        with renderer.ctx:
            target.release()
            depth.release()
            color.release()
    return probes


def transition_strips(source, arrival):
    """Six steps of the tip into starlight, with the Reduced Motion crossfade below."""
    sheet = np.zeros((2*180, 6*320, 3), np.uint8)
    for row, reduced in enumerate((False, True)):
        for i, t in enumerate(np.linspace(0, 1, 6)):
            frame = starlight.frame(source, arrival, float(t), reduced_motion=reduced)
            sheet[row*180:(row+1)*180, i*320:(i+1)*320] = resize_rgb(frame, 320, 180)
    return sheet


def shots(dest, *, software=False, frames=60):
    if frames < 60:
        raise ValueError('Use at least 60 warmed full frames')
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    baseline = resident_bytes()
    text = Text()
    # The transition starts from Crater's still clear night, where the way is found.
    crater = World('crater')
    renderer = Renderer(crater, 1280, 720, software=software)
    state = State.new(crater, seed=4)
    state.toasts.clear()
    state.game_minutes, state.anim = 4*1440+960, 14
    state.x, state.z, state.yaw = -230, 40, 1.828
    source = resize_rgb(renderer.render(state), 1280, 720)
    renderer.close()
    del renderer, state, crater
    gc.collect()
    begin = time.perf_counter()
    world = World('nebula')
    world_ms = (time.perf_counter()-begin)*1000
    renderer = Renderer(world, 1280, 720, software=software)
    state = State.new(world, seed=4)
    renderer.render(state)
    loaded_ms = (time.perf_counter()-begin)*1000
    native = hasattr(renderer, 'scene_fb')
    if not software and not native:
        raise AssertionError('Native Nebula capture fell back to CPU')
    ui = UI(text, world)
    panel = UIState(mode='play', has_save=True)
    state.toasts.clear()
    thumbs, captures = [], []
    try:
        def compose():
            frame = resize_rgb(renderer.render(state), 1280, 720)
            ui.draw(frame, state, panel)
            return frame

        def capture(name, minute, pose, look=0.0, title=None, anim=14):
            state.game_minutes = minute
            state.x, state.z, state.yaw = pose
            state.look, state.anim, state.light = look, anim, False
            if not world.hull_clear(state.x, state.z, state.yaw, state.boat_id):
                raise AssertionError('Capture pose is not navigable: '+name)
            frame = compose()
            write_png(out/(name+'.png'), frame)
            thumb = resize_rgb(frame, 480, 270)
            ui._text(thumb, title or name.replace('-', ' ').title(), 10, 10, 13, (255, 236, 180))
            thumbs.append(thumb)
            light = lighting_at(minute, state)
            captures.append(dict(name=name, minute=minute, pose=[round(v, 3) for v in pose],
                                 band=band_label(hour_of_day(minute)), weather=weather_at(state, minute),
                                 starlight=round(float(light.get('starlight', 0)), 3),
                                 aurora=round(float(light.get('aurora', 0)), 3),
                                 meteors=round(float(light.get('meteors', 0)), 3)))
            return frame

        for name, offset in BANDS:
            capture(name, calm_minute(state, offset), OVERLOOK, title=name.title()+' band')
        capture('aurora', 900, OVERLOOK)
        if captures[-1]['weather'] != 'aurora' or captures[-1]['aurora'] < 1:
            raise AssertionError('The aurora capture must use a real aurora night')
        capture('meteor-shower', 2*1440+1170, OVERLOOK, look=.12, anim=16.5)
        if captures[-1]['meteors'] < 1:
            raise AssertionError('The meteor capture must fall on a Meteor Shower night')
        lx, lz = _lane_point(world, 7)
        tx, tz = _lane_point(world, 10)
        capture('astral-current', 1200, (lx, lz, math.atan2(tx-lx, tz-lz)), look=-.18)
        zones = {row[0]: row[1:] for row in world.environment['zones']}
        kx, kz, _ = zones['cypress']
        capture('crystal-kelp', 1200, (kx, kz, .4), look=-.02)
        mx, mz, _ = zones['rocks']
        capture('meteor-reefs', 1200, (mx, mz+40, math.pi), look=-.06)
        rx, rz, _ = zones['reeds']
        capture('light-reeds', 1200, (rx, rz+70, math.pi), look=-.06)
        capture('lily-drifts', 750, (318, -62, math.atan2(350-318, -95+62)), look=-.05)
        px, pz = world.slip.world(-34, 0)
        capture('cosmic-drift-station', 1200, (px, pz, math.atan2(world.slip.ix, world.slip.iz)))
        panel.mode = 'map'
        capture('habitat-chart', 360, OVERLOOK)
        panel.mode = 'play'
        sheet = np.zeros((4*270, 4*480, 3), np.uint8)
        for i, thumb in enumerate(thumbs[:16]):
            sheet[(i//4)*270:(i//4+1)*270, (i % 4)*480:(i % 4+1)*480] = thumb
        write_png(out/'contact-sheet.png', sheet)
        del sheet, thumbs
        state.game_minutes, state.anim = 1200, 14
        alignment = flow_alignment(renderer, world, state)
        if max(row['angle_error_deg'] for row in alignment) > 20:
            raise AssertionError('Rendered currents do not follow the flow field')
        write_png(out/'current-flow.png', flow_figure(renderer, world, state))
        state.game_minutes, state.look = 360, 0.0
        state._park(world)
        arrival = resize_rgb(renderer.render(state), 1280, 720)
        write_png(out/'starlight-transition.png', transition_strips(source, arrival))
        probes = finite_band_check(renderer, world) if native else 0
        witnesses = lake_witnesses(world)
        (out/'catchability.json').write_text(json.dumps(witnesses, indent=2)+'\n')
        state.x, state.z, state.yaw = OVERLOOK
        modes = ('play', 'map', 'shop')
        panel.shop_tab, panel.shop_i = 5, 0
        for index in range(9):
            panel.mode = modes[index % 3]
            compose()
        before = resident_bytes()
        objects = len(renderer._objects) if native else 0
        times = []
        for index in range(frames):
            state.game_minutes = (30, 360, 750, 900, 1200)[index % 5]
            state.anim = index/30
            panel.mode = modes[index % 3]
            start = time.perf_counter()
            compose()
            times.append((time.perf_counter()-start)*1000)
        after = resident_bytes()
        if native and len(renderer._objects) != objects:
            raise AssertionError('Nebula frames grew persistent graphics objects')
        if rss_bytes() > MEMORY_LIMIT_BYTES:
            raise AssertionError('Nebula capture exceeded the 3 GB budget')
        if loaded_ms > 6000:
            raise AssertionError('Local Nebula load through first frame exceeded six seconds')
        result = dict(backend=renderer.backend, software_gl=bool(getattr(renderer, 'software_gl', False)),
                      hardware_gpu_measured=native and not getattr(renderer, 'software_gl', False),
                      render_size=[renderer.w, renderer.h], presentation_size=[1280, 720],
                      world_load_ms=round(world_ms, 3), first_frame_load_ms=round(loaded_ms, 3),
                      load_limit_ms=6000,
                      scope='Warmed full Nebula frames, resize and play/map/Lakes UI; all four bands and aurora',
                      frames=frames, warmup_frames=9, median_ms=round(float(np.median(times)), 3),
                      p95_ms=round(float(np.percentile(times, 95)), 3), rss_baseline_bytes=baseline,
                      rss_before_bytes=before, rss_after_bytes=after, peak_rss_bytes=rss_bytes(),
                      memory_limit_bytes=MEMORY_LIMIT_BYTES, persistent_graphics_objects=objects,
                      finite_scene_probes=probes, species_witnesses=len(witnesses),
                      minimum_rate_ratio=min(row['ratio'] for row in witnesses),
                      flow_alignment=alignment,
                      max_flow_angle_error_deg=max(row['angle_error_deg'] for row in alignment),
                      captures=captures)
    finally:
        renderer.close()
        text.close()
    ref = weakref.ref(world)
    del compose, capture, renderer, ui, state, world
    gc.collect()
    if ref() is not None:
        raise AssertionError('Closed Nebula capture retained its map')
    result['world_released'] = True
    (out/'benchmark.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({key: value for key, value in result.items() if key not in ('captures', 'flow_alignment')},
                     indent=2))
    return result
