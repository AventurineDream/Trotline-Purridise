"""Parametric first-person meshes for the twenty generated boats (06 §6.4).

The four original boats keep their hand-built meshes in `boatmesh.py`. Every
other boat is built here from its footprint (bow, stern, beam, draft and eye
height in `boats.json`) plus its family: sheer, bow and transom widths, bottom
shape, deck height and accessories. Variants inside a family differ in size,
trim and fittings.

Coordinates are eye-local, like the hand-built boats: x to starboard, y up with
the water at -eye_height, z forward to the bow. The same faces, moved into the
world, serve NPC boats (`npc_faces`).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np

from .boat import BOATS
from .data import paint_rgb
from .weather import wind_at
from .world import Face

STATIONS = 8  # hull cross-sections from transom to stem
STAR = 1.0  # night-emission strength of starlight fittings


@dataclass(frozen=True)
class HullSpec:
    sheer: float  # gunwale height above the water amidships, m
    bow_rise: float  # extra gunwale height at the stem, m
    bow_width: float  # gunwale half-width at the stem, as a fraction of the beam
    stern_width: float  # transom half-width fraction; 0 is a double-ender
    bottom: float  # chine half-width as a fraction of the gunwale; low values make a V
    deck: float  # cockpit floor height above the water, m
    hull: tuple  # material colour when the hull is left unpainted
    inner: tuple  # liner colour
    deck_color: tuple
    rail: tuple = (0.62, 0.66, 0.68)


# Each boat's hull. Families share their fittings; these numbers set the trim.
SPECS = {
    "log_raft": HullSpec(0.20, 0.0, 1.0, 1.0, 1.0, 0.20, (0.47, 0.33, 0.20), (0.40, 0.28, 0.17), (0.52, 0.37, 0.22)),
    "birch_skiff": HullSpec(0.30, 0.16, 0.0, 0.0, 0.45, 0.06, (0.86, 0.82, 0.70), (0.66, 0.50, 0.32), (0.58, 0.44, 0.28)),
    "reed_dugout": HullSpec(0.26, 0.06, 0.14, 0.18, 0.55, 0.05, (0.36, 0.25, 0.15), (0.48, 0.34, 0.20), (0.44, 0.31, 0.19)),
    "dory": HullSpec(0.52, 0.24, 0.0, 0.34, 0.50, 0.10, (0.90, 0.88, 0.80), (0.84, 0.80, 0.66), (0.62, 0.47, 0.30), (0.20, 0.42, 0.30)),
    "flat_skiff": HullSpec(0.40, 0.08, 0.58, 0.86, 0.90, 0.08, (0.42, 0.53, 0.58), (0.74, 0.74, 0.68), (0.56, 0.44, 0.30)),
    "river_runner": HullSpec(0.44, 0.10, 0.62, 0.94, 0.88, 0.10, (0.84, 0.86, 0.84), (0.70, 0.72, 0.72), (0.62, 0.64, 0.62)),
    "duck_jon": HullSpec(0.46, 0.10, 0.64, 0.94, 0.88, 0.10, (0.36, 0.38, 0.24), (0.40, 0.36, 0.24), (0.46, 0.42, 0.30)),
    "marsh_runner": HullSpec(0.48, 0.12, 0.50, 0.90, 0.80, 0.16, (0.78, 0.80, 0.74), (0.82, 0.82, 0.78), (0.70, 0.70, 0.66)),
    "deepv_skiff": HullSpec(0.62, 0.22, 0.0, 0.80, 0.25, 0.22, (0.16, 0.30, 0.52), (0.86, 0.86, 0.84), (0.74, 0.74, 0.72)),
    "coastal_craft": HullSpec(0.70, 0.30, 0.10, 0.84, 0.30, 0.26, (0.88, 0.88, 0.84), (0.86, 0.86, 0.82), (0.66, 0.68, 0.66)),
    "mahogany_runabout": HullSpec(0.56, 0.16, 0.0, 0.78, 0.30, 0.20, (0.44, 0.20, 0.10), (0.78, 0.70, 0.56), (0.52, 0.26, 0.13), (0.82, 0.80, 0.74)),
    "fiberglass_cruiser": HullSpec(0.74, 0.26, 0.0, 0.82, 0.30, 0.28, (0.93, 0.93, 0.90), (0.84, 0.82, 0.76), (0.60, 0.46, 0.30)),
    "lake_taxi": HullSpec(0.64, 0.18, 0.20, 0.90, 0.40, 0.24, (0.92, 0.74, 0.20), (0.90, 0.88, 0.80), (0.62, 0.48, 0.32)),
    "small_sloop": HullSpec(0.60, 0.22, 0.0, 0.60, 0.35, 0.18, (0.90, 0.90, 0.86), (0.82, 0.80, 0.72), (0.56, 0.40, 0.24)),
    "tug_skiff": HullSpec(0.72, 0.26, 0.38, 0.80, 0.60, 0.26, (0.20, 0.38, 0.30), (0.74, 0.66, 0.50), (0.48, 0.36, 0.24), (0.86, 0.80, 0.64)),
    "party_barge": HullSpec(0.70, 0.0, 1.0, 1.0, 1.0, 0.70, (0.84, 0.86, 0.86), (0.80, 0.80, 0.76), (0.52, 0.44, 0.34)),
    "houseboat": HullSpec(0.72, 0.0, 1.0, 1.0, 1.0, 0.72, (0.86, 0.84, 0.76), (0.82, 0.80, 0.72), (0.50, 0.40, 0.30)),
    "steam_barge": HullSpec(0.62, 0.10, 0.62, 0.90, 0.85, 0.40, (0.30, 0.20, 0.44), (0.40, 0.30, 0.54), (0.34, 0.28, 0.42), (0.86, 0.72, 0.38)),
    "nebula_cruiser": HullSpec(0.58, 0.18, 0.0, 0.70, 0.30, 0.22, (0.30, 0.62, 0.70), (0.30, 0.34, 0.46), (0.24, 0.26, 0.36), (0.72, 0.84, 0.92)),
    "celestial_flagship": HullSpec(0.80, 0.24, 0.30, 0.90, 0.60, 0.42, (0.36, 0.26, 0.56), (0.42, 0.36, 0.60), (0.32, 0.30, 0.46), (0.90, 0.80, 0.50)),
}


class _Mesh:
    """Quads in eye-local space, with optional night emission."""

    def __init__(self):
        self.faces: list[Face] = []

    def quad(self, points, color, normal=None, emissive=None):
        points = np.asarray(points, np.float32)
        if len(points) == 3:
            points = np.vstack([points, points[-1]])
        n = (np.cross(points[1] - points[0], points[2] - points[0]) if normal is None
             else np.asarray(normal, np.float32))
        n = n / (np.linalg.norm(n) + 1e-8)
        self.faces.append(Face(points, n.astype(np.float32), np.asarray(color, np.float32), "cam", emissive))

    def box(self, centre, size, color, emissive=None):
        x, y, z = centre
        a, b, d = np.asarray(size, np.float32) * 0.5
        q = self.quad
        q([(x-a, y+b, z-d), (x+a, y+b, z-d), (x+a, y+b, z+d), (x-a, y+b, z+d)], color, (0, 1, 0), emissive)
        q([(x-a, y-b, z-d), (x+a, y-b, z-d), (x+a, y+b, z-d), (x-a, y+b, z-d)], color, (0, 0, -1), emissive)
        q([(x-a, y-b, z+d), (x-a, y+b, z+d), (x+a, y+b, z+d), (x+a, y-b, z+d)], color, (0, 0, 1), emissive)
        q([(x-a, y-b, z-d), (x-a, y+b, z-d), (x-a, y+b, z+d), (x-a, y-b, z+d)], color, (-1, 0, 0), emissive)
        q([(x+a, y-b, z-d), (x+a, y-b, z+d), (x+a, y+b, z+d), (x+a, y+b, z-d)], color, (1, 0, 0), emissive)

    def tube(self, a, b, r, color, sides=6, emissive=None):
        a, b = np.asarray(a, np.float32), np.asarray(b, np.float32)
        axis = b - a
        axis = axis / (np.linalg.norm(axis) + 1e-8)
        ref = np.array([0, 1, 0] if abs(axis[1]) < 0.9 else [1, 0, 0], np.float32)
        u = np.cross(axis, ref)
        u = u / (np.linalg.norm(u) + 1e-8)
        v = np.cross(axis, u)
        for i in range(sides):
            t, s = i * math.tau / sides, (i + 1) * math.tau / sides
            n, m = math.cos(t) * u + math.sin(t) * v, math.cos(s) * u + math.sin(s) * v
            self.quad([a + n * r, b + n * r, b + m * r, a + m * r], color, n + m, emissive)

    def ring(self, centre, radius, r, color, segments=10, axis="z"):
        cx, cy, cz = centre
        for i in range(segments):
            a, b = i * math.tau / segments, (i + 1) * math.tau / segments
            if axis == "z":
                p = (cx + math.cos(a) * radius, cy + math.sin(a) * radius, cz)
                q = (cx + math.cos(b) * radius, cy + math.sin(b) * radius, cz)
            else:
                p = (cx + math.cos(a) * radius, cy, cz + math.sin(a) * radius)
                q = (cx + math.cos(b) * radius, cy, cz + math.sin(b) * radius)
            self.tube(p, q, r, color, 4)


# --- the shared hull ---------------------------------------------------------

def _smooth(t):
    t = min(1.0, max(0.0, t))
    return t * t * (3 - 2 * t)


class _Hull:
    """One boat's sections: half-widths and heights at each station, eye-local."""

    def __init__(self, model, spec):
        self.model, self.spec = model, spec
        self.water = -model.eye_height
        self.t = np.linspace(0.0, 1.0, STATIONS)
        self.z = model.stern + self.t * model.length

    def width(self, t):
        s = self.spec
        if t < 0.4:
            fraction = s.stern_width + (1 - s.stern_width) * _smooth(t / 0.4)
        else:
            fraction = 1 - (1 - s.bow_width) * ((t - 0.4) / 0.6) ** 1.7
        return self.model.half_beam * fraction

    def gunwale(self, t):
        return self.water + self.spec.sheer + self.spec.bow_rise * t ** 2.2

    def chine_y(self):
        return self.water - self.model.draft * (0.35 if self.spec.bottom < 0.5 else 0.85)

    def keel_y(self):
        return self.water - self.model.draft

    def deck_y(self):
        return self.water + self.spec.deck

    def at(self, z):
        t = (z - self.model.stern) / self.model.length
        return self.width(t), self.gunwale(t)


def _shell(m, hull, colour, inner, deck):
    """Sides, liner, floor, bottom, transom and stem for a monohull."""
    s = hull.spec
    rail = np.asarray(s.rail, np.float32)
    widths = [hull.width(t) for t in hull.t]
    tops = [hull.gunwale(t) for t in hull.t]
    chine, keel, floor = hull.chine_y(), hull.keel_y(), hull.deck_y()
    for i in range(STATIONS - 1):
        z0, z1 = hull.z[i], hull.z[i + 1]
        w0, w1, g0, g1 = widths[i], widths[i + 1], tops[i], tops[i + 1]
        c0, c1 = w0 * s.bottom, w1 * s.bottom
        for side in (-1, 1):
            m.quad([(side*w0, g0, z0), (side*w1, g1, z1), (side*c1, chine, z1), (side*c0, chine, z0)],
                   colour, (side, 0.1, 0))
            # The liner shows from the helm; it meets the floor slightly inboard.
            m.quad([(side*w0*0.93, g0-0.03, z0), (side*w1*0.93, g1-0.03, z1),
                    (side*w1*0.86, floor, z1), (side*w0*0.86, floor, z0)], inner, (-side, 0.2, 0))
            # A flat cap rail along the sheer, and a darker rub strip outboard.
            m.quad([(side*w0*0.93, g0-0.03, z0), (side*w0, g0, z0), (side*w1, g1, z1),
                    (side*w1*0.93, g1-0.03, z1)], rail, (0, 1, 0))
            m.quad([(side*w0*1.005, g0-0.05, z0), (side*w1*1.005, g1-0.05, z1),
                    (side*w1*1.005, g1-0.09, z1), (side*w0*1.005, g0-0.09, z0)], colour * 0.62, (side, 0, 0))
            if s.bottom < 0.5:
                m.quad([(side*c0, chine, z0), (side*c1, chine, z1), (0, keel, z1), (0, keel, z0)],
                       colour * 0.8, (side * 0.4, -1, 0))
        if s.bottom >= 0.5:
            m.quad([(-c0, chine, z0), (-c1, chine, z1), (c1, chine, z1), (c0, chine, z0)], colour * 0.8, (0, -1, 0))
        m.quad([(-w0*0.86, floor, z0), (w0*0.86, floor, z0), (w1*0.86, floor, z1), (-w1*0.86, floor, z1)],
               deck, (0, 1, 0))
    if widths[0] > 0.05:
        w, g = widths[0], tops[0]
        m.quad([(-w, g, hull.z[0]), (w, g, hull.z[0]), (w*s.bottom, chine, hull.z[0]),
                (-w*s.bottom, chine, hull.z[0])], colour * 0.9, (0, 0, -1))
    if widths[-1] > 0.05:
        w, g = widths[-1], tops[-1]
        m.quad([(-w, g, hull.z[-1]), (-w*s.bottom, chine, hull.z[-1]), (w*s.bottom, chine, hull.z[-1]),
                (w, g, hull.z[-1])], colour * 0.9, (0, 0, 1))
    else:
        m.tube((0, tops[-1] + 0.02, hull.z[-1]), (0, keel, hull.z[-1] - 0.05), 0.03, rail, 4)


def _platform(m, hull, colour, deck, tubes, radius):
    """Pontoon and barge decks: a flat deck on two or three round tubes."""
    model = hull.model
    floor = hull.deck_y()
    z0, z1 = model.stern, model.bow
    beam = model.half_beam
    m.box((0, floor - 0.06, (z0 + z1) * 0.5), (beam * 2, 0.12, model.length), deck)
    for x in tubes:
        y = hull.water - radius * 0.35
        m.tube((x, y, z0 + 0.1), (x, y, z1 - radius), radius, colour, 10)
        m.tube((x, y, z1 - radius), (x, y + radius * 0.4, z1), radius * 0.55, colour, 8)
    # Fence panels and a top rail around the deck edge.
    for side in (-1, 1):
        m.box((side * (beam - 0.03), floor + 0.36, (z0 + z1) * 0.5), (0.05, 0.60, model.length - 0.3),
              colour * 0.9)
        m.tube((side * beam, floor + 0.74, z0 + 0.15), (side * beam, floor + 0.74, z1 - 0.15), 0.025,
               hull.spec.rail, 4)


# --- fittings -------------------------------------------------------------------

def _bench(m, hull, z, colour, depth=0.30, height=0.18):
    w, g = hull.at(z)
    y = min(g - 0.08, hull.deck_y() + 0.40)
    m.box((0, y, z), (w * 1.7, height * 0.5, depth), colour)


def _paddle(m, hull, wood, z=None):
    z = hull.model.stern * 0.2 if z is None else z
    w, g = hull.at(z)
    m.tube((w * 0.6, g + 0.05, z - 0.55), (w * 0.4, g - 0.05, z + 0.55), 0.02, wood, 4)
    m.quad([(w*0.62-0.08, g+0.06, z+0.55), (w*0.62+0.08, g+0.06, z+0.55), (w*0.62+0.07, g+0.02, z+0.95),
            (w*0.62-0.07, g+0.02, z+0.95)], wood * 0.9, (0, 1, 0))


def _oars(m, hull, z, wood, metal):
    w, g = hull.at(z)
    for side in (-1, 1):
        m.tube((side * w, g + 0.02, z), (side * w, g + 0.10, z), 0.02, metal, 4)
        m.tube((side * w * 0.3, g + 0.08, z - 0.2), (side * (w + 1.3), g - 0.12, z - 0.35), 0.022, wood, 4)
        bx = side * (w + 1.3)
        m.quad([(bx-0.08, g-0.10, z-0.48), (bx+0.08, g-0.10, z-0.48), (bx+0.08, g-0.14, z-0.22),
                (bx-0.08, g-0.14, z-0.22)], wood * 0.9, (0, 1, 0))


def _tiller_motor(m, hull, state, motor):
    model = hull.model
    w, g = hull.at(model.stern)
    z = model.stern - 0.12
    m.box((0, g + 0.06, z), (0.34, 0.34, 0.40), motor)
    m.tube((0, g - 0.12, z), (0, hull.water - 0.45, z - 0.05), 0.04, motor * 0.7, 6)
    angle = state.steer * 0.35
    m.tube((0.05, g + 0.10, z + 0.18), (0.05 + math.sin(angle) * 0.75, g + 0.16, z + 0.18 + math.cos(angle) * 0.75),
           0.022, (0.12, 0.13, 0.14), 4)


def _outboard(m, hull, motor, count=1):
    model = hull.model
    w, g = hull.at(model.stern)
    for i in range(count):
        x = 0 if count == 1 else (i - 0.5) * 0.6
        m.box((x, g + 0.12, model.stern - 0.22), (0.42, 0.58, 0.46), motor)
        m.tube((x, g - 0.20, model.stern - 0.26), (x, hull.water - 0.55, model.stern - 0.32), 0.05, motor * 0.7, 6)


def _wheel(m, state, centre, radius=0.16):
    dark, metal = (0.12, 0.14, 0.15), (0.66, 0.70, 0.72)
    m.ring(centre, radius, 0.014, dark, 10)
    for angle in (0, math.tau / 3, 2 * math.tau / 3):
        angle += state.steer * 0.7
        m.tube(centre, (centre[0] + math.cos(angle) * radius, centre[1] + math.sin(angle) * radius, centre[2]),
               0.008, metal, 4)


def _console(m, hull, state, z, colour, glass=(0.52, 0.68, 0.74), side=0.0):
    floor = hull.deck_y()
    top = min(floor + 0.92, -0.42)  # the helm always looks over its console
    m.box((side, (floor + top) * 0.5, z), (0.58, top - floor, 0.52), colour)
    m.box((side, top + 0.02, z - 0.08), (0.50, 0.04, 0.34), (0.10, 0.14, 0.16))
    m.quad([(side-0.26, top, z+0.20), (side+0.26, top, z+0.20), (side+0.24, top+0.18, z+0.30),
            (side-0.24, top+0.18, z+0.30)], glass, (0, 0.3, -1))
    _wheel(m, state, (side, top - 0.10, z - 0.30))


def _windshield(m, hull, z, glass=(0.54, 0.70, 0.78), height=0.34):
    w, g = hull.at(z)
    m.quad([(-w*0.86, g, z), (w*0.86, g, z), (w*0.70, g+height, z+0.18), (-w*0.70, g+height, z+0.18)],
           glass, (0, 0.3, -1))
    m.tube((-w*0.86, g, z), (-w*0.70, g+height, z+0.18), 0.015, (0.70, 0.72, 0.74), 4)
    m.tube((w*0.86, g, z), (w*0.70, g+height, z+0.18), 0.015, (0.70, 0.72, 0.74), 4)


def _canopy(m, hull, z0, z1, colour, height=1.95, posts=(0.70, 0.70, 0.72)):
    floor = hull.deck_y()
    w0, _ = hull.at(z0)
    w1, _ = hull.at(z1)
    half = min(w0, w1) * 0.92
    for z in (z0, z1):
        for side in (-1, 1):
            m.tube((side * half, floor, z), (side * half, floor + height, z), 0.022, posts, 4)
    m.box((0, floor + height + 0.03, (z0 + z1) * 0.5), (half * 2 + 0.1, 0.05, abs(z1 - z0) + 0.2), colour)


def _cabin(m, hull, z0, z1, wall, roof, height=1.0, inset=0.88, windows=(0.30, 0.44, 0.50)):
    floor = hull.deck_y()
    w, _ = hull.at((z0 + z1) * 0.5)
    half = w * inset
    centre = ((z0 + z1) * 0.5)
    m.box((0, floor + height * 0.5, centre), (half * 2, height, abs(z1 - z0)), wall)
    m.box((0, floor + height + 0.04, centre), (half * 2 + 0.12, 0.08, abs(z1 - z0) + 0.12), roof)
    # Window bands on both sides and the aft face, just proud of the walls.
    for side in (-1, 1):
        m.quad([(side*(half+0.005), floor+height*0.45, z0+0.15), (side*(half+0.005), floor+height*0.45, z1-0.15),
                (side*(half+0.005), floor+height*0.80, z1-0.15), (side*(half+0.005), floor+height*0.80, z0+0.15)],
               windows, (side, 0, 0))
    zf = min(z0, z1) - 0.005
    m.quad([(-half*0.7, floor+height*0.45, zf), (half*0.7, floor+height*0.45, zf),
            (half*0.7, floor+height*0.80, zf), (-half*0.7, floor+height*0.80, zf)], windows, (0, 0, -1))


def _stars(m, hull, count, colour=(0.96, 0.92, 0.70), seed=0):
    """Small emissive freckles scattered along the sheer, fixed per boat."""
    rng = np.random.default_rng(seed)
    for _ in range(count):
        t = float(rng.uniform(0.05, 0.95))
        side = 1 if rng.uniform() > 0.5 else -1
        z = hull.model.stern + t * hull.model.length
        w, g = hull.at(z)
        y = g - float(rng.uniform(0.10, 0.40))
        m.quad([(side*w*1.01, y, z), (side*w*1.01, y+0.04, z), (side*w*1.01, y+0.04, z+0.04),
                (side*w*1.01, y, z+0.04)], colour, (side, 0, 0), STAR)


def _sail(m, hull, state, cloth=(0.95, 0.93, 0.84), metal=(0.66, 0.70, 0.72)):
    """Mast, boom, mainsail and jib; the boom swings with the wind when raised."""
    model = hull.model
    mast_z = model.stern + model.length * 0.66
    deck = hull.deck_y() + 0.25
    top = deck + model.length * 0.95
    m.tube((0, deck, mast_z), (0, top, mast_z), 0.035, metal, 8)
    for side in (-1, 1):
        w, g = hull.at(mast_z - 0.3)
        m.tube((side * w, g, mast_z - 0.3), (0, top, mast_z), 0.005, (0.56, 0.60, 0.60), 4)
    m.tube((0, hull.gunwale(1.0), model.bow), (0, top, mast_z), 0.005, metal, 4)
    angle = 0.0
    if state.sail_raised:
        wind, _ = wind_at(state.game_minutes + state.minute_acc)
        relative = math.atan2(math.sin(wind - state.yaw), math.cos(wind - state.yaw))
        angle = -math.copysign(min(1.08, 0.25 + abs(relative) * 0.50), relative)
    boom = model.length * 0.42
    tack = (0, deck + 0.30, mast_z)
    clew = (math.sin(angle) * boom, deck + 0.30, mast_z - math.cos(angle) * boom)
    m.tube(tack, clew, 0.024, metal, 6)
    head = (0, top - 0.2, mast_z)
    if state.sail_raised:
        m.quad([tack, clew, head], cloth)
        m.quad([head, clew, tack], cloth)
        stem = (0, hull.gunwale(1.0) + 0.1, model.bow - 0.1)
        jib_clew = (math.sin(angle) * 0.9, deck + 0.4, mast_z + 0.35)
        m.quad([stem, jib_clew, head], cloth)
        m.quad([head, jib_clew, stem], cloth)
    else:
        m.tube(tack, clew, 0.07, cloth, 8)


def _lamp(m, hull, state):
    if state.light:
        _w, g = hull.at(hull.model.bow - 0.2)
        m.box((0, g + 0.08, hull.model.bow - 0.25), (0.17, 0.13, 0.16), (0.16, 0.19, 0.19))


# --- the eight families ----------------------------------------------------------

def _pioneer(m, hull, state, c):
    model = hull.model
    if model.id == "log_raft":
        logs = 6
        radius = model.half_beam / logs
        y = hull.water + 0.02
        for i in range(logs):
            x = -model.half_beam + radius * (2 * i + 1)
            m.tube((x, y, model.stern), (x, y, model.bow), radius * 0.98, c.hull * (0.92 + 0.04 * (i % 2)), 6)
        for z in (model.stern + 0.3, 0.0, model.bow - 0.3):
            m.box((0, y + radius * 0.9, z), (model.half_beam * 2.05, 0.03, 0.06), (0.62, 0.52, 0.34))
        m.box((0, y + radius + 0.01, (model.stern + model.bow) * 0.5),
              (model.half_beam * 1.6, 0.02, model.length * 0.85), c.deck)
        # The hammock hangs between two short posts aft.
        for x in (-model.half_beam * 0.7, model.half_beam * 0.7):
            m.tube((x, y + radius, model.stern + 0.35), (x, y + radius + 0.8, model.stern + 0.35), 0.03, c.hull, 4)
        sag = y + radius + 0.45
        m.quad([(-model.half_beam*0.68, y+radius+0.75, model.stern+0.28), (model.half_beam*0.68, y+radius+0.75, model.stern+0.28),
                (model.half_beam*0.3, sag, model.stern+0.42), (-model.half_beam*0.3, sag, model.stern+0.42)],
               (0.80, 0.70, 0.48), (0, 1, 0.2))
        m.tube((model.half_beam * 0.5, y + radius + 0.1, model.stern), (model.half_beam * 0.8, y + 0.9, model.bow + 0.6),
               0.022, (0.56, 0.42, 0.26), 4)
        return
    _shell(m, hull, c.hull, c.inner, c.deck)
    if model.id == "birch_skiff":
        for t in (0.25, 0.5, 0.75):
            z = model.stern + t * model.length
            w, g = hull.at(z)
            for side in (-1, 1):
                m.quad([(side*w*1.006, g-0.12, z-0.03), (side*w*1.006, g-0.12, z+0.03),
                        (side*w*1.006, g-0.26, z+0.03), (side*w*1.006, g-0.26, z-0.03)], (0.30, 0.24, 0.18), (side, 0, 0))
        _bench(m, hull, model.length * 0.12, c.inner, 0.10, 0.06)
    else:
        for z in (model.bow - 0.5, model.bow - 0.75):
            m.tube((-0.18, hull.gunwale(0.9) + 0.06, z), (0.18, hull.gunwale(0.9) + 0.06, z), 0.05, (0.62, 0.58, 0.32), 6)
    _paddle(m, hull, np.asarray((0.62, 0.45, 0.27), np.float32))


def _rowed(m, hull, state, c):
    model = hull.model
    _shell(m, hull, c.hull, c.inner, c.deck)
    _bench(m, hull, model.stern + 0.45, c.deck)
    _bench(m, hull, 0.0, c.deck)
    _bench(m, hull, model.bow - 0.8, c.deck)
    _oars(m, hull, 0.05, np.asarray((0.64, 0.46, 0.27), np.float32), (0.66, 0.70, 0.72))


def _jon(m, hull, state, c):
    model = hull.model
    _shell(m, hull, c.hull, c.inner, c.deck)
    for z in (model.stern + 0.55, 0.9, model.bow - 0.7):
        _bench(m, hull, z, c.hull * 0.9)
    _tiller_motor(m, hull, state, c.motor)
    if model.id == "duck_jon":
        # A folded grass blind frame along both gunwales.
        for side in (-1, 1):
            for z in np.linspace(model.stern + 0.6, model.bow - 0.5, 4):
                w, g = hull.at(z)
                m.tube((side * w, g, z), (side * w * 0.9, g + 0.45, z), 0.012, (0.40, 0.36, 0.22), 4)
            z0, z1 = model.stern + 0.6, model.bow - 0.5
            w0, g0 = hull.at(z0)
            w1, g1 = hull.at(z1)
            m.quad([(side*w0*0.9, g0+0.45, z0), (side*w1*0.9, g1+0.45, z1), (side*w1, g1+0.05, z1),
                    (side*w0, g0+0.05, z0)], (0.58, 0.52, 0.30), (side, 0.3, 0))


def _utility(m, hull, state, c):
    model = hull.model
    _shell(m, hull, c.hull, c.inner, c.deck)
    _console(m, hull, state, 1.10, c.hull * 0.95, side=0.34)
    _bench(m, hull, model.stern + 0.55, c.inner)
    _outboard(m, hull, c.motor)
    # Front casting deck.
    w, g = hull.at(model.bow - 0.9)
    m.box((0, hull.deck_y() + 0.22, model.bow - 0.85), (w * 1.6, 0.06, 1.0), c.deck)
    if model.id == "coastal_craft":
        _canopy(m, hull, -0.3, 0.9, (0.20, 0.30, 0.38), 1.75)
    if "trophy_rail" in model.traits:
        _trophy_rail(m, hull)


def _trophy_rail(m, hull):
    z0, z1 = hull.model.stern + 0.4, hull.model.stern + 1.4
    w0, g0 = hull.at(z0)
    m.tube((-w0 * 0.8, g0 + 0.12, z0), (-w0 * 0.8, g0 + 0.12, z1), 0.018, (0.86, 0.76, 0.42), 4)
    for z in (z0, z1):
        m.tube((-w0 * 0.8, g0, z), (-w0 * 0.8, g0 + 0.12, z), 0.014, (0.86, 0.76, 0.42), 4)


def _runabout(m, hull, state, c):
    model = hull.model
    _shell(m, hull, c.hull, c.inner, c.deck)
    if model.id == "mahogany_runabout":
        # Varnished foredeck planks with pale caulking seams.
        z0 = 0.55
        w, g = hull.at(z0)
        m.quad([(-w, g+0.01, z0), (w, g+0.01, z0), (0.05, hull.gunwale(1.0)+0.01, model.bow-0.05),
                (-0.05, hull.gunwale(1.0)+0.01, model.bow-0.05)], c.hull * 1.15, (0, 1, 0))
        for x in (-0.25, 0.0, 0.25):
            m.tube((x, g + 0.015, z0 + 0.05), (x * 0.1, hull.gunwale(1.0) + 0.015, model.bow - 0.1),
                   0.004, (0.86, 0.80, 0.62), 4)
        _windshield(m, hull, 0.45)
        _bench(m, hull, -0.25, c.inner, 0.45, 0.30)
        m.box((0, hull.deck_y() + 0.30, model.stern + 0.55), (model.half_beam * 1.3, 0.24, 0.8), c.hull)
        _wheel(m, state, (0.0, hull.gunwale(0.45) - 0.05, 0.25))
        if "trophy_rail" in model.traits:
            _trophy_rail(m, hull)
    elif model.id == "fiberglass_cruiser":
        _cabin(m, hull, 1.15, model.bow - 0.7, c.hull, (0.86, 0.86, 0.82), 0.62, 0.80)
        _windshield(m, hull, 1.05, height=0.42)
        _console(m, hull, state, 0.75, c.hull * 0.9)
        _bench(m, hull, model.stern + 0.6, c.inner, 0.50, 0.30)
        # A small galley block opposite the helm.
        m.box((-0.45, hull.deck_y() + 0.42, -0.2), (0.42, 0.84, 0.56), (0.80, 0.76, 0.66))
    else:
        for z in (-1.2, -0.4, 0.5, 1.4):
            _bench(m, hull, z, c.inner, 0.36, 0.26)
        _canopy(m, hull, -1.5, 1.8, (0.94, 0.94, 0.90), 1.85)
        _console(m, hull, state, 0.85, c.hull * 0.9)
    _lamp(m, hull, state)


def _sail_trawler(m, hull, state, c):
    model = hull.model
    _shell(m, hull, c.hull, c.inner, c.deck)
    if model.id == "small_sloop":
        for side in (-1, 1):
            w, _g = hull.at(-0.2)
            m.box((side * w * 0.7, hull.deck_y() + 0.32, -0.3), (0.26, 0.16, 1.6), c.deck)
        m.tube((0, hull.gunwale(0.0) - 0.05, model.stern + 0.1),
               (math.sin(state.steer * 0.35) * 0.9, hull.gunwale(0.0) + 0.02, model.stern + 1.0), 0.022, c.deck, 4)
        _sail(m, hull, state)
        if "trophy_rail" in model.traits:
            _trophy_rail(m, hull)
    else:
        # A stern wheelhouse behind the open helm, a stack, and fender bumpers along the sheer.
        _cabin(m, hull, model.stern + 0.45, -0.25, (0.86, 0.80, 0.64), (0.32, 0.20, 0.14), 1.55, 0.86)
        m.tube((0, hull.deck_y() + 0.4, -1.0), (0, hull.deck_y() + 2.2, -1.05), 0.13, (0.16, 0.14, 0.12), 8)
        for side in (-1, 1):
            for z in np.linspace(model.stern + 0.5, model.bow - 0.6, 5):
                w, g = hull.at(z)
                m.tube((side * w * 1.02, g - 0.08, z - 0.14), (side * w * 1.02, g - 0.08, z + 0.14), 0.07,
                       (0.12, 0.12, 0.12), 6)
        m.box((0, hull.deck_y() + 0.06, model.stern + 0.9), (model.half_beam * 1.2, 0.08, 1.1), (0.40, 0.30, 0.20))
        _wheel(m, state, (0.25, hull.deck_y() + 1.05, 0.40), 0.20)
    _lamp(m, hull, state)


def _pontoon(m, hull, state, c):
    model = hull.model
    beam = model.half_beam
    tubes = (-beam * 0.72, 0.0, beam * 0.72) if model.id == "party_barge" else (-beam * 0.70, beam * 0.70)
    _platform(m, hull, c.hull, c.deck, tubes, 0.27 if model.id == "party_barge" else 0.30)
    floor = hull.deck_y()
    if model.id == "party_barge":
        _canopy(m, hull, -1.6, 1.6, (0.18, 0.28, 0.40), 1.85)
        for side in (-1, 1):
            m.box((side * (beam - 0.4), floor + 0.24, -1.0), (0.6, 0.45, 1.4), (0.80, 0.78, 0.70))
            m.box((side * (beam - 0.4), floor + 0.24, 2.2), (0.6, 0.45, 1.4), (0.80, 0.78, 0.70))
        m.box((-(beam - 0.45), floor + 0.45, model.stern + 0.8), (0.5, 0.9, 0.5), (0.74, 0.70, 0.62))  # galley
        _console(m, hull, state, 1.20, c.hull, side=0.35)
    else:
        # The living cabin sits behind the forward helm deck.
        _cabin(m, hull, model.stern + 0.5, -0.6, (0.86, 0.80, 0.66), (0.42, 0.26, 0.18), 2.0, 0.86)
        m.box((0.35, floor + 0.55, 0.85), (0.5, 1.1, 0.4), (0.74, 0.66, 0.52))
        _wheel(m, state, (0.35, floor + 1.15, 0.55), 0.20)
    _lamp(m, hull, state)


def _cosmic(m, hull, state, c):
    model = hull.model
    if model.id == "steam_barge":
        beam = model.half_beam
        _platform(m, hull, c.hull, c.deck, (-beam * 0.7, beam * 0.7), 0.28)
        floor = hull.deck_y()
        for x in (-0.45, 0.45):
            m.tube((x, floor, model.stern + 1.0), (x, floor + 1.9, model.stern + 1.0), 0.16, (0.20, 0.16, 0.26), 8)
            m.ring((x, floor + 1.95, model.stern + 1.0), 0.17, 0.03, (0.96, 0.86, 0.56), 8, axis="y")
            m.box((x, floor + 2.05, model.stern + 1.0), (0.14, 0.10, 0.14), (0.98, 0.94, 0.72), STAR)
        _cabin(m, hull, 0.9, 2.3, (0.42, 0.34, 0.58), (0.86, 0.74, 0.40), 0.60, 0.55)
        _wheel(m, state, (0.3, floor + 1.0, 0.0), 0.2)
    else:
        _shell(m, hull, c.hull, c.inner, c.deck)
        # Swept fins aft and a glass canopy ahead of the helm.
        for side in (-1, 1):
            z0 = model.stern + 0.2
            w, g = hull.at(z0)
            m.quad([(side*w, g, z0), (side*(w+0.35), g+0.30, z0-0.25), (side*(w+0.35), g+0.30, z0+0.15),
                    (side*w, g, z0+0.9)], c.hull * 1.2, (side, 0.4, 0))
            m.quad([(side*(w+0.35), g+0.30, z0+0.15), (side*(w+0.35), g+0.30, z0-0.25), (side*w, g, z0),
                    (side*w, g, z0+0.9)], c.hull * 1.2, (-side, 0.4, 0))
        _windshield(m, hull, 0.6, glass=(0.58, 0.72, 0.86), height=0.40)
        _bench(m, hull, -0.4, c.inner, 0.5, 0.30)
        _wheel(m, state, (0.0, hull.gunwale(0.5) - 0.05, 0.3))
        if model.id == "celestial_flagship":
            _cabin(m, hull, 1.4, 3.0, (0.50, 0.40, 0.66), (0.90, 0.80, 0.50), 0.90, 0.60)
            mast_z = 2.6
            top = hull.deck_y() + 4.6
            m.tube((0, hull.deck_y() + 1.6, mast_z), (0, top, mast_z), 0.05, (0.86, 0.80, 0.50), 6)
            m.box((0, top + 0.18, mast_z), (0.20, 0.36, 0.20), (0.86, 0.92, 1.0), STAR)
            _canopy(m, hull, -2.6, -0.8, (0.30, 0.22, 0.46), 2.0)
        if "trophy_rail" in model.traits:
            _trophy_rail(m, hull)
    _stars(m, hull, 26 if model.id == "celestial_flagship" else 18, seed=len(model.id))
    _lamp(m, hull, state)


FAMILIES = {
    "pioneer": _pioneer, "rowed": _rowed, "jon": _jon, "utility": _utility,
    "runabout": _runabout, "sail_trawler": _sail_trawler, "pontoon": _pontoon, "cosmic": _cosmic,
}


def _colours(model, look):
    spec = SPECS[model.id]
    hull = (np.asarray(spec.hull, np.float32) if look.get("hull", "aluminum") == "aluminum"
            else np.asarray(paint_rgb("hull", look["hull"]), np.float32))
    deck = (np.asarray(spec.deck_color, np.float32) if look.get("deck", "aluminum") == "aluminum"
            else np.asarray(paint_rgb("deck", look["deck"]), np.float32))
    motor = np.asarray(paint_rgb("motor", look.get("motor", "black")), np.float32)
    return SimpleNamespace(hull=hull, deck=deck, motor=motor, inner=np.asarray(spec.inner, np.float32))


def family_faces(state) -> list[Face]:
    """The first-person mesh of a generated boat, from its family and paint."""
    model = state.boat
    m = _Mesh()
    FAMILIES[model.family](m, _Hull(model, SPECS[model.id]), state, _colours(model, state.look_paint))
    return m.faces


def perch(model) -> tuple[float, float, float]:
    """Where Bot's feet rest on a generated boat: the centreline foredeck."""
    hull = _Hull(model, SPECS[model.id])
    z = model.bow - max(0.6, model.length * 0.16)
    _w, g = hull.at(z)
    return 0.0, max(hull.deck_y(), g - 0.12) + 0.02, z


def seat(model) -> tuple[float, float, float]:
    """Where an NPC cat sits on a generated boat, in its eye frame: the cockpit floor aft of centre."""
    hull = _Hull(model, SPECS[model.id])
    z = model.stern + model.length * 0.38
    _w, g = hull.at(z)
    return 0.0, max(hull.deck_y(), g - 0.12) + 0.02, z


def npc_faces(boat_id: str, x: float, z: float, yaw: float, look_paint=None) -> list[Face]:
    """A generated boat moved into the world at (x, z), bow along yaw, for NPC boats."""
    model = BOATS[boat_id]
    if model.handcrafted:
        raise ValueError(f"{boat_id} has a hand-built cockpit mesh; NPC boats use the generated families")
    pose = SimpleNamespace(boat=model, boat_id=boat_id, look_paint=dict(look_paint or {}),
                           steer=0.0, sail_raised=False, light=False, game_minutes=0.0,
                           minute_acc=0.0, yaw=yaw)
    faces = family_faces(pose)
    c, s = math.cos(yaw), math.sin(yaw)
    right, forward = np.array([c, 0, -s], np.float32), np.array([s, 0, c], np.float32)
    origin = np.array([x, model.eye_height, z], np.float32)
    basis = np.stack([right, np.array([0, 1, 0], np.float32), forward])
    return [Face((face.pts @ basis + origin).astype(np.float32), (face.normal @ basis).astype(np.float32),
                 face.color, "world", face.emissive) for face in faces]
