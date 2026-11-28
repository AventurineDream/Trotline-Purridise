"""Renderer regressions and a repeatable full-frame memory/performance check."""

from __future__ import annotations

import json
import math
import os
import re

import sys
import time
import tempfile
import types
from pathlib import Path

try:
    import resource
except ImportError:  # Windows: the resource module is Unix-only
    resource = None
import numpy as np

from . import detail as detail_tiers
from . import skipperlook
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
from . import calendar

MEMORY_LIMIT_BYTES = 3_000_000_000


def _windows_peak_rss_bytes() -> int:
    """Read the Windows process peak working set in bytes using psapi."""
    import ctypes
    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    process = ctypes.WinDLL("kernel32", use_last_error=True).GetCurrentProcess
    process.restype = wintypes.HANDLE
    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    get_memory = psapi.GetProcessMemoryInfo
    get_memory.argtypes = (
        wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD)
    get_memory.restype = wintypes.BOOL
    if not get_memory(process(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return int(counters.PeakWorkingSetSize)


def rss_bytes():
    """Return this process image's peak resident set size.

    Returns:
        Peak resident bytes from Linux VmHWM, Unix `resource`, or Windows PSAPI.
    """
    try:
        for line in Path("/proc/self/status").read_text().splitlines():
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError):
        pass
    if resource is None:
        return _windows_peak_rss_bytes()
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak * (1024 if os.name == "posix" and sys.platform.startswith("linux") else 1))


_DRM_UNITS = {"": 1, "KiB": 1024, "MiB": 1024**2, "GiB": 1024**3}


def drm_memory_bytes(fdinfo_texts):
    """Total GPU memory described by a process's DRM fdinfo records.

    Several descriptors usually share one DRM client (EGL opens the device more
    than once), and each repeats that client's totals, so clients are counted
    once. Values carry a unit suffix; a bare number is bytes.

    Args:
        fdinfo_texts: The contents of each ``/proc/<pid>/fdinfo/<fd>`` file.

    Returns:
        Resident bytes across all memory regions and clients (falling back to
        ``drm-total-*`` for drivers without resident accounting), or ``None``
        if no descriptor belongs to a DRM device.
    """
    clients = {}
    for text in fdinfo_texts:
        client = re.search(r"^drm-client-id:\s*(\S+)", text, re.M)
        if client is None:
            continue
        device = re.search(r"^drm-pdev:\s*(\S+)", text, re.M)
        sums = {}
        for kind, value, unit in re.findall(
                r"^drm-(resident|total)-\S+:\s*(\d+)[ \t]*(KiB|MiB|GiB)?", text, re.M):
            sums[kind] = sums.get(kind, 0) + int(value) * _DRM_UNITS[unit]
        if sums:
            key = (device.group(1) if device else "", client.group(1))
            clients[key] = sums.get("resident", sums.get("total", 0))
    return sum(clients.values()) if clients else None


def gpu_memory_bytes():
    """GPU memory this process holds, from the kernel's DRM accounting.

    Returns:
        Bytes (see `drm_memory_bytes`), or ``None`` where the platform or
        driver does not expose DRM fdinfo.
    """
    texts = []
    try:
        for path in Path("/proc/self/fdinfo").iterdir():
            try:
                texts.append(path.read_text())
            except OSError:
                continue
    except OSError:
        return None
    return drm_memory_bytes(texts)


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


# The lakes in visiting order. One renderer is resident at a time (06 §0.4), so each
# lake is a block of frames, and every boat gets a slice of its block.
LAKE_ORDER = ("briar", "cedar", "flathead", "crater", "nebula")
LEGENDARY_SCENE = "old_lantern"  # the legendary encounter the benchmark draws (V1-37)
WEATHER_SPAN_HOURS = 168 * 12  # twelve forecast weeks; each lake reaches its weathers well inside this

# 06 §7 budgets in MB, one per table row the benchmark estimates.
MEMORY_BUDGET_MB = {
    "terrain_zones_depth": 350,
    "foliage": detail_tiers.FOLIAGE_BUDGET_MB,
    "render_targets": 300,
    "cat_actors": 150,
    "fish_meshes_and_cards": 120,
    "boats": 80,
    "audio": 150,
    "ui_text_cache": 150,
    "content_and_state": 100,
}
MAX_NPC_BOATS = 14  # the actor cap: resident cats, each with a boat (06 §7)


def _slots(obj):
    names = []
    for klass in type(obj).__mro__:
        slots = getattr(klass, "__slots__", ())
        names.extend((slots,) if isinstance(slots, str) else slots)
    return names


def _deep_bytes(roots, skip=()) -> int:
    """Estimate the bytes reachable from `roots`.

    NumPy arrays count `nbytes`; everything else counts `sys.getsizeof`. Each object is
    counted once, so shared content is not double counted. Modules, classes, functions and
    the `skip` objects (the lake and the renderer, measured separately) are left out.
    """
    import functools
    leave_out = (type, types.ModuleType, types.FunctionType, types.BuiltinFunctionType,
                 types.MethodType, type(functools.lru_cache(lambda: 0)))
    seen = {id(obj) for obj in skip}
    stack, total = list(roots), 0
    while stack:
        obj = stack.pop()
        if id(obj) in seen or isinstance(obj, leave_out):
            continue
        seen.add(id(obj))
        if isinstance(obj, np.ndarray):
            total += obj.nbytes
            continue
        total += sys.getsizeof(obj)
        if isinstance(obj, dict):
            stack.extend(obj.keys())
            stack.extend(obj.values())
        elif isinstance(obj, (list, tuple, set, frozenset)):
            stack.extend(obj)
        else:
            attrs = getattr(obj, "__dict__", None)
            if attrs is not None:
                stack.append(attrs)
            stack.extend(getattr(obj, name) for name in _slots(obj) if hasattr(obj, name))
    return total


def _weather_minutes(seed, lake_id):
    """(weather, game minute) for each weather state this lake's forecast can show.

    The minute is the middle of the first planned hour with that weather. Mid-hour stays
    outside the 60-minute blend at each hour boundary, so the frame shows that weather alone.
    """
    first = {}
    for hour in range(WEATHER_SPAN_HOURS):
        minute = hour * 60 + 30
        first.setdefault(calendar.planned_weather(seed, lake_id, minute), minute)
    return sorted(first.items())


def foliage_bytes(renderer) -> int:
    """Bytes the renderer holds for trees and shore plants, from its real buffers.

    GL: the painted flora atlas at its real layer size, both textures with their mip chains.
    The cat-impostor reserve is left out because `actor_memory` already counts it. CPU: the
    sprite sheets and the prop positions. Counting layers at base size ignores the tier's
    atlas scale and mip chain, so this reads the atlas itself.

    Args:
        renderer: A `LakeRenderer` (GL) or `SoftwareRenderer` (CPU).

    Returns:
        Estimated bytes, as an int.
    """
    atlas = getattr(renderer, "flora_atlas", None)
    if atlas is not None:
        return int(atlas.memory_bytes(include_reserve=False))
    total = sum(sprite.nbytes for sprite in getattr(renderer, "sprites", {}).values())
    return total + getattr(getattr(renderer, "prop_positions", None), "nbytes", 0)


def _memory_report(renderer, world, state, text, mesh_bytes, audio_bytes) -> dict:
    """Per-subsystem MB estimates for the 06 §7 table, each beside its budget.

    These are estimates, not allocator measurements: NumPy `nbytes`, `sys.getsizeof`
    walks, and the renderer's own bounds. Process RSS is reported separately.
    """
    from .boatmesh import boat_faces
    from .content import load_content, load_content_v2
    from .fishmesh import cache_bytes as card_cache_bytes
    mb = 1024 ** 2
    # Terrain: every array the lake holds (height grid, map images, zone and depth grids).
    terrain = _deep_bytes([world], skip=(renderer,))
    # Foliage: the GL flora atlas, or the CPU sprite sheets and prop positions.
    foliage = foliage_bytes(renderer)
    # Render targets at the 1440x810, 4x MSAA target size: colour and depth per sample
    # (4 + 4 bytes), a full-size RGBA16F post target (8 bytes), and a half-size reflection
    # target (4 bytes). The CPU renderer also keeps its colour, depth and bayer arrays.
    targets = 1440 * 810 * 4 * (4 + 4) + 1440 * 810 * 8 + 720 * 405 * 4
    targets += sum(getattr(renderer, name).nbytes for name in ("col", "z", "bayer") if hasattr(renderer, name))
    # Cat actors: the renderer's own bound (resident actors, mesh cache, portraits, GPU slots).
    actors = renderer.actor_memory()["total_bytes_bound"]
    # Fish: cached card and thumbnail pixels, plus the haul meshes built for the card pass
    # (the largest measured mesh times the number cached, an upper-side estimate).
    fish = card_cache_bytes() + mesh_bytes
    # Boats: one boat's face arrays, largest over all 24 boats, for the player and 14 NPC boats.
    current = state.boat_id
    per_boat = 0
    try:
        for boat_id in BOATS:
            state.boat_id = boat_id
            per_boat = max(per_boat, _deep_bytes(boat_faces(state)))
    finally:
        state.boat_id = current
    boats = (1 + MAX_NPC_BOATS) * per_boat
    # Audio: every sound's buffer and each lake's bed, from the soundscape coverage report.
    audio = audio_bytes
    # UI text: the bounded text cache the UI draws from.
    ui_text = text.cache_bytes
    # Content and state: the save state and both loaded content sets, each object once.
    content = _deep_bytes([state, load_content(), load_content_v2()], skip=(world, renderer, text))
    estimates = {"terrain_zones_depth": terrain, "foliage": foliage, "render_targets": targets,
                 "cat_actors": actors, "fish_meshes_and_cards": fish, "boats": boats,
                 "audio": audio, "ui_text_cache": ui_text, "content_and_state": content}
    report = {name: {"estimate_mb": round(value / mb, 2), "budget_mb": MEMORY_BUDGET_MB[name]}
              for name, value in estimates.items()}
    return report


def _catchability_section(witnesses) -> dict:
    """Per-species catchability from the real-map witnesses (specieschecks, 02 §4)."""
    best = {}
    for row in witnesses:
        if row["species"] not in best or row["ratio"] > best[row["species"]]["ratio"]:
            best[row["species"]] = {key: row[key] for key in ("lake", "zone", "rate", "default_rate", "ratio")}
    return {"species": {sid: best[sid] for sid in sorted(best)}, "species_count": len(best),
            "witnesses": len(witnesses), "min_ratio": round(min(row["ratio"] for row in best.values()), 4)}


COVERAGE_SEED = 24  # the save seed the benchmark and the coverage pass both use


def scope_fish_ids() -> tuple:
    """Every fish card the benchmark and the coverage pass paint: 144 species, then 12 legendaries."""
    from .fishmesh import legendary_ids
    return (*(row.id for row in SPECIES), *legendary_ids())


def scope_cat_ids() -> tuple:
    """Each roster row, once. A twin row is one actor with two cats (see `cat_models`)."""
    from .actors import roster
    return tuple(roster())


def scope_cat_models() -> int:
    """Cat models in the roster, twins included (52 in the current content)."""
    from .actors import roster
    return sum(1 + ("twin" in row["appearance"]) for row in roster().values())


def _weather_states_reached(seed=COVERAGE_SEED) -> set:
    """The weather states the forecast reaches on any lake, with no rendering."""
    return {weather for lake_id in LAKE_ORDER for weather, _minute in _weather_minutes(seed, lake_id)}


def coverage_checks(*, software=False) -> dict:
    """The self-test's coverage pass: the benchmark's scope list, without the frame loop (V1-39).

    Lakes render one frame each. Every fish card and every roster cat model is built.
    Every shop tab, help page and book tab is drawn once, and the legendary haul scene is
    drawn once. The weather list is checked from the forecast alone. Raises on any miss.
    """
    from .content import WEATHER_STATES
    from .fishmesh import fish_card, haul_mesh
    from .catmesh import cat_mesh
    from .legendshots import _draw as draw_scene, _panel as scene_panel, _staged
    from .platform import Text
    if len(BOATS) != 24:
        raise AssertionError(f"expected 24 boats, found {len(BOATS)}")
    text = Text()
    counts = {"lakes": 0, "fish_cards": 0, "cat_models": 0, "shop_tabs": 0,
              "help_pages": 0, "book_tabs": 0, "weather_states": 0, "legendary_scenes": 0}
    try:
        for lake_id in LAKE_ORDER:
            world = World(lake_id)
            renderer = Renderer(world, software=software)
            try:
                state = State.new(world, seed=COVERAGE_SEED)
                low = renderer.render(state)
                if float(low.std()) < 8:
                    raise AssertionError(f"{lake_id} frame is flat")
                counts["lakes"] += 1
                if lake_id != LAKE_ORDER[0]:
                    continue
                # Shop, help and book tabs, drawn the way the benchmark selects them.
                ui = UI(text, world)
                panels = [UIState(mode="shop", has_save=True, shop_tab=tab, shop_i=0)
                          for tab in range(len(SHOP_TABS))]
                panels += [UIState(mode="journal", has_save=True, journal_page=page, journal_i=0,
                                   book_entry_i=0, journal_quest_i=0) for page in range(len(BOOK_TABS))]
                for panel in panels:
                    frame = resize_rgb(low, 1440, 810)
                    ui.draw(frame, state, panel)
                    if frame.shape != (810, 1440, 3):
                        raise AssertionError(f"{panel.mode} frame has shape {frame.shape}")
                    if panel.mode == "shop":
                        counts["shop_tabs"] += 1
                    else:
                        counts["book_tabs"] += 1
                # The Field Guide, spread by spread until it wraps, so every help page is drawn.
                guide = UIState(mode="help", has_save=True)
                shown = set()
                while True:
                    frame = resize_rgb(low, 1440, 810)
                    ui.draw(frame, state, guide)
                    if frame.shape != (810, 1440, 3):
                        raise AssertionError(f"help frame has shape {frame.shape}")
                    shown.update(guide.help_shown)
                    guide.help_spread += 1
                    if guide.help_spread >= guide.help_spreads:
                        break
                counts["help_pages"] = len(shown)
                # The legendary encounter's haul scene, in its encounter phase.
                scene_state = _staged(world, LEGENDARY_SCENE)
                scene_ui = UI(text, world)
                scene_ui.fish_card_renderer = getattr(renderer, "fish_card", None)
                scene = draw_scene(renderer, scene_ui, scene_state, scene_panel(LEGENDARY_SCENE, "encounter", 2.2))
                if float(scene.std()) < 8:
                    raise AssertionError(f"{LEGENDARY_SCENE} scene is flat")
                counts["legendary_scenes"] += 1
            finally:
                renderer.close()
        for sid in scope_fish_ids():
            if fish_card(sid).size == 0:
                raise AssertionError(f"fish card {sid} is empty")
            # The haul mesh is cheap enough for every fish (about 9 s for all 156).
            if haul_mesh(sid).triangle_count == 0:
                raise AssertionError(f"fish {sid} has an empty haul mesh")
            counts["fish_cards"] += 1
        for npc_id in scope_cat_ids():
            counts["cat_models"] += len(cat_mesh(npc_id).cats)
        if counts["cat_models"] != scope_cat_models():
            raise AssertionError(f"{counts['cat_models']} cat models, expected {scope_cat_models()}")
        reached = _weather_states_reached(COVERAGE_SEED)
        if reached != set(WEATHER_STATES):
            raise AssertionError(f"weather states reached {sorted(reached)}, "
                                 f"missing {sorted(set(WEATHER_STATES) - reached)}")
        counts["weather_states"] = len(reached)
        expected = scope_counts()
        for name, value in expected.items():
            if counts[name] != value:
                raise AssertionError(f"coverage {name}: {counts[name]} of {value}")
        print(f"coverage ok  {counts['lakes']} lakes, {len(BOATS)} boats, {counts['fish_cards']} fish cards, "
              f"{counts['cat_models']} cat models, {counts['shop_tabs']} shop tabs, {counts['help_pages']} help pages, "
              f"{counts['book_tabs']} book tabs, {counts['weather_states']} weather states, "
              f"{counts['legendary_scenes']} legendary scene")
        return counts
    finally:
        text.close()


def scope_counts() -> dict:
    """The expected count of each coverage item, shared by the benchmark and the self-test."""
    from .content import WEATHER_STATES
    return {"lakes": len(LAKE_ORDER), "fish_cards": len(scope_fish_ids()),
            "cat_models": scope_cat_models(), "shop_tabs": len(SHOP_TABS), "help_pages": HELP_N,
            "book_tabs": len(BOOK_TABS), "weather_states": len(WEATHER_STATES),
            "legendary_scenes": 1}


def _benchmark_play_loop(world, state, text, software):
    """Measure the full-size GPU output pass and play-UI composition."""
    report = {}
    for width, height in ((1200, 675), (1440, 810)):
        render_width, render_height = detail_tiers.render_dimensions(
            width, height, software=software)
        renderer = Renderer(world, render_width, render_height, software=software,
                            output_size=(width, height))
        ui = UI(text, world)
        panel = UIState(mode="play", has_save=True)
        full_ms, render_ms = [], []
        try:
            for frame_i in range(60):
                start = time.perf_counter()
                cam = renderer.camera_for(state)
                low = renderer.render(state, cam)
                big = low if low.shape[:2] == (height, width) else resize_rgb(low, width, height)
                ui.draw(big, state, panel, cam)
                if frame_i >= 10:
                    full_ms.append((time.perf_counter() - start) * 1000)
                    render_ms.append(renderer.last_ms)
            report[f"{width}x{height}"] = {
                "frames": len(full_ms),
                "full_frame_p50_ms": round(float(np.percentile(full_ms, 50)), 3),
                "full_frame_p95_ms": round(float(np.percentile(full_ms, 95)), 3),
                "render_call_p50_ms": round(float(np.percentile(render_ms, 50)), 3),
                "render_cpu_p50_ms": None,
                "true_gpu_p50_ms": None,
            }
        finally:
            renderer.close()
    return report

def benchmark(frames=1200, dest="shots/benchmark.json", software=False):
    """Benchmark renderer/UI throughput and memory bounds.

    Args:
        frames: Full benchmark frame count; at least 60.
        dest: JSON report destination.
        software: Whether to use CPU rendering instead of OpenGL.

    Returns:
        Zero after writing and printing the benchmark report.
    """
    if frames<60:
        raise ValueError("Use at least 60 frames for a meaningful benchmark")
    from .content import WEATHER_STATES
    from .actors import roster
    from .catmesh import cat_mesh
    from .fishmesh import fish_card, haul_mesh, legendary_ids
    from .specieschecks import validate_catchability
    from .legendshots import _draw as draw_scene, _panel as scene_panel, _staged
    render_width, render_height = detail_tiers.render_dimensions(1440, 810, software=software)
    world = World(LAKE_ORDER[0])
    renderer = Renderer(world, render_width, render_height, software=software,
                        output_size=(1440, 810))
    text = Text()
    ui = UI(text,world)
    state = State.new(world,seed=24)
    # Pin the forecast to the save seed, so the weather each frame shows is fixed for the run.
    state.v2.setdefault("calendar", {})["seed"] = calendar.forecast_seed(state)
    # The lake's cats are present, so actors and portraits count in time and memory.
    from .content import load_content
    from .npcs import active_npcs
    npc_content = load_content()
    state.npcs = active_npcs(state,world,npc_content)
    actor_peak = 0
    state.lines = _stress_lines()
    state.light = state.finder = True
    state.well_tier = 2
    state.toasts.clear()
    panel = UIState(mode="play",has_save=True)
    try:
        graphics_checks(renderer,world)
        modes = ("play","map","shop","setbait","check","journal","well","pause","help","title","dialogue")
        # Two journal blocks per cycle keep all 144 fish and twelve quests
        # reachable in the existing 1,200-frame coverage run.
        mode_cycle = (*modes[:6], "journal", *modes[6:])
        locations = ((-90,-40,-2.3),(300,30,math.pi/2),(40,10,-math.pi/2),(0,0,0))
        minutes = (0,180,360,756,900,3*1440+600,3*1440+1050,3*1440+1110)
        frame_ms,render_ms,samples = [],[],[]
        mode_ms = {mode:[] for mode in modes}
        mode_frames = {mode:0 for mode in modes}
        boat_order = tuple(BOATS)
        lake_boat_ms = {f"{lake}/{boat}":[] for lake in LAKE_ORDER for boat in boat_order}
        weather_plan = {lake: _weather_minutes(calendar.forecast_seed(state), lake) for lake in LAKE_ORDER}
        cats = roster()
        cat_models = sum(1 + ("twin" in row["appearance"]) for row in cats.values())
        coverage = {name:set() for name in ("modes", "lake_boat_pairs", "shop_tabs",
                                           "help_pages", "fish_journal", "quest_journal", "book_tabs",
                                           "dialogue_givers", "dialogue_statuses", "fish_cards",
                                           "cat_models", "weather_states", "legendary_scenes")}

        # Every fish card, legendaries included, painted once outside the frame loop.
        # The haul mesh for each is built too, so the fish memory estimate has real meshes.
        mesh_bytes = 0
        for species_id in scope_fish_ids():
            fish_card(species_id)
            mesh_bytes = max(mesh_bytes, haul_mesh(species_id).nbytes)
            coverage["fish_cards"].add(species_id)
        # Every roster cat's model, twins included (each roster row is one actor).
        for npc_id in cats:
            mesh = cat_mesh(npc_id)
            for index in range(len(mesh.cats)):
                coverage["cat_models"].add(f"{npc_id}/{index}")
        # The legendary encounter's haul scene, in its encounter phase, on its own lake.
        scene_state = _staged(world, LEGENDARY_SCENE)
        scene_ui = UI(text, world)
        scene_ui.fish_card_renderer = getattr(renderer, "fish_card", None)
        draw_scene(renderer, scene_ui, scene_state, scene_panel(LEGENDARY_SCENE, "encounter", 2.2))
        coverage["legendary_scenes"].add(LEGENDARY_SCENE)

        for i in range(frames):
            block = max(1, frames // len(LAKE_ORDER))
            lake_id = LAKE_ORDER[min(len(LAKE_ORDER) - 1, i // block)]
            if world.id!=lake_id:
                renderer_to_close = renderer
                renderer = None
                renderer_to_close.close()
                world = World(lake_id)
                state.bind(world)
                state.npcs = active_npcs(state,world,npc_content)
                renderer = Renderer(world,render_width,render_height,software=software,
                                    output_size=(1440, 810))
                ui = UI(text,world)
            t0 = time.perf_counter()
            state.anim = i/30
            if world.id=="cedar":
                spots = [row for row in world.zones if row[0] in ("deep","lilies","inlet","cypress")]
                spot = spots[(i//60)%len(spots)]
                state.x,state.z,state.yaw = spot[1],spot[2],locations[(i//60)%len(locations)][2]
            else:
                state.x,state.z,state.yaw = locations[(i//60)%len(locations)]
            # Each lake block gives every boat its own slice, so all 24 boats visit all five lakes.
            slot = i % block
            state.boat_id = boat_order[slot * len(boat_order) // block]
            # Exercise oars, powered travel and the depleted-battery fallback.
            rowboat_variant = (i//8)%3  # all three within the rowboat's slice
            state.rowboat_trolling_motor = rowboat_variant!=0
            state.rowboat_battery_kwh = (ROWBOAT_BATTERY_KWH*(0.1+0.8*((i%100)/100))
                                         if rowboat_variant==1 else 0.0)
            state.sail_raised = state.boat.power=="sail" and (i//20)%2==1
            state.fuel = state.boat.tank*(0.1+0.8*((i%100)/100))
            state.yaw += math.sin(i*0.02)*0.18
            state.look = math.sin(i*0.03)*0.12
            state.steer = math.sin(i*0.015)*0.3
            # Advance lighting at 12x within each block, including rain onset
            # and the midnight crossfade, while keeping every allocation cap.
            state.game_minutes = minutes[(i//90)%len(minutes)] + (i%90)*12/30
            # The first frames of each lake block show each weather that lake's forecast reaches.
            if slot < len(weather_plan[lake_id]):
                state.game_minutes = weather_plan[lake_id][slot][1]
            state.speed = 1.8
            state.anchored = False
            panel.mode = mode_cycle[(i//20)%len(mode_cycle)]
            # Advance within each mode independently. Coupling selectors to
            # the outer frame block silently skipped half of the old menus.
            visit = mode_frames[panel.mode]
            mode_frames[panel.mode] += 1
            panel.shop_tab = visit%len(SHOP_TABS)
            panel.help_spread = visit  # the guide wraps it into its spread count
            legacy_pages = len(SPECIES) + len(QUEST_IDS)
            journal_visit = visit % (legacy_pages + 4)
            panel.journal_page = ((1, 2, 4, 5)[journal_visit - legacy_pages]
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
                for slot_name,paints in PAINT.items():
                    state.look_paint[slot_name] = paints[(i//60)%len(paints)][0]
            low = renderer.render(state)
            big = low if low.shape[:2] == (810, 1440) else resize_rgb(low,1440,810)
            ui.draw(big,state,panel)
            coverage["modes"].add(panel.mode)
            coverage["lake_boat_pairs"].add(f"{world.id}/{state.boat_id}")
            coverage["weather_states"].add(calendar.weather_at(state))
            if panel.mode=="shop":
                coverage["shop_tabs"].add(panel.shop_tab)
            elif panel.mode=="help":
                coverage["help_pages"].update(panel.help_shown)
            elif panel.mode=="journal":
                coverage["book_tabs"].add(panel.journal_page)
                if panel.journal_page in (0, 3):
                    coverage["quest_journal" if panel.journal_page == 3 else "fish_journal"].add(
                        panel.journal_quest_i if panel.journal_page == 3 else panel.journal_i)
            if low.dtype!=np.uint8 or not np.isfinite(low).all():
                raise AssertionError("invalid frame")
            if text.cache_bytes>text.cache_limit:
                raise AssertionError("text cache exceeded its memory budget")
            gpu_bytes = gpu_memory_bytes()
            if rss_bytes() + (gpu_bytes or 0) >= MEMORY_LIMIT_BYTES:
                raise AssertionError("game exceeded 3 GB combined process/GPU memory")
            actors = renderer.actor_memory()
            actor_peak = max(actor_peak,actors["total_bytes_bound"])
            if actors["resident_actors"]>actors["max_actors"] or actor_peak>actors["budget_bytes"]:
                raise AssertionError(f"cat actors exceeded their budget: {actors}")
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
                             "dialogue_givers":len(QUEST_IDS), "dialogue_statuses":4,
                             "fish_cards":len(scope_fish_ids()), "cat_models":cat_models,
                             "weather_states":len(WEATHER_STATES), "legendary_scenes":1}
        coverage_complete = all(len(coverage[name])==count for name,count in expected_coverage.items())
        if frames>=1200 and not coverage_complete:
            counts = {name:len(values) for name,values in coverage.items()}
            raise AssertionError(f"incomplete benchmark coverage: {counts}")
        # Every sound, every lake's ambience, captions and the audio budget (V1-38).
        from .soundscape import coverage_report
        audio = coverage_report()
        if not audio["complete"] or not audio["within_budget"]:
            raise AssertionError(f"incomplete audio coverage: {audio}")
        memory = _memory_report(renderer, world, state, text, mesh_bytes, audio["bytes"])
        over_budget = {name: row for name, row in memory.items()
                       if isinstance(row, dict) and "budget_mb" in row and row["estimate_mb"] > row["budget_mb"]}
        if over_budget:
            raise AssertionError(f"memory estimates over the 06 §7 budget: {over_budget}")
        catchability = _catchability_section(validate_catchability())
        if catchability["species_count"] != len(SPECIES):
            raise AssertionError(f"catchability covers {catchability['species_count']} species")
        renderer_report = {
            "backend": renderer.backend,
            "render_size": [renderer.w, renderer.h],
            "window_size": [1440, 810],
            "output_size": [1440, 810],
            "antialias_samples": getattr(renderer, "samples", 1),
            "cat_actor_memory": {**renderer.actor_memory(), "peak_total_bytes_bound": actor_peak},
        }
        renderer_to_close = renderer
        renderer = None
        renderer_to_close.close()
        play_loop = _benchmark_play_loop(world, state, text, software)
        gpu_bytes = gpu_memory_bytes()
        report = {
            "frames":frames,**renderer_report,
            "render_median_ms":round(float(np.median(render_ms)),2),
            "full_frame_median_ms":round(float(np.median(frame_ms)),2),
            "full_frame_p50_ms":round(float(np.percentile(frame_ms,50)),2),
            "full_frame_p95_ms":round(float(np.percentile(frame_ms,95)),2),
            "play_loop":play_loop,
            "mode_median_ms":{mode:round(float(np.median(values)),2) for mode,values in mode_ms.items() if values},
            "lake_boat_median_ms":{mode:round(float(np.median(values)),2) for mode,values in lake_boat_ms.items() if values},
            "peak_rss_mb":round(rss_bytes()/1024**2,2),
            "gpu_resident_mb":None if gpu_bytes is None else round(gpu_bytes/1024**2,2),
            "ram_limit_bytes":MEMORY_LIMIT_BYTES,
            "text_cache_limit_bytes":text.cache_limit,
            "memory_mb":memory,
            "memory_samples":samples,
            "audio":{"sounds":len(audio["kinds"]),
                     "lakes":{lake:row["ambience"] for lake,row in audio["lakes"].items()},
                     "buffer_mb":round(audio["bytes"]/1024**2,2),
                     "budget_mb":round(audio["budget_bytes"]/1024**2,2),
                     "complete":audio["complete"]},
            "catchability":catchability,
            "coverage":{name:sorted(values) for name,values in coverage.items()},
            "coverage_expected":expected_coverage,
            "coverage_complete":coverage_complete,
            "checks":["fixed anchored depth","matching camera projections","eleven UI modes, including dialogue",
                      f"all {len(LAKE_ORDER)} lakes with repeated renderer release and rebuild",
                      f"all {len(BOATS)} boats on every lake, and raised sails",
                      f"eight shop tabs, {HELP_N} help pages, {len(SPECIES)} fish and 12 quest journal entries",
                      "twelve dialogue givers and four saved quest statuses","changing fuel and battery gauges",
                      f"every forecast weather state ({len(WEATHER_STATES)}), with 12x midnight fades",
                      "five heavy lines and fifteen buoys",
                      "all paint colors","changing look and steering","bounded text cache",
                      "each lake's cats resident within 14 actors and 150 MiB",
                      f"{len(legendary_ids())} legendary and {len(SPECIES)} species fish cards, with haul meshes",
                      f"all {cat_models} roster cat models, twins included",
                      f"legendary encounter haul scene ({LEGENDARY_SCENE})",
                      "per-subsystem memory against the 06 section 7 budgets",
                      "every sound captioned and heard, five lakes' ambience, audio within 150 MiB",
                      "catchability witnesses for every species"],
        }
        path = Path(dest)
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(report,indent=2)+"\n")
        print(json.dumps({k:v for k,v in report.items() if k not in ("memory_samples","checks","catchability","coverage","coverage_expected")},indent=2))
        return 0
    finally:
        try:
            if renderer is not None:
                renderer_to_close = renderer
                renderer = None
                renderer_to_close.close()
        finally:
            text.close()


def window_smoke():
    """Exercise the actual window and game session with a temporary save."""
    from .audio import Audio, shutdown_stores
    from .game import Keys,Session
    from .platform import Platform
    from .pngsave import write_png
    world = World()
    platform = Platform(1280,720,f"{GAME_TITLE} — visual check",verify_pixels=True)
    text = Text()
    renderer = Renderer(world,1280,720,software=platform.context is None,context=platform.context)
    try:
        audio = Audio()
        ui = UI(text,world)
    except BaseException:
        # Setup failed before the main try exists: stop shared stores first, as quit does (#168).
        shutdown_stores()
        raise
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
                elif session.ui.mode == "skipper" and elapsed>=0.4:
                    # The smoke run keeps the default look: Done is the creator's last row.
                    session.ui.skipper_i = len(skipperlook.ROWS)-1
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
        # Stop shared builds before the interpreter joins threads, as game.run does (#168).
        shutdown_stores()
        audio.close()
        renderer.close()
        text.close()
        platform.close()
