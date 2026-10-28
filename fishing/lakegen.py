"""Bounded procedural lake fields built from authored environment parameters."""

from __future__ import annotations

import math
import numpy as np


class LakeFields:
    def __init__(self, parameters):
        self.parameters = parameters
        self.bounds = tuple(parameters['bounds'])
        self.nx, self.nz = parameters['grid']
        self.zones = tuple(tuple(row) for row in parameters['zones'])
        points = np.asarray(parameters['outline'], np.float32)
        self.angles = points[:, 0] * np.float32(math.pi/180)
        self.radii = points[:, 1]

    def radius(self, angle):
        return np.interp(np.mod(angle, math.tau), self.angles, self.radii).astype(np.float32)

    def shore(self, x, z):
        x, z = np.broadcast_arrays(np.asarray(x, np.float32), np.asarray(z, np.float32))
        result = np.hypot(x, z) - self.radius(np.arctan2(z, x))
        for cx, cz, rx, rz, height in self.parameters.get('islands', ()):
            # Positive on the island, negative in the surrounding water.
            island = (1-np.hypot((x-cx)/rx,(z-cz)/rz))*min(rx,rz)
            result = np.maximum(result,island)
        return result.astype(np.float32)

    def depth(self, x, z):
        x, z = np.broadcast_arrays(np.asarray(x, np.float32), np.asarray(z, np.float32))
        sd = self.shore(x, z)
        distance = np.maximum(0, -sd)
        result = .5 + 15 * (1-np.exp(-distance/100))
        if self.parameters['kind'] == 'caldera':
            result = .9 + 61 * (1-np.exp(-distance/70))
        nearest = np.full(x.shape, np.inf, np.float32)
        for zone, cx, cz, radius in self.zones:
            distance_to_zone = np.hypot(x-cx, z-cz)
            lo, hi = self.parameters['depths'][zone]
            value = lo + (hi-lo) * np.clip(1-distance_to_zone/radius, 0, 1)
            take = (distance_to_zone <= radius) & (distance_to_zone < nearest)
            result = np.where(take, value, result)
            nearest = np.where(take, distance_to_zone, nearest)
        # A narrow gravel margin meets the actual shoreline continuously.
        edge = np.clip(distance/9, 0, 1)
        result = np.minimum(result, .4+distance*.55) * (1-edge) + result*edge
        return np.where(sd < 0, result, 0).astype(np.float32)

    def ground(self, x, z):
        x, z = np.broadcast_arrays(np.asarray(x, np.float32), np.asarray(z, np.float32))
        sd = self.shore(x, z)
        inland = np.maximum(sd, 0)
        blend = np.clip((inland-25)/135, 0, 1)
        blend = blend*blend*(3-2*blend)
        height = .45 + inland*.018
        for cx, cz, peak, width in self.parameters['peaks']:
            height += peak * np.exp(-((x-cx)**2+(z-cz)**2)/(2*width**2)) * blend
        if self.parameters['kind'] == 'caldera':
            rim_height,rise = self.parameters['rim']
            outer = np.maximum(0,np.hypot(x,z)-self.radius(np.arctan2(z,x)))
            wall = np.clip(outer/rise,0,1)
            height += rim_height*wall*wall*(3-2*wall)
            for cx,cz,rx,rz,peak in self.parameters['islands']:
                radial = np.hypot((x-cx)/rx,(z-cz)/rz)
                cone = peak*np.power(np.clip(1-radial,0,1),.72)
                height = np.where(radial<=1,np.maximum(.45,cone),height)
        # Small ridgeline facets, fixed in world coordinates and independent of RNG.
        height += (np.sin(x*.023+z*.016)*5 + np.sin(x*.009-z*.031)*3) * blend
        return np.where(sd >= 0, np.maximum(.45, height), 0).astype(np.float32)

    def bake(self):
        x0, z0, x1, z1 = self.bounds
        x, z = np.meshgrid(np.linspace(x0, x1, self.nx, dtype=np.float32),
                           np.linspace(z0, z1, self.nz, dtype=np.float32))
        angles = np.linspace(0, math.tau, 360, endpoint=False)
        radius = self.radius(angles)
        coast = np.stack((np.cos(angles)*radius, np.sin(angles)*radius,
                          np.cos(angles), np.sin(angles)), axis=1).astype(np.float32)
        for cx,cz,rx,rz,height in self.parameters.get('islands', ()):
            ia = np.linspace(0,math.tau,96,endpoint=False)
            island = np.stack((cx+np.cos(ia)*rx,cz+np.sin(ia)*rz,
                               -np.cos(ia),-np.sin(ia)),axis=1).astype(np.float32)
            coast = np.concatenate((coast,island))
        return self.shore(x, z), self.depth(x, z), coast


def larch_gold(state):
    from .calendar import lake_day
    special = lake_day(state.lake_id, state.game_minutes)
    return bool(special and special.id == 'larch_gold')


def alpine_props(world, prop_type):
    parameters = world.environment
    rng = np.random.default_rng(parameters['seed'])
    result = []
    for index in range(parameters['tree_count'] * 3):
        angle = float(rng.uniform(0, math.tau))
        radius = float(world.fields.radius(angle)) + float(rng.uniform(8, 185))
        x, z = math.cos(angle)*radius, math.sin(angle)*radius
        a, s = world.slip.local(x, z)
        if -60 < a < 75 and abs(s) < 85:
            continue
        if float(world.sample_height(x, z)) > parameters["snow_line"]-15:
            continue
        kind = 'larch' if index % 3 else 'spruce'
        result.append(prop_type(kind, x, z, float(rng.uniform(13, 25)), float(rng.uniform(.82, 1.05))))
        if len(result) == parameters['tree_count']:
            break
    # Dead larch trunks mark the flooded snag habitat. Their footprints enter
    # the same round-obstacle collision table as Briar's stumps.
    for index in range(12):
        x, z = 515 + (index%3)*7, 20 + (index//3)*29
        if float(world.shore_sd(x, z)) < -3:
            result.append(prop_type('stump', x, z, 4.5+(index%4)*.65, .78))
    # Small riprap details live on the dry reef bank, outside boating lanes.
    for angle in np.linspace(4.75, 5.55, 14):
        radius = float(world.fields.radius(angle)) + 4
        result.append(prop_type('rock', math.cos(angle)*radius, math.sin(angle)*radius, .8, .95))
    return result


def chimney_faces(world):
    from .world import _box
    sl = world.slip
    x, z = sl.world(18.8, -1.0)
    return _box((x, 4.55, z), (sl.ix, 0, sl.iz), (0, 1, 0), (sl.sx, 0, sl.sz),
                (.42, 1.65, .42), (.23, .25, .26))


def smoke_faces(state, world):
    from .world import _face
    x, z = world.slip.world(18.8, -1.0)
    phase = 0 if state.v2.get('settings', {}).get('reduced_motion', False) else state.anim
    faces = []
    for index in range(6):
        age = (phase*.22+index/6) % 1
        radius = .16+age*.42
        cx, cy, cz = x+age*1.6, 5.45+age*3.8, z+math.sin(index+age)*.35
        # Six crossed stove-smoke wisps remain visible from either bank.
        # No particle history or retained buffers.
        faces.append(_face([(cx-radius,cy-radius,cz),(cx+radius,cy-radius,cz),
                            (cx+radius,cy+radius,cz),(cx-radius,cy+radius,cz)],
                           (0,0,1), (.48+age*.16,.51+age*.16,.53+age*.16)))
        faces.append(_face([(cx,cy-radius,cz-radius),(cx,cy-radius,cz+radius),
                            (cx,cy+radius,cz+radius),(cx,cy+radius,cz-radius)],
                           (1,0,0), (.48+age*.16,.51+age*.16,.53+age*.16)))
    return faces
