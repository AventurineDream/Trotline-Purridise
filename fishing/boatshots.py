"""The 24-boat lineup and a first-person cockpit view of each generated family (V1-22)."""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from . import fleet
from .boat import BOATS
from .camera import Camera
from .imageops import resize_rgb
from .pngsave import write_png
from .sim import State
from .software import SoftwareRenderer
from .weather import frame_light
from .world import Face, World

# One boat per generated family, shown from the helm.
COCKPIT_BOATS = {
    "pioneer": "log_raft", "rowed": "dory", "jon": "duck_jon", "utility": "deepv_skiff",
    "runabout": "mahogany_runabout", "sail_trawler": "small_sloop", "pontoon": "party_barge",
    "cosmic": "nebula_cruiser",
}
_WATER = (0.20, 0.36, 0.42)


def studio(state, *, angle=0.78, size=256, night=False):
    """A three-quarter view of the player's boat on calm water, using the CPU raster path."""
    renderer = SoftwareRenderer.__new__(SoftwareRenderer)
    renderer.w = renderer.h = size
    yy = np.linspace(0, 1, size, dtype=np.float32)[:, None, None]
    top = np.array((0.05, 0.07, 0.11) if night else (0.86, 0.88, 0.84), np.float32)
    bottom = np.array((0.08, 0.11, 0.14) if night else (0.62, 0.70, 0.70), np.float32)
    renderer.col = np.broadcast_to(top * (1 - yy) + bottom * yy, (size, size, 3)).copy()
    renderer.z = np.full((size, size), 1e6, np.float32)
    model = state.boat
    centre = (model.bow + model.stern) * 0.5
    distance = max(4.6, model.length * 1.05 + 2.8)
    height = distance * 0.42
    x, z = math.sin(angle) * distance, centre + math.cos(angle) * distance
    camera = Camera(x, height, z, math.atan2(-x, centre - z), -math.atan2(height - 0.6, distance), 0,
                    math.radians(42), size, size, build_rays=False)
    light = frame_light(22 if night else 10, "clear")
    reach = distance * 3
    water = [Face(np.array([(-reach, 0, centre - reach), (reach, 0, centre - reach),
                            (reach, 0, centre + reach), (-reach, 0, centre + reach)], np.float32),
                  np.array([0, 1, 0], np.float32), np.array(_WATER, np.float32), "world", 0.0)]
    renderer._faces(camera, water, light, boat=False)
    lift = np.array([0, model.eye_height, 0], np.float32)
    faces = [Face(face.pts + lift, face.normal, face.color, "world", face.emissive)
             for face in renderer._boat_faces(state)]
    renderer._faces(camera, faces, light, boat=False)
    return np.rint(np.clip(renderer.col, 0, 1) * 255).astype(np.uint8)


def boat_lineup(destination, *, text=None, renderer=None, world=None):
    """Write the lineup, its legend, and one cockpit frame per generated family."""
    from .platform import Text
    from .ui import UI
    out = Path(destination)
    out.mkdir(parents=True, exist_ok=True)
    own_text = text is None
    text = Text() if own_text else text
    painter = UI(text, None)
    world = World("briar") if world is None else world
    try:
        tiles, legend = [], []
        for model in fleet.shop_boats():
            state = State.new(world, seed=91)
            state.boat_id = model.id
            state.sail_raised = model.power == "sail"
            tile = studio(state)
            rail = np.full((24, tile.shape[1], 3), (25, 40, 43), np.uint8)
            painter._text(rail, f"T{model.tier} · {model.name}", 8, 5, 11, (232, 226, 205), False, "sans")
            tiles.append(np.concatenate((rail, tile)))
            legend.append({"id": model.id, "name": model.name, "tier": model.tier, "family": model.family,
                           "length_m": round(model.length, 2), "beam_m": round(model.half_beam * 2, 2)})
        rows = [np.concatenate(tiles[i:i + 6], axis=1) for i in range(0, len(tiles), 6)]
        write_png(out / "boat-lineup.png", np.concatenate(rows))
        (out / "boat-lineup.json").write_text(json.dumps(legend, indent=2) + "\n")
        if renderer is not None:
            for family, boat_id in COCKPIT_BOATS.items():
                state = State.new(world, seed=92)
                state.boat_id = boat_id
                state.x, state.z, state.yaw = -90.0, -40.0, math.atan2(-85.0, -75.0)
                state.game_minutes = 15 * 60 if family == "cosmic" else 6 * 60
                state.speed = state.throttle = 0.0
                state.anchored, state.look, state.tutorial = True, -0.02, 4
                state.sail_raised = BOATS[boat_id].power == "sail"
                frame = resize_rgb(renderer.render(state), 960, 540)
                write_png(out / f"cockpit-{family}.png", frame)
        print(f"boat lineup  {len(tiles)} boats, {len(COCKPIT_BOATS) if renderer else 0} cockpit views")
        return legend
    finally:
        if own_text:
            text.close()
