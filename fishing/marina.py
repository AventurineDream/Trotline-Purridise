"""Bounded, static marina scenery around the unchanged landing service slip.

Every new pier and moored hull shares one conservative rectangular footprint
with collision. Shore roots are measured against each lake's real water mask;
the wide lane between the wings remains open to every player boat.
"""

from dataclasses import dataclass
import math

import numpy as np

from .world import _box, _face


@dataclass(frozen=True)
class Footprint:
    name: str
    kind: str
    a: float
    s: float
    half_a: float
    half_s: float

    @property
    def rectangle(self):
        return self.a, self.s, self.half_a, self.half_s


@dataclass
class Marina:
    faces: list
    footprints: tuple[Footprint, ...]
    shore_buildings: tuple[Footprint, ...]

    @property
    def barriers(self):
        return np.asarray([p.rectangle for p in self.footprints], np.float64).reshape(-1, 4)


def footprint_samples(footprint):
    """Corners, edge midpoints and centre, in the landing's local frame."""
    return [(footprint.a + da * footprint.half_a,
             footprint.s + ds * footprint.half_s)
            for da in (-1, 0, 1) for ds in (-1, 0, 1)]


def build_marina(world):
    sl = world.slip
    along = np.array((sl.ix, 0.0, sl.iz), np.float32)
    across = np.array((sl.sx, 0.0, sl.sz), np.float32)
    up = np.array((0.0, 1.0, 0.0), np.float32)
    faces, footprints, buildings = [], [], []
    cedar = world.id == "cedar"
    wood = (0.56, 0.43, 0.29) if cedar else (0.55, 0.39, 0.24)
    edge = (0.28, 0.25, 0.21)
    cream, metal = (0.85, 0.82, 0.69), (0.34, 0.39, 0.39)

    def point(a, s, y):
        x, z = sl.world(a, s)
        return np.array((x, y, z), np.float32)

    def box(a, s, y, la, ls, height, color):
        faces.extend(_box(point(a, s, y), along, up, across, (la, height, ls), color))

    def roof(a, s, y, la, ls, rise, color):
        for sign in (-1, 1):
            pts = [point(a + sign*la/2, s-ls/2, y), point(a + sign*la/2, s+ls/2, y),
                   point(a, s+ls/2, y+rise), point(a, s-ls/2, y+rise)]
            faces.append(_face(pts, up*la/2 + along*sign*rise, color))
        box(a, s, y+rise+0.015, 0.16, ls+0.1, 0.09, color)

    def dock(name, a, s, la, ls):
        footprints.append(Footprint(name, "pier", a, s, la/2, ls/2))
        box(a, s, 0.43, la, ls, 0.20, edge)
        # Separate planks and dark seams survive a view down the long walkway.
        count = max(1, math.ceil(la/0.66))
        for i in range(count):
            aa = a-la/2+(i+0.5)*la/count
            shade = 0.92+(i%5)*0.025
            box(aa, s, 0.548, la/count-0.028, ls-0.05, 0.038,
                tuple(c*shade for c in wood))
        for aa in np.linspace(a-la/2+0.3, a+la/2-0.3, max(2, math.ceil(la/5))):
            for ss in (s-ls/2+0.16, s+ls/2-0.16):
                box(float(aa), ss, -0.18, 0.21, 0.21, 1.8, edge)
        for aa in (a-la/2+0.4, a+la/2-0.4):
            # Low mooring cleats stay inside the deck collision footprint.
            box(aa, s, 0.65, 0.13, 0.10, 0.16, metal)
            box(aa, s, 0.72, 0.13, 0.46, 0.07, metal)

    def lamp(a, s):
        box(a, s, 1.67, 0.12, 0.12, 2.2, edge)
        box(a, s, 2.74, 0.34, 0.34, 0.11, metal)
        box(a, s, 2.51, 0.22, 0.22, 0.35, (0.94, 0.70, 0.31))
        box(a, s, 2.31, 0.30, 0.30, 0.08, metal)

    def ring(a, s):
        # A real opening, with orange/cream segments rather than an opaque disk.
        for i in range(12):
            t0, t1 = i*math.tau/12, (i+1)*math.tau/12
            pts = [point(a, s+math.sin(t)*r, 1.25+math.cos(t)*r)
                   for t, r in ((t0,.36),(t1,.36),(t1,.23),(t0,.23))]
            faces.append(_face(pts, -along, cream if i%3==0 else (0.86,0.28,0.11)))

    def shore_root(s):
        # Walk inward from known open water to the first bank, so a branching
        # Cedar shoreline cannot put the foot of a pier on an offshore island.
        previous = -55.0
        for a in np.arange(-54.5, 61.0, 0.5):
            if float(world.shore_sd(*sl.world(float(a), s))) >= 0:
                lo, hi = previous, float(a)
                for _ in range(12):
                    mid = (lo+hi)/2
                    if float(world.shore_sd(*sl.world(mid, s))) < 0:
                        lo = mid
                    else:
                        hi = mid
                return hi
            previous = float(a)
        raise ValueError(f"{world.id} marina has no shore root at side {s}")

    def boat(name, a, s, kind, color):
        length, beam = ((6.2,2.35) if kind=="cabin" else
                        (5.8,2.65) if kind=="pontoon" else (4.9,1.82))
        # Include the outboard cap and thin gunwales in the solid envelope.
        fp = Footprint(name, "boat", a, s, length/2+.25, beam/2+.08)
        # The authored locations are checked densely, including the hull edges.
        for aa in np.linspace(a-length/2, a+length/2, 7):
            for ss in np.linspace(s-beam/2, s+beam/2, 5):
                if float(world.shore_sd(*sl.world(float(aa),float(ss)))) > -1.0:
                    raise ValueError(f"{world.id} marina boat {name} is outside open water")
        footprints.append(fp)
        stations = ((-length/2,beam*.40),(-length*.28,beam/2),
                    (length*.27,beam*.44),(length/2,beam*.09))
        for (a0,b0),(a1,b1) in zip(stations,stations[1:]):
            for sign in (-1,1):
                pts = [point(a+a0,s+sign*b0,.48),point(a+a1,s+sign*b1,.48),
                       point(a+a1,s+sign*b1*.67,-.22),point(a+a0,s+sign*b0*.67,-.22)]
                faces.append(_face(pts, across*sign+up*.12, color))
                box(a+(a0+a1)/2,s+sign*(b0+b1)/2,.52,a1-a0,.07,.10,cream)
        box(a,s,.13,length*.76,beam*.67,.19,cream)
        box(a-length/2,s,.44,.12,beam*.80,.10,color)
        box(a+length*.32,s,.44,length*.26,beam*.55,.08,color)
        for seat in (-.24,.20):
            box(a+length*seat,s,.53,.37,beam*.75,.19,(0.70,0.59,0.41))
        if kind=="cabin":
            box(a-.15,s,.98,2.4,beam*.76,1.03,cream)
            for sign in (-1,1):
                box(a-.1,s+sign*beam*.385,1.13,1.3,.025,.40,(.12,.29,.31))
            box(a+.98,s,1.14,.035,beam*.65,.44,(.12,.29,.31))
            roof(a-.15,s,1.53,2.65,beam*.86,.11,(.20,.31,.35))
        elif kind=="pontoon":
            for sign in (-1,1):
                box(a,s+sign*beam*.34,.88,length*.69,.045,.59,cream)
                for aa in (a-length*.29,a+length*.29):
                    box(aa,s+sign*beam*.34,1.43,.045,.045,1.3,metal)
            roof(a,s,2.08,length*.71,beam*.83,.12,color)
        elif kind=="sail":
            box(a,s,3.58,.06,.06,6.2,metal)
            box(a+.6,s,1.28,1.6,.13,.13,cream)
            # Furled sail bundled on the boom, not a moving boat under sail.
            box(a+.6,s,1.36,1.7,.20,.18,(.77,.75,.64))
        else:
            box(a+.70,s,.84,.10,beam*.67,.37,(.16,.30,.33))
        box(a-length*.48,s,.47,.46,.44,.65,(.16,.19,.20))
        # A short mooring line joins the deck edge and the nearest cleat.
        sign = 1 if s>0 else -1
        box(a-length*.30,s-sign*beam*.54,.57,.10,.65,.035,(.70,.65,.47))

    palette = ((.23,.39,.43),(.66,.28,.20),(.78,.74,.57),(.25,.37,.24))
    for sign in (-1,1):
        s = sign*18.0
        root = shore_root(s)+2.0
        # Cedar's west bank curls sharply through the outer berths. Move the
        # whole wing lakeward relative to its own measured bank, preserving
        # the same berth spacing instead of placing a hull on dry terrain.
        near = min(-3.0 if cedar else -10.0,
                   min(shore_root(s),shore_root(s+sign*8.0))-5.0)
        fingers = tuple(near-11*j for j in reversed(range(4 if cedar else 3)))
        tip = fingers[0]-2.0
        dock(f"{'east' if sign>0 else 'west'} promenade",(root+tip)/2,s,root-tip,2.15)
        for j,a in enumerate(fingers):
            outer = s+sign*4.0
            dock(f"wing {sign} finger {j}",a,outer,1.45,8.0)
            if j in (0,len(fingers)-1):
                lamp(a,s)
                ring(a-.10,s)
        for j,(a0,a1) in enumerate(zip(fingers,fingers[1:])):
            a = (a0+a1)/2
            kind = ("cabin","pontoon","runabout")[j%3] if cedar else ("sail" if sign<0 and j==0 else "runabout")
            boat(f"wing {sign} berth {j}",a,s+sign*4.25,kind,palette[(j+(sign>0))%len(palette)])
        if cedar:
            # A high, continuous roof shades the outer finger berths; the
            # central service lane has an entirely open sky.
            canopy_a = (fingers[0]+fingers[-1])/2
            canopy_s = s+sign*4.0
            roof(canopy_a,canopy_s,3.30,fingers[-1]-fingers[0]+2.1,9.4,.28,(.27,.38,.40))
            for a in (fingers[0],fingers[-1]):
                for ss in (s,s+sign*7.5):
                    box(a,ss,1.91,.14,.14,2.65,metal)

    def building(name, a, s, la, ls, wall_color, roof_color):
        for offset in np.arange(0.0,31.0,2.0):
            fp = Footprint(name,"building",a+float(offset),s,la/2+.5,ls/2+.5)
            samples = [sl.world(aa,ss) for aa,ss in footprint_samples(fp)]
            if min(float(world.shore_sd(x,z)) for x,z in samples)>=1.0:
                a = fp.a
                break
        else:
            raise ValueError(f"{world.id} marina building {name} has a wet foundation")
        ground = max(float(world.sample_height(x,z)) for x,z in samples)
        base = ground+.12
        box(a,s,(base+.02)/2,la+.3,ls+.3,base-.02,(.38,.36,.30))
        box(a,s,base+1.35,la,ls,2.7,wall_color)
        roof(a,s,base+2.75,la+.85,ls+.85,.9,roof_color)
        for ss in (s-ls*.29,s+ls*.29):
            box(a-la/2-.035,ss,base+1.55,.075,ls*.23,.83,(.12,.25,.27))
            for dy in (-.47,.47):
                box(a-la/2-.08,ss,base+1.55+dy,.10,ls*.27,.075,cream)
        box(a-la/2-.04,s,base+.99,.10,1.0,1.98,(.28,.25,.20))
        box(a-la/2-.1,s,base+2.28,.12,ls*.70,.34,cream)
        box(a-la/2-.18,s,base+2.28,.04,ls*.56,.06,wall_color)
        for ss in (s-ls/2-.25,s+ls/2+.25):
            box(a-la/2-.85,ss,base+1.15,.11,.11,2.3,edge)
        roof(a-la/2-.8,s,base+2.35,2.5,ls+.8,.14,roof_color)
        buildings.append(fp)
        # Porch boxes and bait tubs give a useful human scale.
        for j in range(3):
            box(a-la/2-.6,s-ls/2+.8+j*.72,base+.25,.52,.58,.50,(.42,.32,.20))

    # The existing service shack remains the centre of both settlements.
    # Dry positions follow the bank independently on each side.
    building("boathouse", shore_root(-37)+12.5,-37,9.5,10.0,
             (.46,.53,.47) if cedar else (.55,.38,.25),(.28,.35,.37))
    building("landing cafe", shore_root(37)+12.5,37,8.5,9.2,
             (.72,.67,.50) if cedar else (.65,.52,.35),(.39,.25,.20))
    # Picnic terrace on the existing dry pad, clear of the service shack.
    for a,s in ((20,10),(25,10)):
        x,z = sl.world(a,s)
        ground = float(world.sample_height(x,z))
        box(a,s,ground+.82,1.55,2.9,.13,wood)
        for aa in (a-.9,a+.9):
            box(aa,s,ground+.46,.32,3.1,.10,wood)
            for ss in (s-.95,s+.95):
                box(aa,ss,ground+.23,.13,.13,.46,edge)
        for ss in (s-.9,s+.9):
            box(a,ss,ground+.42,.16,.16,.84,edge)
    return Marina(faces,tuple(footprints),tuple(buildings))
