"""Caldera fog, island, springs and sky reflection with full-frame evidence.

python -m fishing --shots docs/issue-54/native --caldera [--software]
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

from .calendar import weather_at
from .caldera import reflection_strength
from .imageops import resize_rgb
from .platform import Text
from .pngsave import write_png
from .render import Renderer
from .sim import State
from .specieschecks import lake_witnesses
from .ui import UI, UIState
from .verify import MEMORY_LIMIT_BYTES, _finite_scene_check, rss_bytes
from .weather import lighting_at
from .world import World


def resident_bytes():
    return int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')


def finite_night_check(renderer, world):
    """Probe the real calm-night branch before RGB8 can hide shader NaNs."""
    original = renderer.draw_fb
    with renderer.ctx:
        color = renderer.ctx.texture((renderer.w,renderer.h),3,dtype="f4")
        depth = renderer.ctx.depth_renderbuffer((renderer.w,renderer.h))
        target = renderer.ctx.framebuffer([color],depth)
    try:
        renderer.draw_fb = target
        state = State.new(world,seed=4)
        state.game_minutes = 4*1440+960
        state.x,state.z,state.yaw = -230,40,1.828
        if reflection_strength(state,lighting_at(state.game_minutes,state)) != 1:
            raise AssertionError("Native probe did not activate the clear-night mirror")
        for speed in (0.0,2.0):
            state.speed = speed
            with renderer.ctx:
                renderer.render(state)
            with renderer.ctx:
                pixels = np.frombuffer(target.read(components=3,dtype="f4",alignment=1),np.float32)
            if not np.isfinite(pixels).all() or float(pixels.max()) < .1:
                raise AssertionError("Non-finite clear-night reflection colors")
    finally:
        renderer.draw_fb = original
        with renderer.ctx:
            target.release()
            depth.release()
            color.release()
    return 2


def shots(dest, *, software=False, frames=60):
    if frames<60:
        raise ValueError('Use at least 60 warmed full frames')
    out=Path(dest)
    out.mkdir(parents=True,exist_ok=True)
    baseline=resident_bytes()
    begin=time.perf_counter()
    world=World('crater')
    world_ms=(time.perf_counter()-begin)*1000
    renderer=Renderer(world,1280,720,software=software)
    state=State.new(world,seed=4)
    renderer.render(state)
    loaded_ms=(time.perf_counter()-begin)*1000
    native=hasattr(renderer,'scene_fb')
    if not software and not native:
        raise AssertionError('Native caldera capture fell back to CPU')
    text=Text()
    ui=UI(text,world)
    panel=UIState(mode='play',has_save=True)
    state.toasts.clear()
    thumbs=[]
    captures=[]
    friday=4*1440
    overlook=(-230,40,1.828)
    try:
        def compose():
            frame=resize_rgb(renderer.render(state),1280,720)
            ui.draw(frame,state,panel)
            return frame

        def capture(name,minute,pose):
            state.game_minutes=minute
            state.x,state.z,state.yaw=pose
            state.anim=14
            state.light=False
            if not world.hull_clear(state.x,state.z,state.yaw,state.boat_id):
                raise AssertionError('Capture pose is not navigable: '+name)
            frame=compose()
            write_png(out/(name+'.png'),frame)
            thumb=resize_rgb(frame,480,270)
            ui._text(thumb,name.replace('-',' ').title(),10,10,13,(255,236,180))
            thumbs.append(thumb)
            light=lighting_at(minute,state)
            captures.append(dict(name=name,minute=minute,pose=list(pose),weather=weather_at(state),
                                 mist=light['mist'],still_reflection=reflection_strength(state,light)))

        for name,offset in (('dawn-fog',20),('lifting-fog',60),('noon',360),('dusk',780),('clear-night',960)):
            capture(name,friday+offset,overlook)
        if captures[-1]['weather']!='clear' or captures[-1]['still_reflection']!=1:
            raise AssertionError('The sky reflection capture must use a real clear night')
        capture('thermal-springs',friday+360,(270,-270,math.pi/2))
        capture('cinder-isle',friday+360,(5,-70,math.pi/2))
        px,pz=world.slip.world(-8,0)
        capture('dock-survey-marker',friday+360,(px,pz,math.atan2(world.slip.ix,world.slip.iz)))
        panel.mode='map'
        capture('habitat-chart',friday+360,overlook)
        sheet=np.zeros((3*270,3*480,3),np.uint8)
        for i,thumb in enumerate(thumbs):
            sheet[(i//3)*270:(i//3+1)*270,(i%3)*480:(i%3+1)*480]=thumb
        write_png(out/'contact-sheet.png',sheet)
        del sheet,thumbs
        if native:
            _finite_scene_check(renderer,world)
            finite_night_check(renderer,world)
        witnesses=lake_witnesses(world)
        (out/'catchability.json').write_text(json.dumps(witnesses,indent=2)+'\n')
        state.x,state.z,state.yaw=overlook
        modes=('play','map','shop')
        panel.shop_tab,panel.shop_i=5,0
        for index in range(9):
            panel.mode=modes[index%3]
            compose()
        before=resident_bytes()
        objects=len(renderer._objects) if native else 0
        times=[]
        for index in range(frames):
            state.game_minutes=friday+(20,60,360,960)[index%4]
            state.anim=index/30
            panel.mode=modes[index%3]
            start=time.perf_counter()
            compose()
            times.append((time.perf_counter()-start)*1000)
        after=resident_bytes()
        if native and len(renderer._objects)!=objects:
            raise AssertionError('Caldera frames grew persistent graphics objects')
        if rss_bytes()>MEMORY_LIMIT_BYTES:
            raise AssertionError('Caldera capture exceeded the 3 GB budget')
        if loaded_ms>6000:
            raise AssertionError('Local caldera load through first frame exceeded six seconds')
        result=dict(backend=renderer.backend,software_gl=bool(getattr(renderer,'software_gl',False)),
                    hardware_gpu_measured=native and not getattr(renderer,'software_gl',False),
                    render_size=[renderer.w,renderer.h],presentation_size=[1280,720],
                    world_load_ms=round(world_ms,3),first_frame_load_ms=round(loaded_ms,3),load_limit_ms=6000,
                    scope='Warmed full caldera frames, resize and play/map/Lakes UI; fog/lift/noon/clear night',
                    frames=frames,warmup_frames=9,median_ms=round(float(np.median(times)),3),
                    p95_ms=round(float(np.percentile(times,95)),3),rss_baseline_bytes=baseline,
                    rss_before_bytes=before,rss_after_bytes=after,peak_rss_bytes=rss_bytes(),
                    memory_limit_bytes=MEMORY_LIMIT_BYTES,persistent_graphics_objects=objects,
                    finite_scene_probes=6 if native else 0,clear_night_float_probes=2 if native else 0,species_witnesses=len(witnesses),
                    minimum_rate_ratio=min(row['ratio'] for row in witnesses),captures=captures)
    finally:
        renderer.close()
        text.close()
    ref=weakref.ref(world)
    del compose,capture,renderer,ui,state,world
    gc.collect()
    if ref() is not None:
        raise AssertionError('Closed caldera capture retained its map')
    result['world_released']=True
    (out/'benchmark.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return result
