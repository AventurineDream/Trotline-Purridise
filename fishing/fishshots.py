"""`--shots PATH --fish`: per-lake field-guide sheets, legendaries, haul meshes and idles (V1-28)."""

import json
import math
from pathlib import Path
import time

import numpy as np

from .content import load_content_v2
from .fishcheck import lookalike_report
from .fishmesh import (FAMILY_PRESETS, cache_bytes, clear_caches, fish_card, fish_look, haul_mesh,
                       idle_mesh, legendary_idle, _tiny_label)
from .imageops import resize_rgb
from .pngsave import write_png
from .raster import raster_tri
from .verify import MEMORY_LIMIT_BYTES, rss_bytes

CELL = (256, 128)
HAUL_CELL = (192, 96)
IDLE_FRAMES = 6
WATER = np.asarray((0.07, 0.24, 0.30), np.float32)


def _sheet(cells, cols, fill=(224, 215, 193)):
    height, width = cells[0].shape[:2]
    rows = math.ceil(len(cells) / cols)
    sheet = np.empty((rows * height, cols * width, 3), np.uint8)
    sheet[:] = fill
    for index, cell in enumerate(cells):
        row, col = divmod(index, cols)
        sheet[row * height:(row + 1) * height, col * width:(col + 1) * width] = cell
    return sheet


def _card_cell(card, label):
    cell = resize_rgb(card, *CELL).copy()
    _tiny_label(cell, label, 10, 10)
    return cell


def _haul_cell(fish_id, shiny=False):
    from .ui import _haul_mesh_sprite

    sprite = _haul_mesh_sprite(fish_id, "briar", shiny)
    alpha = sprite[:, :, 3:4].astype(np.float32) / 255.0
    cell = WATER * 255 * (1 - alpha) + sprite[:, :, :3] * alpha
    cell = resize_rgb(np.clip(cell + 0.5, 0, 255).astype(np.uint8), *HAUL_CELL).copy()
    _tiny_label(cell, fish_id, 5, 5, (226, 230, 218))
    return cell


def idle_frame(legendary_id, t, *, size=(384, 192), reduced_motion=False):
    """Render one idle pose from a three-quarter view, lit and tinted as if underwater."""
    width, height = size
    mesh = idle_mesh(legendary_id, t, reduced_motion=reduced_motion)
    yaw, pitch = 0.62, 0.22
    cy, sy, cp, sp = math.cos(yaw), math.sin(yaw), math.cos(pitch), math.sin(pitch)

    def turn(points):
        x = points[:, 0] * cy - points[:, 2] * sy
        z = points[:, 0] * sy + points[:, 2] * cy
        y = points[:, 1] * cp - z * sp
        return np.stack((x, y, points[:, 1] * sp + z * cp), axis=1)

    vertices, normals = turn(mesh.vertices), turn(mesh.normals)
    light = np.asarray((0.35, 0.85, 0.40), np.float32)
    light /= np.linalg.norm(light)
    shade = 0.52 + 0.48 * np.abs(normals @ light)
    gradient = np.linspace(1.25, 0.70, height, dtype=np.float32)[:, None, None]
    colour = np.broadcast_to(WATER * gradient, (height, width, 3)).copy()
    depth = np.full((height, width), 1e6, np.float32)
    scale = width / 2.9
    screen = np.stack((width * 0.5 + vertices[:, 0] * scale, height * 0.52 - vertices[:, 1] * scale), axis=1)
    for index, triangle in enumerate(mesh.triangles):
        lit = mesh.colors[index] * shade[index]
        raster_tri(colour, depth, screen[triangle], 3.0 - vertices[triangle, 2], lit * 0.86 + WATER * 0.14)
    return np.clip(colour * 255 + 0.5, 0, 255).astype(np.uint8)


def shots(dest, *, software=False):
    out = Path(dest)
    out.mkdir(parents=True, exist_ok=True)
    clear_caches()
    content = load_content_v2()
    card_renderer = None
    renderer = None
    if not software:
        from .render import Renderer
        from .world import World

        renderer = Renderer(World("briar"), 1280, 720, software=False)
        if not hasattr(renderer, "scene_fb"):
            renderer.close()
            raise AssertionError("Native fish capture fell back to software")
        card_renderer = renderer.fish_card
    try:
        return _capture(out, content, card_renderer, "native" if renderer else "software")
    finally:
        if renderer is not None:
            renderer.close()
        clear_caches()


def _capture(out, content, card_renderer, backend):
    paint = card_renderer or fish_card
    card_ms, mesh_ms, triangles = [], [], {}
    for lake_id, lake in content.lakes.items():
        ids = list(lake["species_ids"])
        for shiny in (False, True):
            cells = []
            for sid in ids:
                start = time.perf_counter()
                card = paint(sid, shiny)
                card_ms.append((time.perf_counter() - start) * 1000)
                cells.append(_card_cell(card, ("SHINY " if shiny else "") + content.species[sid]["name"]))
            write_png(out / f"cards-{lake_id}{'-shiny' if shiny else ''}.png", _sheet(cells, 6))
        cells = []
        for sid in ids:
            start = time.perf_counter()
            mesh = haul_mesh(sid, lake_id, False)
            mesh_ms.append((time.perf_counter() - start) * 1000)
            triangles[sid] = mesh.triangle_count
            cells.append(_haul_cell(sid))
        write_png(out / f"haul-{lake_id}.png", _sheet(cells, 6, WATER * 255))
    legendary_ids = list(content.legendaries)
    write_png(out / "cards-legendaries.png",
              _sheet([_card_cell(paint(lid, False), content.legendaries[lid]["name"]) for lid in legendary_ids], 4))
    for lid in legendary_ids:
        triangles[lid] = haul_mesh(lid, content.legendaries[lid]["lake"], False).triangle_count
    write_png(out / "haul-legendaries.png", _sheet([_haul_cell(lid) for lid in legendary_ids], 4, WATER * 255))

    # Each legendary's idle: six poses across one loop, then the Reduced Motion pose.
    idle_rows, idle_ms, idle = [], [], {}
    for lid in legendary_ids:
        params = legendary_idle(lid)
        loop = 2.0 / params["rate"]
        frames = []
        for k in range(IDLE_FRAMES):
            start = time.perf_counter()
            frames.append(idle_frame(lid, loop * k / IDLE_FRAMES, size=HAUL_CELL))
            idle_ms.append((time.perf_counter() - start) * 1000)
        still = idle_frame(lid, loop * 0.3, size=HAUL_CELL, reduced_motion=True)
        held = bool(np.array_equal(still, idle_frame(lid, 0.0, size=HAUL_CELL, reduced_motion=True)))
        _tiny_label(frames[0], content.legendaries[lid]["name"], 5, 5, (226, 230, 218))
        _tiny_label(still, "REDUCED MOTION", 5, 5, (226, 230, 218))
        idle_rows.append(np.concatenate(frames + [still], axis=1))
        rest_vertices = idle_mesh(lid, 0.0, reduced_motion=True).vertices
        travel = [float(np.abs(idle_mesh(lid, loop * k / 24).vertices - rest_vertices).max()) for k in range(24)]
        idle[lid] = {**params, "loop_s": round(loop, 3), "max_displacement": round(max(travel), 4),
                     "loop_closes": bool(np.allclose(idle_mesh(lid, loop).vertices, idle_mesh(lid, 0.0).vertices,
                                                     atol=1e-5)),
                     "reduced_motion_still": held}
    write_png(out / "legendary-idle.png", np.concatenate(idle_rows, axis=0))
    if not all(row["loop_closes"] and row["reduced_motion_still"] for row in idle.values()):
        raise AssertionError(f"Legendary idles must loop and hold still for Reduced Motion: {idle}")

    report = lookalike_report(content)
    (out / "lookalike.json").write_text(json.dumps(report, indent=2) + "\n")
    # The closest same-lake pairs side by side, for the manual review.
    pairs = []
    for lake_id, lake in report["lakes"].items():
        for pair in lake["closest"][:3]:
            row = [_card_cell(paint(pair["a"], False), pair["a"]), _card_cell(paint(pair["b"], False), pair["b"])]
            _tiny_label(row[1], f"IOU {pair['iou']:.3f} PALETTE {pair['palette_overlap']:.3f}", 10, 112)
            pairs.append(np.concatenate(row, axis=1))
    write_png(out / "lookalike-closest.png", _sheet(pairs, 2))

    counts = np.asarray(list(triangles.values()))
    families = sorted({fish_look(fid)["family"] for fid in triangles})
    result = {
        "backend": backend,
        "species": len(content.species),
        "legendaries": len(legendary_ids),
        "families": families,
        "family_presets": sorted(FAMILY_PRESETS),
        "card_variants": len(card_ms),
        "card_median_ms": round(float(np.median(card_ms)), 3),
        "haul_mesh_median_ms": round(float(np.median(mesh_ms)), 3),
        "haul_triangles": {"min": int(counts.min()), "median": int(np.median(counts)), "max": int(counts.max())},
        "idle_frame_median_ms": round(float(np.median(idle_ms)), 3),
        "idle": idle,
        "lookalike_failures": len(report["failures"]),
        "cpu_card_cache_bytes": cache_bytes(),
        "peak_rss_bytes": rss_bytes(),
        "memory_limit_bytes": MEMORY_LIMIT_BYTES,
    }
    if result["peak_rss_bytes"] >= MEMORY_LIMIT_BYTES:
        raise AssertionError("Fish captures exceeded 3 GB")
    if report["failures"]:
        raise AssertionError(f"Look-alike pairs: {report['failures']}")
    (out / "benchmark.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "idle"}, indent=2))
    return result
