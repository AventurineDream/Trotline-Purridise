"""`--shots PATH --cats`: the 52-cat lineup with portraits, and the cats in the world (V1-29).

Writes the lineup and portrait sheets, a pose, pattern and LOD sheet, the lakes'
resident cats from the player's boat in both renderers, the Skipper's paws and
calm-water reflection, a dialogue portrait, chart pins, and `benchmark.json` with
triangle counts, timings, the actor budget and the hailing checks.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import time
from types import SimpleNamespace

import numpy as np

from . import actors, catart, catmesh
from .anchors import Anchor
from .camera import Camera
from .content import load_content, load_content_v2
from .dialogue import HAIL_RANGE_M, HAIL_SPEED_MPS, nearby_npc
from .fishmesh import _tiny_label
from .imageops import resize_rgb
from .npcs import NPC, active_npcs
from .pngsave import write_png
from .sim import State
from .verify import MEMORY_LIMIT_BYTES, rss_bytes
from .world import World

LAKES = ("briar", "cedar")
CELL = 192
INK = (54, 58, 48)


def _sheet(cells, cols, fill=(224, 215, 193)):
    height, width = cells[0].shape[:2]
    rows = math.ceil(len(cells) / cols)
    sheet = np.empty((rows * height, cols * width, 3), np.uint8)
    sheet[:] = fill
    for index, cell in enumerate(cells):
        row, col = divmod(index, cols)
        sheet[row * height:(row + 1) * height, col * width:(col + 1) * width] = cell
    return sheet


def _tag(backend):
    return "GL" if backend == "native" else "CPU"


def _u8(image):
    return np.clip(image * 255 + 0.5, 0, 255).astype(np.uint8)


def _body(npc_id, size=CELL, lod=catmesh.LOD0, weights=None, yaw=0.6):
    mesh = catmesh.cat_mesh(npc_id, lod)
    image, _mask = catart.rasterize(mesh, weights or catart._pose_weights(mesh), size, size, yaw=yaw, pitch=0.15)
    return _u8(image)


def _labelled(image, label, color=INK):
    cell = np.ascontiguousarray(image).copy()
    _tiny_label(cell, label, 6, 6, color)
    return cell


def _lineup(out, roster):
    """Every actor's full figure above its dialogue portrait."""
    cells, portraits, build_ms, portrait_ms = [], [], [], []
    for npc_id, row in roster.items():
        catmesh.clear_caches()
        start = time.perf_counter()
        catmesh.cat_mesh(npc_id, catmesh.LOD0)
        catmesh.cat_mesh(npc_id, catmesh.LOD1)
        build_ms.append((time.perf_counter() - start) * 1000)
        start = time.perf_counter()
        card = catart.portrait(npc_id)
        portrait_ms.append((time.perf_counter() - start) * 1000)
        small = resize_rgb(card, CELL, CELL)
        figure = _labelled(_body(npc_id), row["name"].upper())
        cells.append(np.concatenate([figure, small], axis=0))
        portraits.append(_labelled(small, row["name"].upper()))
    write_png(out / "cats-lineup.png", _sheet(cells, 9))
    write_png(out / "cats-portraits.png", _sheet(portraits, 9))
    return build_ms, portrait_ms


def _by(roster, key, values):
    """The first roster cat for each value of an appearance field."""
    picks = {}
    for npc_id, row in roster.items():
        value = row["appearance"][key]
        if value in values and value not in picks:
            picks[value] = npc_id
    return [(value, picks[value]) for value in values if value in picks]


def _poses_patterns_lods(out, roster):
    cells = [_labelled(_body(npc_id), f"{pose.upper()}  {roster[npc_id]['name'].upper()}")
             for pose, npc_id in _by(roster, "pose", catmesh.POSES)]
    # The approach wave, blended in as the player closes from 40 m to 30 m.
    sitter = next(npc_id for npc_id, row in roster.items() if row["appearance"]["pose"] == "sit_fish")
    mesh = catmesh.cat_mesh(sitter, catmesh.LOD0)
    for blend in (0.0, 0.5, 1.0):
        weights = catart._pose_weights(mesh, blend)
        cells.append(_labelled(_body(sitter, weights=weights), f"WAVE BLEND {blend:.1f}"))
    write_png(out / "cats-poses.png", _sheet(cells, 4))
    cells = [_labelled(_body(npc_id), f"{pattern.upper()}  {roster[npc_id]['name'].upper()}")
             for pattern, npc_id in _by(roster, "pattern", catmesh.PATTERNS)]
    write_png(out / "cats-patterns.png", _sheet(cells, 5))
    rows = []
    for npc_id in ("grandmother_whiskers", "captain_huckleberry", "pip_pebble", "astra_9"):
        if npc_id not in roster:
            continue
        lod0 = _labelled(_body(npc_id), "LOD0")
        lod1 = _labelled(_body(npc_id, lod=catmesh.LOD1), "LOD1")
        sprite, _w, _h, _b = catart.impostor(npc_id)
        alpha = sprite[..., 3:4] / 255.0
        flat = (sprite[..., :3] * alpha + np.asarray((224, 215, 193)) * (1 - alpha)).astype(np.uint8)
        side = max(sprite.shape[:2])
        pad = np.empty((side, side, 3), np.uint8)
        pad[:] = (224, 215, 193)
        y0, x0 = side - sprite.shape[0], (side - sprite.shape[1]) // 2
        pad[y0:, x0:x0 + sprite.shape[1]] = flat
        imp = _labelled(resize_rgb(pad, CELL, CELL), "IMPOSTOR")
        rows.append(np.concatenate([lod0, lod1, imp], axis=1))
    write_png(out / "cats-lod.png", np.concatenate(rows, axis=0))


def _water_spot(world, x, z, distance, prefer):
    """A player position `distance` from (x, z) on open water, preferring direction `prefer`."""
    for step in range(32):
        k = (step + 1) // 2 * (1 if step % 2 else -1)
        angle = prefer + k * math.tau / 32
        px, pz = x + math.sin(angle) * distance, z + math.cos(angle) * distance
        if float(world.shore_sd(np.float32(px), np.float32(pz))) < -4.0:
            return px, pz, angle
    return x + math.sin(prefer) * distance, z + math.cos(prefer) * distance, prefer


def _place_player(state, world, actor, distance):
    px, pz, angle = _water_spot(world, actor.x, actor.z, distance, actor.yaw + 0.5)
    state.x, state.z = px, pz
    state.yaw = math.atan2(actor.x - px, actor.z - pz)
    state.speed, state.anchored = 0.0, True


def _world(out, renderers, content):
    """Each lake's resident cats from the player's boat, plus a close look, in each renderer."""
    tiles, report = [], {}
    for lake in LAKES:
        world = World(lake)
        state = State.new(world, seed=3)
        state.game_minutes = 10 * 60
        state.npcs = active_npcs(state, world, content)
        for backend, make in renderers:
            renderer = make(world)
            try:
                present = renderer.actor_cache.sync(state.npcs, actors.roster())
                for actor in present:
                    for label, distance in (("approach", 14.0), ("hail", 8.0)):
                        _place_player(state, world, actor, distance)
                        hail = nearby_npc(state)
                        frame = renderer.render(state)
                        tile = _labelled(resize_rgb(frame, 480, 270),
                                         f"{_tag(backend)} {label} {actor.name.split()[0]}", (240, 236, 210))
                        write_png(out / f"world-{lake}-{actor.npc_id}-{label}-{backend}.png", frame)
                        tiles.append(tile)
                        report[f"{lake}/{actor.npc_id}/{label}/{backend}"] = {
                            "distance_m": distance, "hail_available": hail is not None and hail.id == actor.npc_id,
                            "position": [round(actor.x, 2), round(actor.y, 3), round(actor.z, 2)],
                            "boat": actor.boat_id}
                    # A long-lens look from the hail spot, with the player's own boat out of frame.
                    eye = state.boat.eye_height
                    dist = math.hypot(actor.x - state.x, actor.z - state.z)
                    cam = Camera(state.x, eye, state.z, state.yaw, math.atan2(actor.y + 0.3 - eye, dist), 0.0,
                                 2 * math.atan(1.6 / dist), renderer.w, renderer.h, build_rays=backend == "software")
                    frame = renderer.render(state, cam)
                    tiles.append(_labelled(resize_rgb(frame, 480, 270),
                                           f"{_tag(backend)} close {actor.name.split()[0]}", (240, 236, 210)))
                    write_png(out / f"world-{lake}-{actor.npc_id}-close-{backend}.png", frame)
                report[f"{lake}/{backend}/memory"] = renderer.actor_memory()
            finally:
                renderer.close()
    write_png(out / "cats-world.png", _sheet(tiles, 3, (20, 24, 26)))
    return report


def _skipper(out, renderers):
    """The paws for each grip, and the head reflection idle against moving."""
    world = World("briar")
    cases = (("jon", {}), ("rowboat", {}), ("rowboat", {"rowboat_trolling_motor": True}), ("sail", {}),
             ("log_raft", {}), ("dory", {}), ("river_runner", {"steer": 0.5}), ("jon", {"hauling": True}))
    tiles = []
    for backend, make in renderers:
        renderer = make(world)
        try:
            for boat_id, extra in cases:
                state = State.new(world, seed=3)
                state.game_minutes = 10 * 60
                state.boat_id = boat_id
                for key, value in extra.items():
                    setattr(state, key, value)
                label = f"{_tag(backend)} {boat_id} {' '.join(k.split('_')[-1] for k in extra)}"
                tiles.append(_labelled(resize_rgb(renderer.render(state), 480, 270), label, (240, 236, 210)))
            state = State.new(world, seed=3)
            state.game_minutes = 10 * 60
            for speed in (0.0, 1.5):
                state.speed = speed
                frame = renderer.render(state)
                write_png(out / f"reflection-{'idle' if speed == 0 else 'moving'}-{backend}.png", frame)
                tiles.append(_labelled(resize_rgb(frame, 480, 270),
                                       f"{_tag(backend)} reflection {'idle' if speed == 0 else 'moving'}",
                                       (240, 236, 210)))
        finally:
            renderer.close()
    write_png(out / "skipper.png", _sheet(tiles, 5, (20, 24, 26)))


def _dialogue_and_chart(out, content):
    from .platform import Text
    from .ui import UI, UIState
    from .software import SoftwareRenderer

    text = Text()
    try:
        for lake in LAKES:
            world = World(lake)
            state = State.new(world, seed=3)
            state.npcs = active_npcs(state, world, content)
            ui = UI(text, world)
            background = SoftwareRenderer(world, 480, 270).render(state)
            host = state.npcs[0]
            node = next(k for k, v in ui.narrative_content.dialogue.items() if v.get("choices"))
            screen = UIState(mode="dialogue", conversation=SimpleNamespace(npc_id=host.id, node_id=node, selected=0),
                             dialogue_content=ui.narrative_content)
            frame = resize_rgb(background, 1280, 720).copy()
            ui.draw(frame, state, screen)
            write_png(out / f"dialogue-portrait-{lake}.png", frame)
            frame = resize_rgb(background, 1280, 720).copy()
            ui.draw(frame, state, UIState(mode="map"))
            write_png(out / f"chart-pins-{lake}.png", frame)
    finally:
        text.close()


def _budget(roster):
    """Twenty cats queued on Briar's water anchors: the cache keeps 14 within 150 MiB."""
    world = World("briar")
    anchors = [a for a in world.anchors.values() if a.kind == "water"]
    water = [npc_id for npc_id, row in roster.items() if row["role"] == "water"]
    cache = actors.ActorCache(world)
    peak, resident = 0, 0
    for count in range(1, 21):
        npcs = tuple(NPC(water[i], roster[water[i]]["name"], "", anchors[i % len(anchors)]
                         if i < len(anchors) else Anchor(f"briar:test:{i}", "open", "test", 40.0 * i, 20.0), False)
                     for i in range(count))
        present = cache.sync(npcs, roster)
        for actor in present:
            actor.mesh(catmesh.LOD0)
            actor.mesh(catmesh.LOD1)
        resident = max(resident, len(cache.actors))
        peak = max(peak, actors.memory_report(cache)["total_bytes_bound"])
    report = actors.memory_report(cache)
    report.update(peak_resident=resident, peak_total_bytes_bound=peak, queued=20)
    if resident > actors.MAX_ACTORS or peak > actors.ACTOR_BUDGET:
        raise AssertionError(f"Cat actors exceeded their budget: {report}")
    return report


def _hailing(content):
    """The hail rule is untouched: within 20 m of the anchor and under 3 knots."""
    world = World("briar")
    state = State.new(world, seed=3)
    state.npcs = active_npcs(state, world, content)
    host = state.npcs[0]
    rows = []
    for distance, speed in ((19.5, 0.0), (20.5, 0.0), (10.0, HAIL_SPEED_MPS * 0.99), (10.0, HAIL_SPEED_MPS)):
        state.x, state.z = host.anchor.x + distance, host.anchor.z
        state.speed = speed
        found = nearby_npc(state)
        rows.append({"distance_m": distance, "speed_mps": round(speed, 4), "hails": found is not None})
    expected = [True, False, True, False]
    if [row["hails"] for row in rows] != expected:
        raise AssertionError(f"Hailing changed: {rows}")
    return {"range_m": HAIL_RANGE_M, "speed_limit_mps": round(HAIL_SPEED_MPS, 4), "cases": rows}


def _motion(roster):
    """The approach wave and head turn by distance, and the Reduced Motion hold."""
    world = World("briar")
    content = load_content()
    state = State.new(world, seed=3)
    state.npcs = active_npcs(state, world, content)
    actor = actors.ActorCache(world).sync(state.npcs, roster)[0]
    rows = []
    for distance in (5.0, 20.0, 35.0, 45.0):
        p = actors.pose_state(actor, actor.x + distance, actor.z, 12.3, False)
        rows.append({"distance_m": distance, "wave_blend": round(p["blend"], 3), "head_yaw": round(p["head_yaw"], 3)})
    still = [actors.animate(actor.mesh(catmesh.LOD0), actors.pose_state(actor, actor.x + 50, actor.z, t, True))[0]
             for t in (0.0, 7.7)]
    return {"npc": actor.npc_id, "by_distance": rows, "reduced_motion_still": bool(np.array_equal(*still))}


def shots(dest, *, software=False):
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    catmesh.clear_caches()
    catart.clear_caches()
    roster = load_content_v2().roster
    content = load_content()
    from .software import SoftwareRenderer

    renderers = [("software", lambda world: SoftwareRenderer(world, 480, 270))]
    if not software:
        from .glrender import LakeRenderer

        renderers.insert(0, ("native", lambda world: LakeRenderer(world, 960, 540)))
    build_ms, portrait_ms = _lineup(out, roster)
    _poses_patterns_lods(out, roster)
    world = _world(out, renderers, content)
    _skipper(out, renderers)
    _dialogue_and_chart(out, content)
    lod0 = np.asarray([catmesh.cat_mesh(i, catmesh.LOD0).triangle_count for i in roster])
    lod1 = np.asarray([catmesh.cat_mesh(i, catmesh.LOD1).triangle_count for i in roster])
    cats = sum(1 + bool(row["appearance"].get("twin")) for row in roster.values())
    result = {
        "backends": [name for name, _make in renderers],
        "actors": len(roster),
        "cats": cats,
        "lod0_triangles": {"min": int(lod0.min()), "median": int(np.median(lod0)), "max": int(lod0.max())},
        "lod1_triangles": {"min": int(lod1.min()), "median": int(np.median(lod1)), "max": int(lod1.max())},
        "mesh_build_median_ms": round(float(np.median(build_ms)), 2),
        "portrait_median_ms": round(float(np.median(portrait_ms)), 2),
        "world": world,
        "budget": _budget(roster),
        "hailing": _hailing(content),
        "motion": _motion(roster),
        "peak_rss_bytes": rss_bytes(),
        "memory_limit_bytes": MEMORY_LIMIT_BYTES,
    }
    if cats != 52:
        raise AssertionError(f"The lineup holds {cats} cats, not 52")
    if not result["motion"]["reduced_motion_still"]:
        raise AssertionError("Reduced Motion must hold the cats still")
    if result["peak_rss_bytes"] >= MEMORY_LIMIT_BYTES:
        raise AssertionError("Cat captures exceeded 3 GB")
    (out / "benchmark.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "world"}, indent=2))
    catmesh.clear_caches()
    catart.clear_caches()
    return result
