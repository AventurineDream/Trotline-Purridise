"""Renderer regressions and a repeatable full-frame memory/performance check."""

from __future__ import annotations

import json
import math
import resource
import time
import tempfile
from pathlib import Path

import numpy as np

from .camera import Camera
from .data import PAINT, SPECIES
from .dialogue import Conversation
from .imageops import resize_rgb
from .platform import Text
from .render import Renderer
from .sim import Catch, Hook, SetLine, State
from .ui import UI, UIState, SHOP_TABS, HELP_N, GAME_TITLE
from .narrative import QUEST_IDS
from .bookview import BOOK_TABS
from .boat import BOATS, ROWBOAT_BATTERY_KWH
from .world import World

MEMORY_LIMIT_BYTES = 3_000_000_000


def rss_bytes():
    # Linux ru_maxrss is KiB, and records the process peak, including startup.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024


def graphics_checks(renderer, world):
    state = State.new(world,seed=31)
    state.anim = 0
    a = renderer.camera_for(state)
    state.anim = 37
    b = renderer.camera_for(state)
    for attr in ("eye","forward","right","up"):
        if not np.array_equal(getattr(a,attr),getattr(b,attr)):
            raise AssertionError("anchored camera moved")
    if a.pitch!=b.pitch or a.roll!=b.roll:
        raise AssertionError("anchored horizon moved")

    # The lightweight GPU camera must keep exactly the same projection as
    # the ray-based fallback, including look pitch and roll.
    args = (12,1.22,-30,1.1,-0.23,0.05,math.radians(74),320,180)
    ray = Camera(*args)
    mesh = Camera(*args,build_rays=False)
    for p in ((25,3,2),(20,0,10),(50,10,-20)):
        if not np.allclose(ray.world_to_cam(np.array([p])),mesh.world_to_cam(np.array([p])),atol=1e-5):
            raise AssertionError("camera projections differ")

    state.x,state.z,state.yaw = 300,30,math.pi/2
    state.anim = 0
    renderer.render(state)
    if hasattr(renderer,"scene_fb"):
        depth = renderer.read_depth()
        objects = len(renderer._objects)
        state.anim = 37
        renderer.render(state)
        next_depth = renderer.read_depth()
        if depth!=next_depth:
            raise AssertionError("shore or boat geometry moved while anchored")
        if len(renderer._objects)!=objects:
            raise AssertionError("render allocated persistent graphics objects")
        if renderer.w>1440 or renderer.h>810:
            raise AssertionError("render resolution exceeds the memory cap")
        _finite_scene_check(renderer, world)
    print("graphics ok  anchored geometry, projection, resolution cap")


def _finite_scene_check(renderer, world):
    # The normal RGB8 framebuffer clamps invalid shader values before CPU
    # readback, hiding NaNs as a dark water patch. Probe the actual scene pass
    # in floating point so idle and moving wakes must remain finite.
    original = renderer.draw_fb
    with renderer.ctx:
        color = renderer.ctx.texture((renderer.w, renderer.h), 3, dtype="f4")
        depth = renderer.ctx.depth_renderbuffer((renderer.w, renderer.h))
        target = renderer.ctx.framebuffer([color], depth)
    try:
        renderer.draw_fb = target
        state = State.new(world, seed=31)
        poses = ((state.x, state.z, state.yaw), (300.0, 30.0, math.pi/2))
        for x, z, yaw in poses:
            state.x, state.z, state.yaw = x, z, yaw
            for speed in (0.0, 2.0):
                state.speed = speed
                renderer.render(state)
                # Standalone render() leaves its context on return; readback
                # must make it current again, independently of nested scopes.
                with renderer.ctx:
                    values = np.frombuffer(target.read(components=3, dtype="f4", alignment=1), np.float32)
                if not np.isfinite(values).all():
                    raise AssertionError(f"non-finite scene colors at speed {speed} and position {(x,z)}")
    finally:
        renderer.draw_fb = original
        with renderer.ctx:
            target.release()
            depth.release()
            color.release()
    print("graphics ok  finite floating-point scene colors at idle and under power")


def _stress_lines():
    # Largest current boat: six 24-hook lines, eighteen buoys, mixed catch flags.
    lines = []
    for i in range(6):
        hooks = [Hook(True,None) for _ in range(24)]
        if i%2==0:
            hooks[0].catch = Catch("bluegill",0.55,1,1,"flats","worm",10)
        lines.append(SetLine("heavy","worm",15+i*7,12,15+i*7,44,"open",hooks))
    return lines


def benchmark(frames=1200, dest="shots/benchmark.json", software=False):
    if frames<60:
        raise ValueError("Use at least 60 frames for a meaningful benchmark")
    world = World()
    renderer = Renderer(world,1440,810,software=software)
    text = Text()
    ui = UI(text,world)
    state = State.new(world,seed=24)
    state.lines = _stress_lines()
    state.light = state.finder = True
    state.well_tier = 2
    state.toasts.clear()
    panel = UIState(mode="play",has_save=True)
    try:
        graphics_checks(renderer,world)
        modes = ("play","map","shop","setbait","check","journal","well","pause","help","title","dialogue")
        locations = ((-90,-40,-2.3),(300,30,math.pi/2),(40,10,-math.pi/2),(0,0,0))
        minutes = (0,180,360,756,900,3*1440+600,3*1440+1050,3*1440+1110)
        frame_ms,render_ms,samples = [],[],[]
        mode_ms = {mode:[] for mode in modes}
        mode_frames = {mode:0 for mode in modes}
        lake_boat_ms = {f"{lake}/{boat}":[] for lake in ("briar","cedar") for boat in BOATS}
        coverage = {name:set() for name in ("modes", "lake_boat_pairs", "shop_tabs",
                                           "help_pages", "fish_journal", "quest_journal", "book_tabs",
                                           "dialogue_givers", "dialogue_statuses")}
        for i in range(frames):
            lake_id = ("briar","cedar")[(i//300)%2]
            if world.id!=lake_id:
                renderer.close()
                world = World(lake_id)
                state.bind(world)
                renderer = Renderer(world,1440,810,software=software)
                ui = UI(text,world)
            t0 = time.perf_counter()
            state.anim = i/30
            if world.id=="cedar":
                spots = [row for row in world.zones if row[0] in ("deep","lilies","inlet","cypress")]
                spot = spots[(i//60)%len(spots)]
                state.x,state.z,state.yaw = spot[1],spot[2],locations[(i//60)%len(locations)][2]
            else:
                state.x,state.z,state.yaw = locations[(i//60)%len(locations)]
            state.boat_id = tuple(BOATS)[(i//100)%len(BOATS)]
            # Exercise oars, powered travel and the depleted-battery fallback.
            rowboat_variant = (i//20)%3
            state.rowboat_trolling_motor = rowboat_variant!=0
            state.rowboat_battery_kwh = (ROWBOAT_BATTERY_KWH*(0.1+0.8*((i%100)/100))
                                         if rowboat_variant==1 else 0.0)
            state.sail_raised = state.boat_id=="sail" and (i//20)%2==1
            state.fuel = state.boat.tank*(0.1+0.8*((i%100)/100))
            state.yaw += math.sin(i*0.02)*0.18
            state.look = math.sin(i*0.03)*0.12
            state.steer = math.sin(i*0.015)*0.3
            # Advance lighting at 12x within each block, including rain onset
            # and the midnight crossfade, while keeping every allocation cap.
            state.game_minutes = minutes[(i//90)%len(minutes)] + (i%90)*12/30
            state.speed = 1.8
            state.anchored = False
            panel.mode = modes[(i//20)%len(modes)]
            # Advance within each mode independently. Coupling selectors to
            # the outer frame block silently skipped half of the old menus.
            visit = mode_frames[panel.mode]
            mode_frames[panel.mode] += 1
            panel.shop_tab = visit%len(SHOP_TABS)
            panel.help_page = visit%HELP_N
            legacy_pages = len(SPECIES) + len(QUEST_IDS)
            journal_visit = visit % (legacy_pages + 3)
            panel.journal_page = ((1, 2, 4)[journal_visit - legacy_pages]
                                  if journal_visit >= legacy_pages else
                                  (3 if journal_visit >= len(SPECIES) else 0))
            panel.journal_i = journal_visit%len(SPECIES)
            panel.book_entry_i = journal_visit%len(SPECIES)
            panel.journal_quest_i = (journal_visit-len(SPECIES))%len(QUEST_IDS)
            if panel.mode=="dialogue":
                quest_id = QUEST_IDS[visit%len(QUEST_IDS)]
                quest = ui.narrative_content.quests[quest_id]
                status = ("available","active","ready","completed")[(visit//len(QUEST_IDS))%4]
                panel.dialogue_content = ui.narrative_content
                panel.conversation = Conversation(quest["giver_id"],quest_id,quest["dialogue"][status])
                coverage["dialogue_givers"].add(quest["giver_id"])
                coverage["dialogue_statuses"].add(status)
            panel.confirm_new = panel.mode=="title" and i%40>20
            forward = np.array([math.sin(state.yaw),math.cos(state.yaw)])
            right = np.array([forward[1],-forward[0]])
            for line_i,line in enumerate(state.lines):
                start = np.array([state.x,state.z])+forward*18+right*(line_i-2)*6
                end = start+forward*32
                line.x0,line.z0,line.x1,line.z1 = *start,*end
            if i%60==0:
                for slot,paints in PAINT.items():
                    state.look_paint[slot] = paints[(i//60)%len(paints)][0]
            low = renderer.render(state)
            big = resize_rgb(low,1440,810)
            ui.draw(big,state,panel)
            coverage["modes"].add(panel.mode)
            coverage["lake_boat_pairs"].add(f"{world.id}/{state.boat_id}")
            if panel.mode=="shop":
                coverage["shop_tabs"].add(panel.shop_tab)
            elif panel.mode=="help":
                coverage["help_pages"].add(panel.help_page)
            elif panel.mode=="journal":
                coverage["book_tabs"].add(panel.journal_page)
                if panel.journal_page in (0, 3):
                    coverage["quest_journal" if panel.journal_page == 3 else "fish_journal"].add(
                        panel.journal_quest_i if panel.journal_page == 3 else panel.journal_i)
            if low.dtype!=np.uint8 or not np.isfinite(low).all():
                raise AssertionError("invalid frame")
            if text.cache_bytes>text.cache_limit:
                raise AssertionError("text cache exceeded its memory budget")
            if rss_bytes()>=MEMORY_LIMIT_BYTES:
                raise AssertionError("game exceeded 3 GB of RAM")
            if i>=10:
                elapsed_ms = (time.perf_counter()-t0)*1000
                frame_ms.append(elapsed_ms)
                mode_ms[panel.mode].append(elapsed_ms)
                lake_boat_ms[f"{world.id}/{state.boat_id}"].append(elapsed_ms)
                render_ms.append(renderer.last_ms)
            if i%100==0:
                samples.append({"frame":i,"peak_rss_mb":round(rss_bytes()/1024**2,2),
                                "lake":world.id,"boat":state.boat_id,
                                "text_cache_mb":round(text.cache_bytes/1024**2,2)})
            if i%100==0:
                elapsed_ms = (time.perf_counter()-t0)*1000
                print(f"frame {i}/{frames}  peak RAM {rss_bytes()/1024**2:.0f} MiB  full frame {elapsed_ms:.0f} ms",flush=True)
        expected_coverage = {"modes":len(modes), "lake_boat_pairs":len(lake_boat_ms),
                             "shop_tabs":len(SHOP_TABS), "help_pages":HELP_N,
                             "fish_journal":len(SPECIES), "quest_journal":len(QUEST_IDS),
                             "book_tabs":len(BOOK_TABS),
                             "dialogue_givers":len(QUEST_IDS), "dialogue_statuses":4}
        coverage_complete = all(len(coverage[name])==count for name,count in expected_coverage.items())
        if frames>=1200 and not coverage_complete:
            counts = {name:len(values) for name,values in coverage.items()}
            raise AssertionError(f"incomplete benchmark coverage: {counts}")
        report = {
            "frames":frames,"backend":renderer.backend,
            "render_size":[renderer.w,renderer.h],"window_size":[1440,810],
            "antialias_samples":getattr(renderer,"samples",1),
            "render_median_ms":round(float(np.median(render_ms)),2),
            "full_frame_median_ms":round(float(np.median(frame_ms)),2),
            "full_frame_p95_ms":round(float(np.percentile(frame_ms,95)),2),
            "mode_median_ms":{mode:round(float(np.median(values)),2) for mode,values in mode_ms.items() if values},
            "lake_boat_median_ms":{mode:round(float(np.median(values)),2) for mode,values in lake_boat_ms.items() if values},
            "peak_rss_mb":round(rss_bytes()/1024**2,2),
            "ram_limit_bytes":MEMORY_LIMIT_BYTES,
            "text_cache_limit_bytes":text.cache_limit,
            "memory_samples":samples,
            "coverage":{name:sorted(values) for name,values in coverage.items()},
            "coverage_complete":coverage_complete,
            "checks":["fixed anchored depth","matching camera projections","eleven UI modes, including dialogue",
                      "both lakes with repeated renderer release and rebuild","all four boats and raised sail",
                      "six shop tabs, four help pages, 36 fish and 12 quest journal entries",
                      "twelve dialogue givers and four saved quest statuses","changing fuel and battery gauges",
                      "clear, fair, night, drizzle and 12x midnight fades","five heavy lines and fifteen buoys",
                      "all paint colors","changing look and steering","bounded text cache"],
        }
        path = Path(dest)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(report,indent=2)+"\n")
        print(json.dumps({k:v for k,v in report.items() if k not in ("memory_samples","checks")},indent=2))
        return 0
    finally:
        renderer.close()
        text.close()


def window_smoke():
    """Exercise the actual window and game session with a temporary save."""
    from .audio import Audio
    from .game import Keys,Session
    from .platform import Platform
    from .pngsave import write_png
    world = World()
    platform = Platform(1280,720,f"{GAME_TITLE} — visual check",verify_pixels=True)
    text = Text()
    renderer = Renderer(world,1280,720,software=platform.context is None,context=platform.context)
    audio = Audio()
    ui = UI(text,world)
    frames = 0
    try:
        with tempfile.TemporaryDirectory(prefix="briar-check-") as temp:
            state = State.new(world,seed=24)
            session = Session(world,Path(temp)/"briar.json",state,False)
            # Re-render an unchanged scene after real SDL presentation.
            # The former context switch produced corrupted/black frames here.
            baseline = renderer.render(state)
            shown = resize_rgb(baseline,1280,720)
            platform.present(shown)
            if not np.array_equal(platform.read_surface(),shown):
                raise AssertionError("SDL window pixels differ from the submitted frame")
            for _ in range(3):
                same = renderer.render(state)
                if not np.array_equal(same,baseline):
                    raise AssertionError("window presentation corrupted the next lake frame")
                platform.present(resize_rgb(same,1280,720))
            start = time.perf_counter()
            previous = start
            control_phases=set()
            while time.perf_counter()-start<5:
                now = time.perf_counter()
                dt = min(0.1,now-previous)
                previous = now
                if platform.poll().quit:
                    break
                keys = Keys()
                elapsed=now-start
                if session.ui.mode in {"title", "new_mode"} and elapsed>=0.4:
                    keys = Keys(pressed={"return"})
                elif 0.4<=elapsed<1.5 and session.ui.mode=="play":
                    keys = Keys(held={"w"})
                    control_phases.add("forward")
                elif 1.5<=elapsed<2.0:
                    control_phases.add("hold")
                elif 2.0<=elapsed<2.4:
                    keys = Keys(held={"shift"})
                    control_phases.add("left idle")
                elif 2.4<=elapsed<3.8:
                    keys = Keys(held={"s"})
                    control_phases.add("reverse")
                elif elapsed>=3.8:
                    keys = Keys(held={"rshift"})
                    control_phases.add("right idle")
                session.tick(keys,dt)
                frame = resize_rgb(renderer.render(session.state),1280,720)
                ui.draw(frame,session.state,session.ui)
                platform.present(frame)
                if frames%30==0 and not np.array_equal(platform.read_surface(),frame):
                    raise AssertionError("displayed game frame is corrupted")
                audio.update(dt,session.state.throttle,session.state.speed,True)
                frames += 1
                platform.delay(max(0,int(16-(time.perf_counter()-now)*1000)))
            if frames<5:
                raise AssertionError("window did not render enough frames")
            if len(control_phases)!=5 or session.state.throttle_setting!=0:
                raise AssertionError("window did not exercise the full throttle sequence")
            # Run a complete rain-to-clear midnight crossing through the same
            # shared context and SDL presentation path used during real play.
            state = session.state
            state.anchored = True
            state.speed = state.throttle = state.throttle_setting = 0.0
            state.time_scale = 12
            state.game_minutes = 3*1440 + 1050
            state.minute_acc = 0.0
            session.ui.mode = "play"
            previous_lake = renderer.render(state).copy()
            weather_step = 0.0
            for i in range(101):
                if platform.poll().quit:
                    raise AssertionError("window check was closed during the midnight fade")
                session.tick(Keys(),0.05)
                lake = renderer.render(state)
                delta = float(np.abs(lake.astype(np.float32)-previous_lake).mean())
                weather_step = max(weather_step,delta)
                if delta>4.0:
                    raise AssertionError(f"12x midnight frame jumped by {delta:.2f}/255")
                previous_lake = lake.copy()
                frame = resize_rgb(lake,1280,720)
                ui.draw(frame,state,session.ui)
                platform.present(frame)
                if i%25==0 and not np.array_equal(platform.read_surface(),frame):
                    raise AssertionError("midnight SDL pixels differ from the rendered frame")
                if i==49:
                    write_png("shots/midnight.png",platform.read_surface())
            # Purchase both larger boats through the real menu dispatcher,
            # then rebuild both lakes in this same SDL-owned graphics context.
            state._park(world)
            state.money=3000
            state.time_scale=1
            state.game_minutes=180
            for boat_id,index in (("sail",1),("pontoon",2)):
                session.ui.mode="play"
                session.tick(Keys(pressed={"e"}),0.01)
                session.ui.shop_tab=4
                session.ui.shop_i=index
                session.tick(Keys(pressed={"return"}),0.01)
                if state.boat_id!=boat_id:
                    raise AssertionError(f"native menu did not buy {boat_id}")
                session.ui.mode="play"
                if boat_id=="sail":
                    from .weather import wind_at
                    state.x=state.z=0
                    state.yaw=wind_at(state.game_minutes)[0]+math.pi/2
                    initial_fuel=state.fuel
                    session.tick(Keys(pressed={"q"}),0.05)
                    for _ in range(15):
                        session.tick(Keys(),0.05)
                        frame=resize_rgb(renderer.render(state),1280,720)
                        ui.draw(frame,state,session.ui)
                        platform.present(frame)
                        if not np.array_equal(platform.read_surface(),frame):
                            raise AssertionError("native sailing pixels were corrupted")
                    if state.fuel!=initial_fuel or not state.sail_raised or state.speed<=0:
                        raise AssertionError("native sail control did not provide free propulsion")
                    write_png("shots/window-sailing.png",platform.read_surface())
                else:
                    frame=resize_rgb(renderer.render(state),1280,720)
                    ui.draw(frame,state,session.ui)
                    platform.present(frame)
                    write_png("shots/window-pontoon.png",platform.read_surface())
                state._park(world)
            for lake_id,index in (("cedar",1),("briar",0)):
                session.ui.mode="play"
                session.tick(Keys(pressed={"e"}),0.01)
                session.ui.shop_tab=5
                session.ui.shop_i=index
                session.tick(Keys(pressed={"return"}),0.01)
                if session.world.id!=lake_id:
                    raise AssertionError("native Lakes menu did not travel")
                renderer.close()
                world=session.world
                ui=UI(text,world)
                renderer=Renderer(world,1280,720,software=platform.context is None,context=platform.context)
                for _ in range(3):
                    frame=resize_rgb(renderer.render(state),1280,720)
                    ui.draw(frame,state,session.ui)
                    platform.present(frame)
                    if not np.array_equal(platform.read_surface(),frame):
                        raise AssertionError("lake switch corrupted SDL pixels")
                write_png(f"shots/window-{lake_id}.png",platform.read_surface())
            write_png("shots/window.png",platform.read_surface())
            session.save()
            State.load(session.save_path,world)
        if rss_bytes()>=MEMORY_LIMIT_BYTES:
            raise AssertionError("window exceeded the RAM budget")
        print(f"window ok  {frames} throttle frames, 101 midnight frames at 12x; "
              "paid boats, fuel-free sailing and both lake swaps; "
              f"max weather step {weather_step:.2f}/255; repeated pixels and SDL readback verified; "
              f"{renderer.backend}; peak RAM {rss_bytes()/1024**2:.0f} MiB")
        return 0
    finally:
        audio.close()
        renderer.close()
        text.close()
        platform.close()
