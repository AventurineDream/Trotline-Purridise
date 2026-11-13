"""Procedural-shell turntables, chime samples and incremental memory evidence."""
from functools import lru_cache
import gc
import math
import os
from pathlib import Path
try:
    import resource
except ImportError:
    # Unix-only; on Windows the /proc fallback below is also unavailable,
    # so _rss_bytes() reports 0 instead of crashing.
    resource = None
import time
import tracemalloc
import wave
import json
import numpy as np

from . import botmesh
from .botchimes import SAMPLE_RATE, synthesize
from .camera import Camera
from .data import BOT_SHELLS
from .pngsave import write_png
from .software import SoftwareRenderer
from .weather import frame_light


@lru_cache(maxsize=1)
def _floor():
    b=botmesh.Builder()
    b.ellipsoid((0,-.027,0),(.34,.016,.34),(.34,.40,.41),32,3)
    b.torus((0,-.020,0),(.32,.32),.003,(.58,.50,.34),segments=32)
    return b.finish()


def preview(shell, *, collar=True, knot='bow', night=False, angle=0., size=256,
            anim=0., scouting=False, emission=True, stage='retied', sway=0.):
    """Use the actual software mesh/raster path without loading another lake."""
    renderer=SoftwareRenderer.__new__(SoftwareRenderer)
    renderer.w=renderer.h=size
    yy=np.linspace(0,1,size,dtype=np.float32)[:,None,None]
    top=np.array((.045,.068,.10) if night else (.88,.86,.78),np.float32)
    bottom=np.array((.09,.12,.15) if night else (.62,.66,.62),np.float32)
    renderer.col=np.broadcast_to(top*(1-yy)+bottom*yy,(size,size,3)).copy()
    renderer.z=np.full((size,size),1e6,np.float32)
    radius=.97
    x,z=math.sin(angle)*radius,math.cos(angle)*radius
    camera=Camera(x,.34,z,math.atan2(-x,-z),-.085,0,math.radians(43),size,size,build_rays=False)
    light=frame_light(23 if night else 10,'clear')
    floor=_floor()
    faces=[botmesh.Face(floor.points[i],floor.normals[i],floor.colors[i],emissive=0.) for i in range(len(floor.points))]
    renderer._faces(camera,faces,light,boat=False)
    faces=botmesh.faces((0,0,0),(1,0,0),(0,1,0),(0,0,1),shell=shell,stage=stage,knot=knot,
                        collar_visible=collar,anim=anim,scouting=scouting,sway=sway)
    if not emission:
        from dataclasses import replace
        faces=[replace(face,emissive=0.) for face in faces]
    renderer._faces(camera,faces,light,boat=False)
    return np.rint(np.clip(renderer.col,0,1)*255).astype(np.uint8)


def _rss_bytes():
    try:
        return int(Path('/proc/self/statm').read_text().split()[1])*os.sysconf('SC_PAGE_SIZE')
    except (OSError,ValueError,AttributeError):
        if resource is None:
            return __import__("fishing.verify", fromlist=["rss_bytes"]).rss_bytes()
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024


def memory_report():
    """Measure runtime mesh/PCM resources, excluding gallery image buffers."""
    botmesh.local_mesh.cache_clear();synthesize.cache_clear();gc.collect()
    baseline=_rss_bytes()
    tracemalloc.start()
    max_faces=0;times=[]
    for shell in BOT_SHELLS:
        for style in ('none','loop','loose','square','bow','sailors_hitch'):
            mesh=botmesh.local_mesh(shell,style)
            max_faces=max(max_faces,len(mesh.points))
        synthesize(BOT_SHELLS[shell].chime)
    for index in range(100):
        shell=tuple(BOT_SHELLS)[index%5]
        start=time.perf_counter()
        faces=botmesh.faces((0,0,0),(1,0,0),(0,1,0),(0,0,1),shell=shell,
                            stage='retied',knot='bow',anim=index*.1,scouting=True)
        if index>=10: times.append((time.perf_counter()-start)*1000)
        del faces
    current,peak=tracemalloc.get_traced_memory();tracemalloc.stop();gc.collect()
    delta=max(0,_rss_bytes()-baseline)
    audio_bytes=sum(synthesize(row.chime).nbytes for row in BOT_SHELLS.values())
    return dict(rss_growth_mib=round(delta/1024**2,3),python_numpy_peak_mib=round(peak/1024**2,3),
                retained_python_numpy_mib=round(current/1024**2,3),pcm_bytes=audio_bytes,
                mesh_cache_entries=botmesh.local_mesh.cache_info().currsize,mesh_cache_limit=12,allocation_tracing=True,
                max_faces=max_faces,mesh_rig_p50_ms=round(float(np.percentile(times,50)),3),
                mesh_rig_p95_ms=round(float(np.percentile(times,95)),3),frames=len(times),
                scope='Incremental Bot mesh cache, scout rig and all five PCM chimes; excludes renderer/context and gallery image buffers')


def bot_shell_gallery(destination, *, text=None, renderer=None):
    from .platform import Text
    from .ui import UI
    own_text=text is None
    text=Text() if own_text else text
    painter=UI(text,None)
    out=Path(destination);out.mkdir(parents=True,exist_ok=True)
    # Measure before retaining screenshot arrays, which are not runtime assets.
    report=memory_report()
    (out/'bot-shell-memory.json').write_text(json.dumps(report,indent=2)+'\n')
    contact=[]
    def label(image,value):
        painter._text(image,value,10,8,12,(225,220,197),False,'sans')
        return image
    try:
        for shell in BOT_SHELLS:
            views=[]
            for night in (False,True):
                for collar in (False,True):
                    frames=[]
                    for angle in (0.,math.pi/2,math.pi,math.pi*1.5):
                        frame=preview(shell,collar=collar,night=night,angle=angle)
                        frames.append(frame)
                    strip=np.concatenate(frames,axis=1)
                    # A dark label rail avoids altering the actual model pixels.
                    rail=np.full((30,strip.shape[1],3),(25,40,43),np.uint8)
                    painter._text(rail,BOT_SHELLS[shell].name+' · '+('Night' if night else 'Day')+' · '+('Wool collar / bow' if collar else 'No collar')+' · 0° / 90° / 180° / 270°',10,7,12,(232,226,205),False,'sans')
                    filename=f'bot-turntable-{shell}-'+('night' if night else 'day')+'-'+('collar' if collar else 'bare')+'.png'
                    write_png(out/filename,np.concatenate((rail,strip)))
                    thumb=frames[0].copy()
                    tag=np.full((24,256,3),(25,40,43),np.uint8)
                    painter._text(tag,shell.upper()+' · '+('NIGHT' if night else 'DAY')+' · '+('COLLAR' if collar else 'BARE'),8,5,11,(232,226,205),False,'sans')
                    views.append(np.concatenate((tag,thumb)))
            contact.append(np.concatenate(views,axis=1))
        write_png(out/'bot-shell-contact-sheet.png',np.concatenate(contact))
        knots=[]
        for knot in ('square','bow','sailors_hitch'):
            strip=np.concatenate([preview(shell,collar=True,knot=knot,size=256) for shell in BOT_SHELLS],axis=1)
            rail=np.full((28,strip.shape[1],3),(25,40,43),np.uint8)
            painter._text(rail,knot.replace('_',' ').title()+' · same shared wool collar on every shell',10,7,12,(232,226,205),False,'sans')
            knots.append(np.concatenate((rail,strip)))
        write_png(out/'bot-knot-comparison.png',np.concatenate(knots))
        motion=[]
        for shell in BOT_SHELLS:
            motion.append(np.concatenate([preview(shell,anim=t,scouting=True,angle=math.pi/5) for t in (0.,.18,.40)],axis=1))
        write_png(out/'bot-scout-motion.png',np.concatenate(motion))
        for row in BOT_SHELLS.values():
            with wave.open(str(out/(row.chime+'.wav')),'wb') as audio:
                audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(SAMPLE_RATE)
                audio.writeframes(synthesize(row.chime).astype('<i2',copy=False).tobytes())
        if renderer is not None and hasattr(renderer, 'ctx'):
            gl_shell_comparison(renderer,out)
        print('Bot shell memory / rig: '+json.dumps(report))
        return report
    finally:
        if own_text:text.close()



def gl_shell_comparison(renderer, destination):
    """Native scene snapshots with the same active world/context as --shots."""
    from .sim import State
    from .imageops import resize_rgb
    state=State.new(renderer.world,seed=4618)
    state.x,state.z=0.,-12.
    state.bot_phase='out';state.bot_x=state.bot_z=0.;state.anim=2.5
    state.v2['profile']['collar'].update(stage='retied',knot='bow')
    camera=Camera(1.4,.8,1.4,math.pi*1.25,-.13,0,math.radians(52),renderer.w,renderer.h,build_rays=False)
    rows=[]
    for minute in (360.,1080.):
        frames=[]
        for shell in BOT_SHELLS:
            state.game_minutes=minute;state.v2['profile']['shell']=shell
            frame=renderer.render(state,camera).copy()
            width=min(320,frame.shape[1]);height=int(frame.shape[0]*width/frame.shape[1])
            frames.append(resize_rgb(frame,width,height))
        rows.append(np.concatenate(frames,axis=1))
    write_png(Path(destination)/'bot-shell-gl-comparison.png',np.concatenate(rows))
