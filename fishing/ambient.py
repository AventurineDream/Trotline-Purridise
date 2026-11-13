"""Small world-space wildlife meshes, rebuilt into one existing bounded buffer.

Gulls circle, swallows dart and herons beat their broad wings slowly. Dragonflies
work the sunny bank and fireflies pulse after dusk. Paths use stable lake zones
and shoreline cells rather than following the camera or retaining particles.
"""
from __future__ import annotations

import math
import numpy as np

from .weather import lighting_at
from .world import Face

MAX_FACES = 160
BIRD_SPECIES = ("gull", "swallow", "heron")


def _quad(out, points, color):
    p = np.asarray(points, np.float32)
    if len(p) == 3:
        p = np.vstack((p, p[-1]))
    out.append(Face(p, np.array([0, 1, 0], np.float32), np.asarray(color, np.float32)))


def _bird(out, x, y, z, yaw, species, t, phase):
    # Coordinates in the bird's body frame: span, height, forward.
    side = np.array([math.cos(yaw), 0, -math.sin(yaw)], np.float32)
    fwd = np.array([math.sin(yaw), 0, math.cos(yaw)], np.float32)
    origin = np.array([x, y, z], np.float32)
    def face(pts, color):
        _quad(out, [origin+side*a+np.array([0,b,0])+fwd*c for a,b,c in pts], color)
    scale, rate = {"gull": (0.70, 3.1), "swallow": (0.39, 7.5), "heron": (1.02, 1.65)}[species]
    beat = math.sin(t*rate+phase)
    color = {"gull": (0.82,0.85,0.80), "swallow": (0.10,0.20,0.25), "heron": (0.40,0.51,0.57)}[species]
    tip = (0.18,0.23,0.25) if species=="gull" else tuple(c*0.65 for c in color)
    length = 0.57 if species=="heron" else 0.30
    face([(-0.07,0,-length),(0.07,0,-length),(0.09,0,0.22),(-0.09,0,0.22)],color)
    for sign in (-1,1):
        elbow, wingtip = sign*scale*0.54, sign*scale
        lift = beat*scale*0.28
        face([(sign*0.04,0,0.14),(elbow,lift,0.03),(elbow,lift,-0.19),(sign*0.04,0,-0.12)],color)
        face([(elbow,lift,0.03),(wingtip,lift*1.45,-0.22),(elbow,lift,-0.19)],tip)
    if species=="heron":
        # Folded neck, dagger bill, and trailing legs distinguish the heron.
        face([(-0.045,0,0.14),(-0.045,0.15,0.39),(0.045,0.15,0.39),(0.045,0,0.14)],color)
        face([(-0.045,0.15,0.39),(0,0.13,0.75),(0.045,0.15,0.39)],(0.65,0.49,0.22))
        for a in (-0.05,0.05):
            face([(a-0.009,-0.02,-0.37),(a+0.009,-0.02,-0.37),(a+0.009,-0.09,-1.03),(a-0.009,-0.09,-1.03)],tip)
    else:
        face([(-0.06,0.005,0.19),(0,0.03,0.37),(0.06,0.005,0.19)],color)
        if species=="swallow":
            for sign in (-1,1):
                face([(0,0,-0.16),(sign*0.13,0,-0.56),(sign*0.08,0,-0.21)],tip)
        else:
            face([(-0.11,0,-0.22),(0.11,0,-0.22),(0.08,0,-0.43),(-0.08,0,-0.43)],color)


def _star_motes(state, world, out):
    """The Lagoon has no birds: small motes of starlight hover over the water.

    The same bounded 5x5 cell neighborhood as the fireflies, anchored to the
    water rather than the bank. Reduced Motion holds them still.
    """
    reduced = bool(state.v2.get("settings", {}).get("reduced_motion", False))
    t = 0.0 if reduced else float(state.anim)
    cx, cz = math.floor(state.x/8), math.floor(state.z/8)
    for iz in range(cz-2, cz+3):
        for ix in range(cx-2, cx+3):
            seed = ((ix*73856093) ^ (iz*19349663)) & 0xffff
            if seed % 3:
                continue
            x, z = ix*8+1.5+(seed%47)/10, iz*8+1.5+((seed//47)%47)/10
            if not 3 < math.hypot(x-state.x, z-state.z) < 19 or float(world.shore_sd(x, z)) > -2:
                continue
            x += math.sin(t*0.5+seed)*0.9
            z += math.cos(t*0.4+seed)*0.9
            y = 0.5+0.4*math.sin(t*0.9+seed)
            pulse = 0.5+0.5*math.sin(t*1.4+seed)
            r = 0.03+0.03*pulse
            col = (0.55, 0.95, 1.0) if seed % 2 else (1.0, 0.72, 0.96)
            _quad(out, [(x-r,y-r,z),(x+r,y-r,z),(x+r,y+r,z),(x-r,y+r,z)], col)
            _quad(out, [(x,y-r,z-r),(x,y-r,z+r),(x,y+r,z+r),(x,y+r,z-r)], col)
    for face in out:
        face.emissive = 1.0
    return out


def faces(state, world, light=None):
    light = lighting_at(state.game_minutes+state.minute_acc, state) if light is None else light
    out = []
    if world.nebula:
        from .finale import faces as finale_faces
        return _star_motes(state, world, out) + finale_faces(state, world)  # Settle In (V1-35)
    if world.caldera:
        from .caldera import thermal_faces
        out.extend(thermal_faces(state, world))
    elif world.generated:
        from .lakegen import smoke_faces
        out.extend(smoke_faces(state, world))
    reduced = bool(state.v2.get("settings", {}).get("reduced_motion", False))
    t = 0.0 if reduced else float(state.anim)
    # Only two nearby stable habitats are active, regardless of world size.
    nearby = sorted(world.zones, key=lambda row: (row[1]-state.x)**2+(row[2]-state.z)**2)[:2]
    if light['night'] < 0.65 and light['rain'] < 0.8:
        for habitat, row in enumerate(nearby):
            if math.hypot(row[1]-state.x,row[2]-state.z)>280:
                continue
            for i,species in enumerate(BIRD_SPECIES):
                phase = i*2.1+habitat*3.7
                rate = (0.09,0.22,0.055)[i]
                angle = t*rate+phase
                radius = (28,19,38)[i]
                x = row[1]+math.sin(angle)*radius
                z = row[2]+math.cos(angle)*radius*0.65
                y = (7.5,4.5,6.0)[i]+math.sin(t*0.6+phase)*0.6
                y = max(y,float(world.sample_height(x,z))+2.0)
                yaw = math.atan2(math.cos(angle),-math.sin(angle)*0.65)
                _bird(out,x,y,z,yaw,species,t,phase)
    if light['rain'] > 0.65:
        return out
    # A 5x5 cell neighborhood is bounded and anchored to the bank. No spawning
    # history or retained particle arrays accumulate during long sessions.
    from .calendar import lake_day
    special = lake_day(world.id, state.game_minutes)
    firefly_day = bool(special and special.fireflies and light["night"] > .25)
    cx,cz = math.floor(state.x/8),math.floor(state.z/8)
    count = 0
    for iz in range(cz-2,cz+3):
        for ix in range(cx-2,cx+3):
            seed = ((ix*73856093) ^ (iz*19349663)) & 0xffff
            x,z = ix*8+1.5+(seed%47)/10, iz*8+1.5+((seed//47)%47)/10
            distance = math.hypot(x-state.x,z-state.z)
            if not 3<distance<19 or not -7<float(world.shore_sd(x,z))<9:
                continue
            x += math.sin(t*0.8+seed)*0.85
            z += math.cos(t*0.7+seed)*0.85
            y = max(0,float(world.sample_height(x,z)))+0.65+0.35*math.sin(t*1.3+seed)
            if light['night']>0.25:
                pulse = (0.5+0.5*math.sin(t*1.8+seed))**4
                if pulse < (.04 if firefly_day else .12):
                    continue
                r = 0.018+0.025*pulse
                col = (0.98,0.69+0.12*pulse,0.12)
                _quad(out,[(x-r,y-r,z),(x+r,y-r,z),(x+r,y+r,z),(x-r,y+r,z)],col)
                _quad(out,[(x,y-r,z-r),(x,y-r,z+r),(x,y+r,z+r),(x,y+r,z-r)],col)
            else:
                # Blue-green body and two pairs of fast silver wings.
                _quad(out,[(x-.012,y,z-.12),(x+.012,y,z-.12),(x+.012,y,z+.12),(x-.012,y,z+.12)],(0.10,0.49,0.47))
                flap = math.sin(t*38+seed)*0.028
                for dz in (-0.04,0.04):
                    _quad(out,[(x-.13,y+flap,z+dz-.025),(x+.13,y-flap,z+dz-.025),(x+.10,y-flap,z+dz+.025),(x-.10,y+flap,z+dz+.025)],(0.63,0.74,0.70))
            count += 1
            if count >= (20 if firefly_day else 12):
                return out
    return out
