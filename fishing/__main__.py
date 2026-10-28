"""Trotline Purridise. `python -m fishing` plays. `--selftest` never opens a window."""

from __future__ import annotations

import math
import resource
import sys
import time
from pathlib import Path

import numpy as np

from .camera import self_check
from .data import SPECIES_BY_ID, dollars
from .game import Keys, Session
from .imageops import resize_rgb
from .pngsave import write_png
from .render import Renderer
from .savepaths import UnsupportedSaveVersionError, parse_save_option
from .sim import Catch, HeldLine, Hook, SetLine, State
from .ui import UI, UIState
from .world import World, shore_sd

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        argv, save_path = parse_save_option(argv)
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    if "--selftest" in argv:
        return selftest(software="--software" in argv)
    if "--benchmark" in argv:
        from .verify import benchmark
        i = argv.index("--benchmark")
        frames = int(argv[i+1]) if i+1<len(argv) and argv[i+1].isdigit() else 1200
        return benchmark(frames,software="--software" in argv)
    if "--smoke" in argv:
        from .verify import window_smoke
        return window_smoke()
    if "--chart" in argv:
        i = argv.index("--chart")
        dest = argv[i + 1] if i + 1 < len(argv) else str(ROOT / "shots" / "chart.png")
        return chart(dest)
    if "--shots" in argv:
        i = argv.index("--shots")
        dest = argv[i + 1] if i + 1 < len(argv) else str(ROOT / "shots")
        if "--species" in argv:
            from .speciesgallery import gallery
            gallery(dest, software="--software" in argv)
            return 0
        if "--lake-framework" in argv:
            from .lakeshots import shots as lake_shots
            selected = next((arg.split("=", 1)[1].split(",") for arg in argv
                             if arg.startswith("--lakes=")), None)
            lake_shots(dest, software="--software" in argv, lakes=selected)
            return 0
        return shots(dest)
    from .game import run
    try:
        run(software="--software" in argv, save_path=save_path)
    except UnsupportedSaveVersionError as exc:
        print(exc, file=sys.stderr)
        return 1
    return 0


def selftest(*,software=False) -> int:
    self_check()
    world = World()
    _world_checks(world)
    _economy(world)
    _rules(world)
    _play(world)
    from .boatchecks import boat_checks
    boat_checks(world)
    from .bot import checks as bot_checks
    bot_checks(world)
    from .updatechecks import interface_checks, weather_checks
    interface_checks(world)
    from .test_narrative import narrative_checks
    narrative_checks()
    from .test_content import content_checks
    content_checks()
    from .test_anchors import anchor_checks
    anchor_checks()
    from .test_npcs import npc_checks
    npc_checks()
    from .test_dialogue import dialogue_checks
    dialogue_checks()
    renderer = Renderer(world,software=software)
    low = renderer.render(State.new(world, seed=1))
    if low.shape != (renderer.h, renderer.w, 3) or low.dtype != np.uint8:
        raise AssertionError(f"frame {low.shape} {low.dtype}")
    if float(low.std()) < 8:
        raise AssertionError("frame is flat")
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    print(f"frame {low.shape[1]}x{low.shape[0]}  std {low.std():.1f}  RSS {rss:.0f} MB")
    if rss > 1500:
        raise AssertionError(f"RSS {rss:.0f} MB")
    from .verify import graphics_checks
    graphics_checks(renderer,world)
    weather_checks(renderer,world)
    renderer.close()
    from .expansionchecks import expansion_checks
    expansion_checks(world,software=software)
    print("selftest ok")
    return 0


def _world_checks(world: World):
    if float(shore_sd(0.0, 0.0)) >= 0:
        raise AssertionError("lake center is land")
    if float(shore_sd(700.0, 500.0)) <= 0:
        raise AssertionError("far corner is water")
    st = State.new(world, seed=1)
    if not world.navigable(st.x, st.z):
        raise AssertionError("the slip is not navigable")
    if st.slip_status(world) != "docked":
        raise AssertionError("a new game is not in the slip")
    deep = float(world.depth(75.0, -25.0))
    flats = float(world.depth(10.0, 205.0))
    print(f"depth  deep {deep:.1f} m   flats {flats:.1f} m   dock {st.x:.0f},{st.z:.0f}")
    if deep < 10.0:
        raise AssertionError(f"deep hole is {deep:.1f} m")
    if not (0.4 <= flats <= 3.2):
        raise AssertionError(f"flats are {flats:.1f} m")


def _economy(world: World):
    print("strategy incomes, 24 game hours, check every 4:")
    bands = {
        "worm": (8.0, 180.0),
        "liver": (8.0, 280.0),
        "shad": (6.0, 400.0),
    }
    zones = {"worm": "flats", "liver": "cypress", "shad": "deep"}
    for bait, zone in zones.items():
        totals = []
        counts = []
        for seed in (11, 12, 13, 14):
            money, hooked = _work(world, zone, bait, hours=24, seed=seed)
            totals.append(money)
            counts.append(hooked)
        mid = sorted(totals)[len(totals) // 2]
        lo, hi = bands[bait]
        print(
            f"  {bait:6s} {zone:8s}  "
            f"${min(totals):6.2f} .. ${max(totals):6.2f}  mid ${mid:6.2f}  "
            f"hooked {min(counts)}..{max(counts)}"
        )
        if not lo <= mid <= hi:
            raise AssertionError(f"{bait} mid ${mid:.2f} outside ${lo:.0f}..${hi:.0f}")
        if max(counts) < 1:
            raise AssertionError(f"{bait} hooked nothing")


def _work(world, zone, bait, hours, seed, check_every=4) -> tuple[float, int]:
    state = State.new(world, seed=seed)
    state.money = 46.0
    for key in list(state.bait):
        state.bait[key] = 0
    state.bait[bait] = 72
    x, z, yaw = _pose(world, zone, bait)
    state.x, state.z, state.yaw = x, z, yaw
    state.speed = 0.0
    state.held = [HeldLine("std")]
    state.lines.clear()
    err = state.try_set(world, 0, bait)
    if err:
        raise AssertionError(f"set {bait} on {zone}: {err}")
    state.anchored = True
    blocks = max(1, hours // check_every)
    for _ in range(blocks):
        state._advance_hours(check_every, toast=False)
        state.take_all(0)
        if state.well_load() > state.well_cap() * 0.72:
            state.sell_all()
        state.rebait(0)
    state.take_all(0)
    state.sell_all()
    worth = state.money
    return worth, state.hooked_total


def _pose(world, zone, bait) -> tuple[float, float, float]:
    probe = State.new(world, seed=1)
    x, z = _spot(world, zone)
    last = "no water"
    for k in range(36):
        yaw = k * math.tau / 36.0
        probe.x, probe.z, probe.yaw = x, z, yaw
        probe.speed = 0.0
        probe.lines.clear()
        probe.held = [HeldLine("std")]
        probe.bait[bait] = 80
        last = probe.try_set(world, 0, bait) or ""
        if last == "":
            return x, z, yaw
    raise AssertionError(f"nowhere to set on {zone}: {last}")


def _spot(world, zone) -> tuple[float, float]:
    centers = {name: (x, z) for name, x, z, _r in world.zones}
    cx, cz = centers[zone]
    for rad in (0.0, 12.0, 24.0, 40.0, 60.0):
        for k in range(20):
            ang = k / 20.0 * math.tau
            x = cx + math.cos(ang) * rad
            z = cz + math.sin(ang) * rad
            if world.zone_at(x, z) != zone:
                continue
            if not world.navigable(x, z):
                continue
            if float(world.depth(x, z)) < 1.3:
                continue
            return x, z
    raise AssertionError(f"no {zone} water")


def _rules(world: World):
    state = State.new(world, seed=7)
    x, z, yaw = _pose(world, "flats", "worm")
    state.x, state.z, state.yaw = x, z, yaw
    state.speed = 0.0
    before = state.bait["worm"]
    err = state.try_set(world, 0, "worm")
    if err:
        raise AssertionError(err)
    if state.bait["worm"] != before - 12:
        raise AssertionError("bait was not consumed")
    state.anchored = True
    state._advance_hours(10, toast=False)
    hooked = state.hooked_total
    if hooked < 1:
        state._advance_hours(10, toast=False)
    on = state.lines[0].fish_on()
    state.take_all(0)
    if state.well and on:
        frozen = state.well[0].quality
        state._advance_hours(6, toast=False)
        if state.well[0].quality != frozen:
            raise AssertionError("the livewell aged a fish")
    state._advance_hours(14, toast=False)
    for hook in state.lines[0].hooks:
        if hook.catch is not None and hook.catch.age >= 13.0:
            raise AssertionError("a spoiled fish stayed on the hook")
    # A long absence is one soak, then empty hooks. Money stays put.
    held_money = state.money
    state.stamp = time.time() - 3 * 3600
    state.catch_up(time.time())
    if abs(state.money - held_money) > 0.001:
        raise AssertionError("offline soak paid out by itself")
    for line in state.lines:
        for hook in line.hooks:
            if hook.catch is not None and hook.catch.age >= 13.0:
                raise AssertionError("offline left a spoiled fish")
    state.money = 1.0
    if state.buy_motor() is None:
        raise AssertionError("bought a motor with a dollar")
    if state.motor != 0:
        raise AssertionError("motor changed without paying")
    state.money = 500.0
    if state.buy_motor() is not None or state.motor != 1:
        raise AssertionError("could not buy the 9.9")
    state.bait["worm"] = state.box_cap()
    if state.buy_bait("liver") is None:
        raise AssertionError("bait box overflowed")
    heavy = state.well_cap()
    from .sim import Catch
    state.well.append(Catch("buffalo", heavy - 1.0, 1.0, 0.0, "deep", "shad", 12.0))
    state.lines[0].hooks[0].catch = Catch("buffalo", 5.0, 1.0, 0.0, "flats", "worm", 12.0)
    state.lines[0].hooks[0].baited = False
    err = state.take_hook(0, 0)
    if err is None:
        raise AssertionError("livewell accepted more than it holds")
    path = ROOT / ".selftest-save.json"
    try:
        state.save(path)
        loaded = State.load(path, world)
    finally:
        path.unlink(missing_ok=True)
    if abs(loaded.money - state.money) > 0.001 or loaded.motor != state.motor:
        raise AssertionError("save roundtrip")
    if len(loaded.lines) != len(state.lines):
        raise AssertionError("lines did not roundtrip")
    print(f"rules ok  {dollars(state.money)}  motor {state.motor}")


def _play(world: World):
    path = ROOT / ".selftest-play.json"
    try:
        state = State.new(world, seed=3)
        session = Session(world, path, state, has_save=False)
        session.ui.mode = "play"
        for _ in range(40):
            session.tick(Keys(held={"w"}), 0.05)
        if session.state.traveled < 1.0 and abs(session.state.speed) < 0.4:
            raise AssertionError(f"boat did not leave the slip, speed {session.state.speed:.2f}")
        for _ in range(30):
            session.tick(Keys(held={"s"}), 0.05)
        session.state.speed = 2.0
        session.state.throttle = 1.0
        session.state.anchored = False
        session.tick(Keys(pressed={"t"}), 0.05)
        if session.state.time_scale != 1:
            raise AssertionError("time scaled while moving")
        x, z, yaw = _pose(world, "flats", "worm")
        session.state.x, session.state.z, session.state.yaw = x, z, yaw
        session.state.speed = 0.0
        session.state.throttle = 0.0
        session.state.anchored = False
        worms = session.state.bait["worm"]
        session.tick(Keys(pressed={"f"}), 0.05)
        if session.ui.mode != "setbait":
            raise AssertionError("F did not open the bait box")
        session.tick(Keys(pressed={"return"}), 0.05)
        if session.ui.mode != "play" or len(session.state.lines) != 1:
            raise AssertionError(session.ui.note or "the line was not set")
        if session.state.bait["worm"] != worms - 12:
            raise AssertionError("the set did not spend bait")
        session.tick(Keys(pressed={"space"}), 0.05)
        if not session.state.anchored:
            raise AssertionError("anchor did not drop")
        session.tick(Keys(pressed={"t"}), 0.05)
        if session.state.time_scale != 3:
            raise AssertionError("anchored time scale")
        session.state._advance_hours(12, toast=False)
        session.state.v2["settings"]["haul_speed"] = "instant"
        session.tick(Keys(pressed={"e"}), 0.05)
        if session.ui.mode != "check":
            raise AssertionError(session.ui.note or "E did not check the line")
        session.ui.check_i = 12  # take all sits after the 12 hooks
        session.tick(Keys(pressed={"return"}), 0.05)
        dock = world.slip.world(world.slip.land_ext - 4.5, 0.0)
        session.state.x, session.state.z = dock
        session.state.speed = 0.0
        session.state.throttle = 0.0
        session.ui.mode = "play"
        session.tick(Keys(pressed={"e"}), 0.05)
        if session.ui.mode != "shop":
            raise AssertionError("E did not open the landing")
        if session.state.well:
            session.tick(Keys(pressed={"return"}), 0.05)
            if session.state.well:
                raise AssertionError("sell everything left fish in the well")
        session.tick(Keys(pressed={"right"}), 0.05)
        session.tick(Keys(pressed={"right"}), 0.05)
        if session.ui.shop_tab != 2:
            raise AssertionError("gear tab")
        session.state.money = 1.0
        motor = session.state.motor
        session.tick(Keys(pressed={"return"}), 0.05)
        if session.state.motor != motor or not session.ui.note:
            raise AssertionError("the shop took a dollar")
        session.state.money = 500.0
        session.ui.note = ""
        session.tick(Keys(pressed={"return"}), 0.05)
        if session.state.motor != motor + 1:
            raise AssertionError(session.ui.note or "shop did not sell the motor")
        session.tick(Keys(pressed={"esc"}), 0.05)
        session.save()
        loaded = State.load(path, world)
        if loaded.motor != session.state.motor:
            raise AssertionError("play save")
        session.ui.mode = "play"
        session.tick(Keys(pressed={"m"}), 0.05)
        if not session.state.muted:
            raise AssertionError("mute")
        session.tick(Keys(pressed={"esc"}), 0.05)
        if session.ui.mode != "pause":
            raise AssertionError("pause")
        session.tick(Keys(pressed={"esc"}), 0.05)
        if session.ui.mode != "play":
            raise AssertionError("resume")
        session.tick(Keys(pressed={"h"}), 0.05)
        if session.ui.mode != "help":
            raise AssertionError("help")
        session.tick(Keys(pressed={"right"}), 0.05)
        if session.ui.help_page != 1:
            raise AssertionError("help page")
        session.tick(Keys(pressed={"esc"}), 0.05)
        if session.ui.mode != "play":
            raise AssertionError("help did not close")
        names = [SPECIES_BY_ID[k].name for k, rec in session.state.journal.items() if rec.get("count")]
        print(f"play ok  traveled {session.state.traveled:.0f} m  species {', '.join(names) or 'none yet'}")
    finally:
        path.unlink(missing_ok=True)


def chart(dest: str) -> int:
    from .platform import Text
    world = World()
    text = Text()
    ui = UI(text, world)
    rgb = np.repeat(np.repeat(world.map_rgb, 2, axis=0), 2, axis=1)
    frame = rgb.copy()
    state = State.new(world, seed=1)
    ui._plot_boat(frame, state, 0, 0, frame.shape[1], frame.shape[0], radius=4)
    for name, x, z, _r in world.zones:
        u, v = world.map_pixel(x, z, frame.shape[1], frame.shape[0])
        ui._text(frame, name, u + 4, v - 8, 14, (236, 228, 206))
    write_png(dest, frame)
    print(dest)
    return 0


def shots(dest: str) -> int:
    from .platform import Text
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    world = World()
    text = Text()
    ui = UI(text, world)
    renderer = Renderer(world,1280,720)
    ui.fish_card_renderer = getattr(renderer, "fish_card", None)
    software_renderer = Renderer(world, 1280, 720, software=True)
    software_ui = UI(text, world)
    software_ui.fish_card_renderer = getattr(software_renderer, "fish_card", None)

    def grab(state, mode, name, **ui_kw):
        panel = UIState(mode=mode, has_save=True)
        for key, value in ui_kw.items():
            setattr(panel, key, value)
        t0 = time.perf_counter()
        low = renderer.render(state)
        ms = (time.perf_counter() - t0) * 1000.0
        big = resize_rgb(low,1280,720)
        ui.draw(big, state, panel)
        path = out / name
        write_png(path, big)
        print(f"{name:16s} {ms:6.1f} ms")
        return ms

    dawn = State.new(world, seed=2)
    grab(dawn, "title", "title.png")
    grab(dawn, "play", "dawn.png")

    morning = State.new(world, seed=2)
    _move(morning, 300.0, 30.0, math.pi / 2, (9.0 - 6.0) * 60.0)
    grab(morning, "play", "morning.png")

    noon = State.new(world, seed=2)
    # Just outside the lily shallows, looking back into the cove.
    _move(noon, -90.0, -40.0, math.atan2(-85.0, -75.0), (12.0 - 6.0) * 60.0)
    grab(noon, "play", "noon.png")

    sunset = State.new(world, seed=2)
    _move(sunset, 40.0, 10.0, -math.pi / 2, (18.6 - 6.0) * 60.0)
    grab(sunset, "play", "sunset.png")

    night = State.new(world, seed=2)
    night.light = True
    night.finder = True
    _move(night, 260.0, 10.0, math.pi / 2, (21.0 - 6.0) * 60.0)
    grab(night, "play", "night.png")

    shop = State.new(world, seed=2)
    shop.money = 86.50
    shop.game_minutes = 8 * 60
    shop.well.append(Catch("bluegill", 0.42, 1.0, 1.0, "flats", "worm", 10.0))
    shop.well.append(Catch("channel", 6.4, 0.72, 7.0, "cypress", "liver", 20.0))
    grab(shop, "shop", "shop.png", shop_tab=0, shop_i=0)

    check = State.new(world, seed=2)
    x, z, yaw = _pose(world, "flats", "worm")
    check.x, check.z, check.yaw = x, z, yaw
    check.game_minutes = 5 * 60
    err = check.try_set(world, 0, "worm")
    if err:
        raise AssertionError(err)
    check.anchored = True
    check._advance_hours(8, toast=False)
    if check.lines[0].fish_on() == 0:
        check.lines[0].hooks[0].catch = Catch("bluegill", 0.55, 1.0, 1.0, "flats", "worm", 11.0)
        check.lines[0].hooks[0].baited = False
        check.lines[0].hooks[3].catch = Catch("bullhead", 1.1, 1.0, 2.0, "flats", "worm", 11.0)
        check.lines[0].hooks[3].baited = False
    grab(check, "check", "check.png", check_line=0, check_i=0)

    def haul_fixture(*, fish=False, shiny=False):
        state = State.new(world, seed=17 + int(fish) + int(shiny))
        px, pz, yaw = _pose(world, "flats", "worm")
        _move(state, px, pz, yaw, 8 * 60)
        hooks = [Hook(True) for _ in range(12)]
        if fish:
            catch = Catch("bluegill", 0.75, 1.0, 0.0, "flats", "worm", 8.0,
                          shiny=shiny)
            hooks[0] = Hook(False, catch)
            state._note_journal(catch)
        if shiny:
            shiny_catch = Catch("channel", 2.4, 1.0, 0.0, "flats", "worm", 8.0,
                                shiny=True)
            hooks[5] = Hook(False, shiny_catch)
            state._note_journal(shiny_catch)
        state.lines = [SetLine("std", "worm", px, pz, px + 42, pz + 8,
                               "flats", hooks)]
        return state

    def grab_haul_gallery(target_renderer, target_ui, suffix):
        target_ui.fish_card_renderer = getattr(target_renderer, "fish_card", None)
        images = (
            ("mid", haul_fixture(fish=True),
             UIState(mode="haul", check_line=0, haul_index=6, haul_timer=0.13,
                     haul_counts_before={"bluegill": 0})),
            ("card", haul_fixture(fish=True),
             UIState(mode="haul", check_line=0, haul_index=0, haul_phase="card",
                     haul_counts_before={"bluegill": 0})),
            ("shiny", haul_fixture(shiny=True),
             UIState(mode="haul", check_line=0, haul_index=5, haul_phase="card",
                     haul_counts_before={"channel": 0})),
            ("summary", haul_fixture(fish=True, shiny=True),
             UIState(mode="check", check_line=0, check_i=0)),
        )
        for name, state, panel in images:
            low = target_renderer.render(state)
            frame = resize_rgb(low, 1280, 720)
            target_ui.draw(frame, state, panel)
            path = out / f"haul-{suffix}-{name}.png"
            write_png(path, frame)
            print(f"{path.name:24s} {getattr(target_renderer, 'backend', 'CPU fallback')}")

    gpu_label = "gl" if type(renderer).__name__ == "LakeRenderer" else "fallback"
    grab_haul_gallery(renderer, ui, gpu_label)
    grab_haul_gallery(software_renderer, software_ui, "software")
    from .fishmesh import fish_card_contact_sheet
    write_png(out / "fishcards.png", fish_card_contact_sheet(ui.fish_card_renderer))
    rain = State.new(world,seed=2)
    _move(rain,-90.0,-40.0,math.atan2(-85.0,-75.0),(18.0-6.0)*60.0+3*24*60)
    grab(rain,"play","rain.png")
    from .bookview import book_gallery
    book_gallery(out, text=text, world=world)
    from .ui import comfort_gallery
    comfort_gallery(out, text=text, world=world, background=renderer.render(dawn))
    from .kitchenview import kitchen_gallery
    kitchen_gallery(out, text=text, world=world, background=renderer.render(dawn))
    from .calendarview import calendar_gallery
    calendar_gallery(out, text=text, world=world, background=renderer.render(dawn))
    from .botview import bot_gallery
    bot_gallery(out, text=text, world=world, background=renderer.render(dawn))
    from .botshots import bot_shell_gallery
    bot_shell_gallery(out, text=text, renderer=renderer)
    renderer.close()
    software_renderer.close()
    text.close()
    print(out)
    return 0


def _move(state, x, z, yaw, minutes):
    state.x = x
    state.z = z
    state.yaw = yaw
    state.game_minutes = minutes
    state.speed = 0.0
    state.throttle = 0.0
    state.anchored = True
    state.look = -0.02
    state.tutorial = 4
    state.toasts.clear()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
