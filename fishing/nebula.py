"""Starlight Nebula Lagoon: band palettes, scenery, the station and current lanes.

Everything here is deterministic and read-only. Visual helpers never touch the
fishing RNG, a save or the story. The flow field itself is `bottools.flow_at`;
the visible current lanes and their moving dashes are drawn from it.
"""

from __future__ import annotations

import math

import numpy as np

from .bottools import flow_at
from .data import band_of

BAND_LABELS = {"dawn": "Rising", "day": "Bright", "dusk": "Fading", "night": "Deep"}
# Hours at which each palette is fully reached; the sky eases between them.
_KEYS = ((4.25, "deep"), (6.5, "rising"), (8.75, "bright"), (16.25, "bright"),
         (18.5, "fading"), (20.75, "deep"), (28.25, "deep"))
# Glowing props store 2 + their emission in Prop.shade (see foliage.frag).
GLOW_SHADE = 2.0
GLOW_KINDS = ("spire", "starlily", "kelp", "meteor", "lightreed")
WATERLINE = frozenset(("kelp", "meteor", "lightreed"))
SOLID_RADIUS = {"kelp": 0.12, "meteor": 0.45}  # fraction of the prop height
DASH_CELL = 6.0  # metres between current dashes
DASH_RATE = 0.11  # dash cycles per animation second
# Denser scenery beyond the baseline counts. `nebula_props` draws these last, from a
# separate stream, so the kelp and meteor solids keep their exact places (issue #167).
EXTRA_SPIRES = 30
EXTRA_LILIES = 8
EXTRA_REEDS = 20


def band_label(hour: float) -> str:
    """The Nebula's names for the four time bands (03 §1.6)."""
    return BAND_LABELS[band_of(hour)]


def sky_palette(hour: float, bands: dict) -> dict:
    """Zenith, horizon and star strength, eased between the four band palettes."""
    h = hour % 24.0
    if h < _KEYS[0][0]:
        h += 24.0
    for (h0, a), (h1, b) in zip(_KEYS, _KEYS[1:]):
        if h0 <= h <= h1:
            t = (h - h0) / (h1 - h0)
            t = t * t * (3.0 - 2.0 * t)
            break
    first, second = bands[a], bands[b]
    mix = lambda key: (np.asarray(first[key], np.float32) * (1 - t)
                       + np.asarray(second[key], np.float32) * t)
    return {"zenith": mix("zenith"), "horizon": mix("horizon"),
            "stars": float(first["stars"] * (1 - t) + second["stars"] * t)}


def lane_circles(world) -> np.ndarray:
    """(x, z, radius) rows of every current-lane circle, for both renderers."""
    rows = [(x, z, r) for zone, x, z, r in world.zones if zone == "current"]
    return np.asarray(rows, np.float32).reshape(-1, 3)


def lane_strength(circles, x, z):
    """1 on a lane's centreline, fading to 0 at its edge."""
    x, z = np.broadcast_arrays(np.asarray(x, np.float32), np.asarray(z, np.float32))
    shape = x.shape
    x, z = x.reshape(-1), z.reshape(-1)
    strength = np.zeros(x.shape, np.float32)
    for cx, cz, radius in circles:
        # Only points inside a circle's bounding square can be lit by it.
        near = np.flatnonzero((np.abs(x - cx) < radius) & (np.abs(z - cz) < radius))
        if near.size:
            d = np.hypot(x[near] - cx, z[near] - cz)
            lit = 1 - np.clip((d - radius * .55) / (radius * .45), 0, 1)
            strength[near] = np.maximum(strength[near], lit)
    return strength.reshape(shape)


def flow_direction(x, z):
    """Unit flow direction; the same formula as `bottools.flow_at`, vectorised."""
    heading = 1.7 * np.sin(np.asarray(x) / 190.0 + 0.6) + 1.1 * np.cos(np.asarray(z) / 150.0 - 0.4)
    return np.cos(heading), np.sin(heading)


def _hash(ix, iz, salt):
    """common.glsl's `hash` on cell coordinates, always in float64 on the CPU."""
    ix, iz = np.asarray(ix, np.float64), np.asarray(iz, np.float64)
    value = np.sin((ix + salt) * 127.1 + (iz + salt) * 311.7) * 43758.5453
    return value - np.floor(value)


def dashes(x, z, t):
    """Moving dashes that ride the flow field: 1 on a dash, 0 between them.

    Each 6 m cell owns at most one dash, centred near the cell middle and
    pointing along the flow there. It travels downstream as t advances.
    """
    x, z = np.asarray(x, np.float64), np.asarray(z, np.float64)
    bx, bz = np.floor(x / DASH_CELL), np.floor(z / DASH_CELL)
    best = np.zeros(np.broadcast(x, z).shape, np.float32)
    for j in (-1, 0, 1):
        for i in (-1, 0, 1):
            cx, cz = bx + i, bz + j
            seed = _hash(cx, cz, 7.3)
            ox = (cx + .5 + (_hash(cx, cz, 1.7) - .5) * .7) * DASH_CELL
            oz = (cz + .5 + (_hash(cx, cz, 4.1) - .5) * .7) * DASH_CELL
            dx, dz = flow_direction(ox, oz)
            phase = np.mod(t * DASH_RATE + seed, 1.0)
            hx, hz = ox + dx * (phase - .5) * DASH_CELL, oz + dz * (phase - .5) * DASH_CELL
            along = (x - hx) * dx + (z - hz) * dz
            side = -(x - hx) * dz + (z - hz) * dx
            dash = (1 - np.clip(np.abs(along) / 1.6, 0, 1)) * (1 - np.clip((np.abs(side) - .06) / .16, 0, 1))
            dash *= np.sin(phase * math.pi) * (seed > .35)
            best = np.maximum(best, dash)
    return best


def dash_segments(x0, z0, x1, z1, t):
    """Every visible dash in a rectangle as (x, z, dx, dz) rows, for checks."""
    rows = []
    for cz in range(math.floor(z0 / DASH_CELL), math.floor(z1 / DASH_CELL) + 1):
        for cx in range(math.floor(x0 / DASH_CELL), math.floor(x1 / DASH_CELL) + 1):
            seed = float(_hash(cx, cz, 7.3))
            if seed <= .35:
                continue
            ox = (cx + .5 + (float(_hash(cx, cz, 1.7)) - .5) * .7) * DASH_CELL
            oz = (cz + .5 + (float(_hash(cx, cz, 4.1)) - .5) * .7) * DASH_CELL
            dx, dz = (float(v) for v in flow_direction(ox, oz))
            phase = (t * DASH_RATE + seed) % 1.0
            rows.append((ox + dx * (phase - .5) * DASH_CELL, oz + dz * (phase - .5) * DASH_CELL, dx, dz))
    return np.asarray(rows, np.float64).reshape(-1, 4)


_GALAXY = np.array([0.4153, 0.5440, -0.7290], np.float32)


def aurora_rgb(dx, dy, dz, t):
    """CPU aurora curtains on unit directions; matches common.glsl's shape."""
    from .world import noise2
    az = np.arctan2(dz, dx)
    base = .07 + np.sin(az * 3 + t * .05) * .05 + np.sin(az * 7 - t * .03) * .02
    v = (dy - base) / (.30 + .09 * np.sin(az * 2 + 1.3))
    ribbon = np.clip(v / .07, 0, 1) * (1 - np.clip((v - .30) / .70, 0, 1)) * (dy > 0)
    rays = .45 + .55 * noise2((az * 42 + t * .09).astype(np.float32), (v * 1.5).astype(np.float32))
    folds = .45 + .55 * np.sin(az * 11 + t * .07 + np.sin(az * 4) * 2)
    mix = np.clip((v - .25) / .75, 0, 1)[..., None]
    colour = np.array([.18, .95, .62], np.float32) * (1 - mix) + np.array([.80, .34, .88], np.float32) * mix
    return colour * (ribbon * rays * np.maximum(folds, 0))[..., None]


_RADIANT = np.array([0.30, 0.45, 0.37], np.float32)


def _glsl_hash(x, y):
    """common.glsl's `hash(vec2)`."""
    value = math.sin(x * 127.1 + y * 311.7) * 43758.5453
    return value - math.floor(value)


def meteor_rgb(dx, dy, dz, t):
    """CPU Meteor Shower streaks from the same radiant as common.glsl."""
    radiant = _RADIANT / np.linalg.norm(_RADIANT)
    out = np.zeros(np.shape(dx) + (3,), np.float32)
    for i in range(8):
        cycle = t * .23 + i * .29
        life = cycle - math.floor(cycle)
        seed = (float(i), float(math.floor(cycle)))
        az = _glsl_hash(*seed) * math.tau
        side = np.cross(radiant, (math.cos(az), 0.0, math.sin(az)))
        side /= np.linalg.norm(side)
        start = radiant + np.cross(side, radiant) * (.18 + .35 * _glsl_hash(seed[0] + 3.1, seed[1] + 3.1))
        start /= np.linalg.norm(start)
        away = start - radiant * float(start @ radiant)
        away /= np.linalg.norm(away)
        tangent = away - start * float(away @ start)
        tangent /= np.linalg.norm(tangent)
        normal = np.cross(start, tangent)
        normal /= np.linalg.norm(normal)
        along = np.arctan2(dx * tangent[0] + dy * tangent[1] + dz * tangent[2],
                           dx * start[0] + dy * start[1] + dz * start[2])
        off = np.abs(dx * normal[0] + dy * normal[1] + dz * normal[2])
        head, tail = life * .95, max(0.0, life * .95 - .16)
        on = (off < .0042) & (along >= tail) & (along <= head) & (dy > .02)
        out += (on * (along - tail) / max(head - tail, .001) * (1 - life) * 1.6)[..., None] \
            * np.array([1.0, .93, .82], np.float32)
    return out


def gas_rgb(dx, dy, dz, light):
    """CPU Nebula gas and galaxy band. Smooth, so the sky samples it at half size."""
    from .world import noise2
    inv = 1 / np.maximum(np.sqrt(dx * dx + dy * dy + dz * dz), 1e-6)
    dx, dy, dz = dx * inv, dy * inv, dz * inv
    up = np.clip((dy + .02) / .27, 0, 1)
    px, pz = dx / (np.abs(dy) + .55) * 1.7, dz / (np.abs(dy) + .55) * 1.7
    gas_a = noise2((px * .9 + 3.1).astype(np.float32), (pz * .9 + 1.7).astype(np.float32))
    gas_b = noise2((px * 1.7 - 5.3).astype(np.float32), (pz * 1.7 - 2.2).astype(np.float32))
    band = np.exp(-(dx * _GALAXY[0] + dy * _GALAXY[1] + dz * _GALAXY[2]) ** 2 / .03)
    gas = (np.array([.42, .18, .62], np.float32) * np.clip((gas_a - .45) / .40, 0, 1)[..., None]
           + np.array([.10, .42, .50], np.float32) * np.clip((gas_b - .52) / .38, 0, 1)[..., None]
           + np.array([.55, .47, .72], np.float32) * (band * .6)[..., None])
    level = up * (.22 + .73 * light.get("starlight", 0.0)) * (1 - light["cloud_cover"] * .25)
    return (gas * level[..., None]).astype(np.float32)


def sky_add(dx, dy, dz, light, t):
    """CPU Nebula stars, aurora and meteors, added to the base sky (gas apart)."""
    from .world import hash21
    inv = 1 / np.maximum(np.sqrt(dx * dx + dy * dy + dz * dz), 1e-6)
    dx, dy, dz = dx * inv, dy * inv, dz * inv
    stars_level = light.get("starlight", 0.0)
    up = np.clip((dy + .02) / .27, 0, 1)
    band = np.exp(-(dx * _GALAXY[0] + dy * _GALAXY[1] + dz * _GALAXY[2]) ** 2 / .03)
    col = np.zeros(np.shape(dx) + (3,), np.float32)
    qx, qy, qz = (np.floor(axis * 200).astype(np.int64) for axis in (dx, dy, dz))
    seed = hash21(qx + qz * 13, qy + 31)
    density = .0045 * (1 + band * 2)
    stars = (seed > 1 - density) * np.clip((seed - (1 - density)) / density * 1.6, 0, 1)
    col = col + (stars * stars_level * up)[..., None] * np.array([.85, .88, 1.0], np.float32)
    if light.get("aurora", 0.0) > 0:
        col = col + aurora_rgb(dx, dy, dz, t) * light["aurora"] * .85
    if light.get("meteors", 0.0) > 0:
        col = col + meteor_rgb(dx, dy, dz, t) * light["meteors"]
    return col.astype(np.float32)


def nebula_props(world, prop_type):
    """Crystal spires, star-lilies, crystal kelp, meteor reefs and light-reeds."""
    from .world import in_landing_envelope
    parameters = world.environment
    rng = np.random.default_rng(parameters["seed"])
    result = []
    zones = {row[0]: row[1:] for row in parameters["zones"]}
    for index in range(parameters["tree_count"] * 3):
        angle = float(rng.uniform(0, math.tau))
        radius = float(world.fields.radius(angle)) + float(rng.uniform(10, 170))
        x, z = math.cos(angle) * radius, math.sin(angle) * radius
        a, s = world.slip.local(x, z)
        if in_landing_envelope(world.id, a, s):
            continue
        result.append(prop_type("spire", x, z, float(rng.uniform(6, 16)),
                                GLOW_SHADE + float(rng.uniform(.30, .60))))
        if len(result) == parameters["tree_count"]:
            break
    # Star-lilies bloom on every floating drift, never at its edge.
    for cx, cz, rx, rz in parameters["drifts"]:
        for _ in range(max(2, min(8, int(rx * rz / 40)))):
            angle, reach = float(rng.uniform(0, math.tau)), math.sqrt(float(rng.random())) * .6
            result.append(prop_type("starlily", cx + math.cos(angle) * rx * reach,
                                    cz + math.sin(angle) * rz * reach,
                                    float(rng.uniform(.9, 1.4)), GLOW_SHADE + .7))
    # Crystal kelp stands in six clusters around the forest, leaving its heart open.
    kx, kz, kr = zones["cypress"]
    for cluster in range(6):
        angle = cluster * math.tau / 6 + .4
        ccx, ccz = kx + math.cos(angle) * kr * .55, kz + math.sin(angle) * kr * .55
        for _ in range(6):
            x, z = ccx + float(rng.uniform(-7, 7)), ccz + float(rng.uniform(-7, 7))
            if float(world.shore_sd(x, z)) < -4:
                result.append(prop_type("kelp", x, z, float(rng.uniform(3.0, 5.5)),
                                        GLOW_SHADE + float(rng.uniform(.45, .75))))
    # Meteor reefs: three short ridges of dark boulders with ember seams.
    mx, mz, mr = zones["rocks"]
    for ridge in range(3):
        angle = ridge * 2.1 + .3
        dx, dz = math.cos(angle), math.sin(angle)
        ox, oz = mx + dz * (ridge - 1) * mr * .45, mz - dx * (ridge - 1) * mr * .45
        for step in range(6):
            t = (step - 2.5) * 9.0
            x, z = ox + dx * t + float(rng.uniform(-1.5, 1.5)), oz + dz * t + float(rng.uniform(-1.5, 1.5))
            if float(world.shore_sd(x, z)) < -4:
                result.append(prop_type("meteor", x, z, float(rng.uniform(1.4, 2.4)), GLOW_SHADE + .18))
    # Light-reeds fill the reed bed; like Briar's reeds they never block a hull.
    rx_, rz_, rr = zones["reeds"]
    for _ in range(70):
        angle, reach = float(rng.uniform(0, math.tau)), math.sqrt(float(rng.random())) * rr * .9
        x, z = rx_ + math.cos(angle) * reach, rz_ + math.sin(angle) * reach
        if float(world.shore_sd(x, z)) < -2.5:
            result.append(prop_type("lightreed", x, z, float(rng.uniform(1.3, 2.2)),
                                    GLOW_SHADE + float(rng.uniform(.5, .8))))
    # Denser scenery from a separate stream, last: the kelp and meteor solids above keep
    # their exact places, and every baseline spire, lily and light-reed is unchanged.
    extra = np.random.default_rng(parameters["seed"] + 9000)
    spires = reeds = 0
    for _ in range(EXTRA_SPIRES * 4):
        if spires == EXTRA_SPIRES:
            break
        angle = float(extra.uniform(0, math.tau))
        radius = float(world.fields.radius(angle)) + float(extra.uniform(10, 170))
        x, z = math.cos(angle) * radius, math.sin(angle) * radius
        a, s = world.slip.local(x, z)
        if in_landing_envelope(world.id, a, s):
            continue
        result.append(prop_type("spire", x, z, float(extra.uniform(6, 16)),
                                GLOW_SHADE + float(extra.uniform(.30, .60))))
        spires += 1
    drifts = parameters["drifts"]
    for _ in range(EXTRA_LILIES):
        cx, cz, rx, rz = drifts[int(extra.integers(len(drifts)))]
        angle, reach = float(extra.uniform(0, math.tau)), math.sqrt(float(extra.random())) * .6
        result.append(prop_type("starlily", cx + math.cos(angle) * rx * reach,
                                cz + math.sin(angle) * rz * reach,
                                float(extra.uniform(.9, 1.4)), GLOW_SHADE + .7))
    for _ in range(EXTRA_REEDS * 4):
        if reeds == EXTRA_REEDS:
            break
        angle, reach = float(extra.uniform(0, math.tau)), math.sqrt(float(extra.random())) * rr * .9
        x, z = rx_ + math.cos(angle) * reach, rz_ + math.sin(angle) * reach
        if float(world.shore_sd(x, z)) < -2.5:
            result.append(prop_type("lightreed", x, z, float(extra.uniform(1.3, 2.2)),
                                    GLOW_SHADE + float(extra.uniform(.5, .8))))
            reeds += 1
    return result


# Station panels replace the timber of the shared marina geometry.
_PANEL = np.array([.70, .72, .84], np.float32)
_TRIM = np.array([.30, .27, .52], np.float32)
_LANTERN = np.array([.70, .95, 1.0], np.float32)


def restyle_station(faces):
    """Recolour the shared landing geometry as Cosmic Drift Station, in place."""
    for face in faces:
        r, g, b = (float(v) for v in face.color)
        luminance = .30 * r + .59 * g + .11 * b
        if r > .8 and g > .5 and b < .35:
            # Every warm lamp becomes a pale star-lantern.
            face.color = _LANTERN.copy()
            face.emissive = 1.0
        elif r > b * 1.25:
            # Timber decks and walls become silver-lilac hull panels.
            face.color = (_PANEL * (.55 + luminance * .75)).astype(np.float32)
        else:
            face.color = (face.color * .55 + _TRIM * .45 * (.6 + luminance)).astype(np.float32)


def station_faces(world):
    """An observatory dome, telescope and beacon mast on the station's dry pad."""
    from .world import _box, _face
    sl = world.slip
    along, up, side = np.array((sl.ix, 0, sl.iz), np.float32), np.array((0, 1, 0), np.float32), \
        np.array((sl.sx, 0, sl.sz), np.float32)
    s = -14.0
    for a in np.arange(26.0, 56.0, 1.0):
        if all(float(world.shore_sd(*sl.world(a + da, s + ds))) >= 1.5
               for da in (-4, 0, 4) for ds in (-4, 0, 4)):
            break
    else:
        raise ValueError("Cosmic Drift Station has no dry observatory pad")
    x, z = sl.world(float(a), s)
    ground = max(float(world.sample_height(*sl.world(float(a) + da, s + ds)))
                 for da in (-4, 0, 4) for ds in (-4, 0, 4))
    base = np.array((x, ground + .1, z), np.float32)
    faces = _box(base + up * .55, along, up, side, (7.0, 1.1, 7.0), (.42, .40, .56))
    radius, rings, segments = 3.1, 5, 14
    shell, slot = np.array((.82, .84, .94), np.float32), np.array((.08, .09, .20), np.float32)
    centre = base + up * 1.1
    for ring in range(rings):
        e0, e1 = ring * (math.pi / 2) / rings, (ring + 1) * (math.pi / 2) / rings
        for k in range(segments):
            a0, a1 = k * math.tau / segments, (k + 1) * math.tau / segments
            def p(e, az):
                return centre + (along * math.cos(az) + side * math.sin(az)) * radius * math.cos(e) + up * radius * math.sin(e)
            pts = [p(e0, a0), p(e0, a1), p(e1, a1), p(e1, a0)]
            mid = (pts[0] + pts[2]) * .5 - centre
            # The shutter slot faces the lagoon, open on the telescope.
            colour = slot if k in (6, 7) and ring < rings - 1 else shell
            faces.append(_face(pts, mid, colour))
    # The telescope leans out of the slot toward the sky over the water.
    tip = centre - along * 3.6 + up * 3.0
    root = centre + up * .8
    axis = tip - root
    length = float(np.linalg.norm(axis))
    faces += _box((root + tip) * .5, axis, np.cross(axis, side), side, (length, .42, .42), (.26, .24, .40))
    faces += _box(tip, axis, np.cross(axis, side), side, (.12, .55, .55), (.62, .86, 1.0))
    faces[-6:] = [_emit(face) for face in faces[-6:]]
    # Beacon mast with a slowly visible star light at its top.
    mx, mz = sl.world(float(a) + 6.0, s + 7.0)
    mast = np.array((mx, ground, mz), np.float32)
    faces += _box(mast + up * 4.5, along, up, side, (.22, 9.0, .22), (.52, .54, .66))
    for height in (3.0, 6.0):
        faces += _box(mast + up * height, along, up, side, (1.6, .08, .08), (.52, .54, .66))
    faces += [_emit(face) for face in _box(mast + up * 9.25, along, up, side, (.5, .5, .5), (.95, .78, 1.0))]
    return faces


def _emit(face):
    face.emissive = 1.0
    return face
