"""Repeatable alpine time, weather, habitat and load/allocation evidence.

python -m fishing --shots docs/issue-53/native --alpine [--software]
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
from .imageops import resize_rgb
from .platform import Text
from .pngsave import write_png
from .render import Renderer
from .sim import State
from .specieschecks import lake_witnesses
from .ui import UI, UIState
from .verify import MEMORY_LIMIT_BYTES, _finite_scene_check, rss_bytes
from .world import World


def resident_bytes():
    return int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')


def shots(dest, *, software=False, frames=60):
    """Write alpine views to `dest`, including Wednesday's Larch Gold and `frames` warmed timings."""
    if frames < 60:
        raise ValueError('Use at least 60 warmed full frames')
    out=Path(dest)
    out.mkdir(parents=True,exist_ok=True)
    baseline=resident_bytes()
    start=time.perf_counter()
    world=World('flathead')
    world_ms=(time.perf_counter()-start)*1000
    renderer=Renderer(world,1280,720,software=software)
    state=State.new(world,seed=16)
    # Include the first presented frame, shader compilation and foliage baking.
    renderer.render(state)
    loaded_ms=(time.perf_counter()-start)*1000
    native=hasattr(renderer,'scene_fb')
    if not software and not native:
        raise AssertionError('Native alpine capture fell back to CPU')
    text=Text()
    ui=UI(text,world)
    state.toasts.clear()
    panel=UIState(mode='play',has_save=True)
    thumbnails=[]
    try:
        def compose():
            frame=resize_rgb(renderer.render(state),1280,720)
            ui.draw(frame,state,panel)
            return frame

        def capture(name,minute,pose):
            state.game_minutes=minute
            state.x,state.z,state.yaw=pose
            state.anim=14.0
            state.light=minute==960
            frame=compose()
            write_png(out/(name+'.png'),frame)
            small=resize_rgb(frame,640,360)
            ui._text(small,name.replace('-',' ').title(),12,12,15,(255,236,180))
            thumbnails.append(small)

        overlook=(-260,10,math.pi/2)
        for name,minute in (('dawn',60),('noon',360),('dusk',780),('night',960),
                            ('snow-mist',5),('larch-gold',3*1440+360)):
            capture(name,minute,overlook)
        # A real navigable approach shows the inhabited launch, cabin and chimney.
        px,pz=world.slip.world(-55,0)
        capture('glacial-peak-outpost',360,(px,pz,math.atan2(world.slip.ix,world.slip.iz)))
        panel.mode='map'
        capture('habitat-chart',360,overlook)
        sheet=np.zeros((4*360,2*640,3),np.uint8)
        for i,thumb in enumerate(thumbnails):
            sheet[(i//2)*360:(i//2+1)*360,(i%2)*640:(i%2+1)*640]=thumb
        write_png(out/'contact-sheet.png',sheet)
        del sheet,thumbnails
        if native:
            _finite_scene_check(renderer,world)
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
            panel.mode=modes[index%3]
            state.game_minutes=(5,360,960,3*1440+360)[index%4]
            state.anim=index/30
            begin=time.perf_counter()
            compose()
            times.append((time.perf_counter()-begin)*1000)
        after=resident_bytes()
        if native and len(renderer._objects)!=objects:
            raise AssertionError('Alpine loop grew persistent GPU objects')
        if rss_bytes()>MEMORY_LIMIT_BYTES:
            raise AssertionError('Alpine capture exceeded the 3 GB budget')
        if loaded_ms>6000:
            raise AssertionError('Local lake construction and first frame exceeded 6 seconds')
        result=dict(backend=renderer.backend,software_gl=bool(getattr(renderer,'software_gl',False)),
                    render_size=[renderer.w,renderer.h],presentation_size=[1280,720],
                    world_load_ms=round(world_ms,3),first_frame_load_ms=round(loaded_ms,3),
                    load_limit_ms=6000,hardware_gpu_measured=native and not getattr(renderer,"software_gl",False),
                    scope='Warmed full alpine frames, resize and play/map/Lakes UI; snow/night/Larch Gold',
                    warmup_frames=9,frames=frames,median_ms=round(float(np.median(times)),3),
                    p95_ms=round(float(np.percentile(times,95)),3),rss_baseline_bytes=baseline,
                    rss_before_bytes=before,rss_after_bytes=after,peak_rss_bytes=rss_bytes(),
                    memory_limit_bytes=MEMORY_LIMIT_BYTES,persistent_graphics_objects=objects,
                    finite_scene_probes=4 if native else 0,species_witnesses=len(witnesses),
                    minimum_rate_ratio=min(row['ratio'] for row in witnesses),
                    capture_weather={name:weather_at(state,minute) for name,minute in
                                     (('dawn',60),('noon',360),('dusk',780),('night',960),('snow-mist',5))})
    finally:
        renderer.close()
        text.close()
    # Closure locals keep references; discard them before checking map release.
    ref=weakref.ref(world)
    del compose,capture,renderer,ui,state,world
    gc.collect()
    if ref() is not None:
        raise AssertionError('Closed alpine capture retained the map')
    result['world_released']=True
    (out/'benchmark.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return result
