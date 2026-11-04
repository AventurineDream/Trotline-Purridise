"""V1-37: trophy replicas, a carved fish on a wooden plaque (02 §5.5, §8, §9).

A recorded legendary earns a trophy replica, and a shiny earns one too. Both go on the
book's Trophy page, and on the rail of any boat with the `trophy_rail` trait.
- **The model** (`rail_faces`) is low-poly enough for a boat: a varnished plaque hung from the
  rail, the fish carved in relief on it (its side-on silhouette, in its own top, flank and
  belly colours, or its shiny palette), and a brass plate under it. It is about 30 faces, and
  a rail holds `RAIL_SLOTS` of them along its metre.
- **The Trophy page's picture** (`picture`) is the same replica, drawn from the fish's lit
  sprite, toned like varnished wood and brass.

Mounting never consumes a catch or a book record (`State.mount_legendary_replica`,
`State.mount_shiny_trophy`); taking one down only clears the rail.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

RAIL_SLOTS = 4                   # replicas a rail holds, one beside the next
PLAQUE = (0.22, 0.13, 0.025)     # length along the rail, height, thickness (metres)
WOOD = (0.42, 0.26, 0.14)
WOOD_EDGE = (0.30, 0.18, 0.10)
BRASS = (0.86, 0.70, 0.34)
COLUMNS = 8                      # the carved fish's columns, snout to tail


def _palette(kind: str, item_id: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    from .fishmesh import SHINY_PALETTES, _species_rows, fish_look
    if kind == "shiny":
        return tuple(np.asarray(c, np.float32) for c in SHINY_PALETTES[_species_rows()[item_id]["shiny"]])
    colors = fish_look(item_id)["colors"]
    return tuple(np.asarray(colors[k], np.float32) for k in ("top", "side", "belly"))


@lru_cache(maxsize=32)
def silhouette(item_id: str) -> tuple[tuple[float, float, float], ...]:
    """The fish side-on, as `COLUMNS` columns from snout to tail: (x, top, bottom), normalised
    so its length is 1 and its midline sits at 0."""
    from .fishmesh import _species_rows, haul_mesh
    v = haul_mesh(item_id, _species_rows()[item_id].get("lake", "briar"), False).vertices
    x, y = v[:, 0], v[:, 1]
    lo, hi = float(x.min()), float(x.max())
    length = max(hi - lo, 1e-6)
    mid = (float(y.max()) + float(y.min())) / 2.0
    edges = np.linspace(hi, lo, COLUMNS + 1)   # snout first
    out = []
    for a, b in zip(edges, edges[1:]):
        inside = (x <= a) & (x >= b)
        if not inside.any():
            inside = np.abs(x - (a + b) / 2) <= (a - b)
        top = float(y[inside].max() - mid) / length if inside.any() else 0.0
        bottom = float(y[inside].min() - mid) / length if inside.any() else 0.0
        out.append((float((hi - (a + b) / 2) / length), top, bottom))
    return tuple(out)


def rail_faces(m, kind: str, item_id: str, centre, along, inward) -> None:
    """Add one replica to a boat mesh `m` (`boatfamilies._Mesh`): a plaque centred on `centre`
    whose face looks along `inward`, its length running along `along` (unit vectors)."""
    c = np.asarray(centre, np.float32)
    a = np.asarray(along, np.float32)
    n = np.asarray(inward, np.float32)
    up = np.array((0.0, 1.0, 0.0), np.float32)
    length, height, depth = PLAQUE

    def at(s, t, d):
        return c + a * s + up * t + n * d

    # The plaque: a shallow box, its face toward the cockpit, a darker edge around it.
    hl, hh = length / 2, height / 2
    m.quad([at(-hl, -hh, depth), at(hl, -hh, depth), at(hl, hh, depth), at(-hl, hh, depth)], WOOD, n)
    m.quad([at(-hl, hh, 0), at(hl, hh, 0), at(hl, hh, depth), at(-hl, hh, depth)], WOOD_EDGE, up)
    m.quad([at(-hl, -hh, 0), at(-hl, -hh, depth), at(hl, -hh, depth), at(hl, -hh, 0)], WOOD_EDGE, -up)
    m.quad([at(-hl, -hh, 0), at(-hl, hh, 0), at(-hl, hh, depth), at(-hl, -hh, depth)], WOOD_EDGE, -a)
    m.quad([at(hl, -hh, 0), at(hl, -hh, depth), at(hl, hh, depth), at(hl, hh, 0)], WOOD_EDGE, a)
    # The carved fish, standing proud of the plaque: each column is a top and a lower quad.
    top, side, belly = _palette(kind, item_id)
    span = length * 0.82
    scale = span
    lift = height * 0.10
    proud = depth + 0.012
    cols = silhouette(item_id)
    for (x0, t0, b0), (x1, t1, b1) in zip(cols, cols[1:]):
        s0, s1 = span / 2 - x0 * span, span / 2 - x1 * span
        m0, m1 = (t0 + b0) / 2, (t1 + b1) / 2
        m.quad([at(s0, lift + m0 * scale, proud), at(s1, lift + m1 * scale, proud),
                at(s1, lift + t1 * scale, proud), at(s0, lift + t0 * scale, proud)], top * 0.55 + side * 0.45, n)
        m.quad([at(s0, lift + b0 * scale, proud), at(s1, lift + b1 * scale, proud),
                at(s1, lift + m1 * scale, proud), at(s0, lift + m0 * scale, proud)], side * 0.5 + belly * 0.5, n)
    # The brass plate under it.
    pl, ph = length * 0.30, height * 0.12
    py = -hh + ph * 0.9
    m.quad([at(-pl / 2, py - ph / 2, depth + 0.004), at(pl / 2, py - ph / 2, depth + 0.004),
            at(pl / 2, py + ph / 2, depth + 0.004), at(-pl / 2, py + ph / 2, depth + 0.004)], BRASS, n)


def _sprite(kind: str, item_id: str) -> np.ndarray:
    if kind == "legendary":
        from .encounter import fish_sprite
        return fish_sprite(item_id)
    from .ui import _haul_mesh_sprite
    from .fishmesh import _species_rows
    return _haul_mesh_sprite(item_id, (_species_rows()[item_id].get("lakes") or ["briar"])[0], True)


@lru_cache(maxsize=8)
def picture(kind: str, item_id: str, width: int, height: int) -> np.ndarray:
    """The replica for the Trophy page, RGB8 (read-only, cached): the fish mounted on a
    varnished plaque, with its shadow, a highlight along the varnish, and a brass plate."""
    from .imageops import resize_rgb
    width, height = max(48, int(width)), max(32, int(height))
    yy = np.arange(height, dtype=np.float32)[:, None] / height
    xx = np.arange(width, dtype=np.float32)[None, :] / width
    paper = np.asarray((232, 224, 200), np.float32) / 255.0
    image = np.broadcast_to(paper, (height, width, 3)).copy()
    # The plaque: an oval of wood, its grain running along it, darker at the bevel.
    ox, oy = (xx - 0.5) / 0.47, (yy - 0.47) / 0.42
    r = np.sqrt(ox * ox + oy * oy)
    grain = 0.06 * np.sin(yy * 70.0 + np.sin(xx * 9.0) * 2.0)
    wood = np.asarray(WOOD, np.float32) * (1.12 + grain)[..., None]
    bevel = np.clip((r - 0.86) / 0.14, 0.0, 1.0)[..., None]
    wood = wood * (1.0 - 0.45 * bevel)
    shadow = (r > 1.0) & (np.sqrt(((xx - 0.515) / 0.47) ** 2 + ((yy - 0.50) / 0.42) ** 2) <= 1.0)
    image[shadow] = image[shadow] * 0.72
    inside = (r <= 1.0)[..., None]
    image = np.where(inside, wood, image)
    # The fish, varnished: a little warmer, a sheen along its back.
    sprite = _sprite(kind, item_id)
    fw = int(width * 0.74)
    fh = max(1, fw * sprite.shape[0] // sprite.shape[1])
    small = resize_rgb(sprite, fw, fh).astype(np.float32) / 255.0
    x0, y0 = int(width * 0.5 - fw / 2), int(height * 0.43 - fh / 2)
    ax, ay, bx, by = max(0, x0), max(0, y0), min(width, x0 + fw), min(height, y0 + fh)
    if ax < bx and ay < by:
        part = small[ay - y0:by - y0, ax - x0:bx - x0]
        alpha = part[:, :, 3:4]
        fish = part[:, :, :3] * np.asarray((1.04, 1.0, 0.92), np.float32)
        rows = np.linspace(0.0, 1.0, by - ay, dtype=np.float32)[:, None, None]
        fish = fish + 0.10 * np.clip(1.0 - np.abs(rows - 0.35) * 6.0, 0.0, 1.0)
        sx0, sy0, sx1, sy1 = ax + 3, ay + 2, min(width, bx + 3), min(height, by + 2)
        image[sy0:sy1, sx0:sx1] *= 1.0 - alpha[:sy1 - sy0, :sx1 - sx0] * 0.35   # its shadow on the plaque
        image[ay:by, ax:bx] = image[ay:by, ax:bx] * (1.0 - alpha) + np.clip(fish, 0.0, 1.0) * alpha
    # The brass plate.
    plate = (np.abs(xx - 0.5) < 0.16) & (np.abs(yy - 0.80) < 0.045)
    image[np.broadcast_to(plate, (height, width))] = BRASS
    edge = plate & ~((np.abs(xx - 0.5) < 0.152) & (np.abs(yy - 0.80) < 0.036))
    image[np.broadcast_to(edge, (height, width))] = np.asarray(BRASS, np.float32) * 0.7
    out = np.clip(image * 255.0 + 0.5, 0, 255).astype(np.uint8)
    out.setflags(write=False)
    return out


def rail_view(state, size: int = 240) -> np.ndarray | None:
    """The current boat's trophy rail seen from the cockpit side, close up, RGB8: where the
    replicas hang, which the helm view never shows. None for a boat without a rail."""
    from .boatfamilies import rail_centre
    centre = rail_centre(state.boat)
    if centre is None:
        return None
    key = (state.boat_id, tuple(state.rail_trophies()), tuple(sorted(state.look_paint.items())), int(size))
    if key not in _RAIL_VIEWS:
        while len(_RAIL_VIEWS) >= 4:
            _RAIL_VIEWS.pop(next(iter(_RAIL_VIEWS)))
        _RAIL_VIEWS[key] = _rail_view(state, int(size))
    return _RAIL_VIEWS[key]


_RAIL_VIEWS: dict = {}   # (boat, what hangs on its rail, paint, size) -> image; the last four


def _rail_view(state, size):
    import math
    from .boatfamilies import rail_centre
    from .camera import Camera
    from .software import SoftwareRenderer
    from .weather import frame_light
    from .world import Face
    model = state.boat
    rx, ry, rz = rail_centre(model)
    lift = np.array([0, model.eye_height, 0], np.float32)
    target = np.array((rx, ry - PLAQUE[1] * 0.6, rz), np.float32) + lift
    eye = target + np.array((1.75, 0.50, 0.0), np.float32)
    d = target - eye
    renderer = SoftwareRenderer.__new__(SoftwareRenderer)
    renderer.w = renderer.h = size
    yy = np.linspace(0, 1, size, dtype=np.float32)[:, None, None]
    sky = np.array((0.80, 0.84, 0.82), np.float32) * (1 - yy) + np.array((0.55, 0.64, 0.64), np.float32) * yy
    renderer.col = np.broadcast_to(sky, (size, size, 3)).copy()
    renderer.z = np.full((size, size), 1e6, np.float32)
    camera = Camera(float(eye[0]), float(eye[1]), float(eye[2]), math.atan2(float(d[0]), float(d[2])),
                    -math.atan2(float(-d[1]), math.hypot(float(d[0]), float(d[2]))), 0,
                    math.radians(38), size, size, build_rays=False)
    light = frame_light(10, "clear")
    faces = [Face(face.pts + lift, face.normal, face.color, "world", face.emissive)
             for face in renderer._boat_faces(state)]
    renderer._faces(camera, faces, light, boat=False)
    out = np.rint(np.clip(renderer.col, 0, 1) * 255).astype(np.uint8)
    out.setflags(write=False)
    return out
