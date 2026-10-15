"""Boat models, handling, and shared full-hull collision geometry, in metres."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

HULL_BOW = 2.86
HULL_STERN = -0.80
HULL_HALF_BEAM = 0.70
HULL_INNER_BEAM = 0.64
HULL_CLEARANCE = 0.04
THROTTLE_RATE = 0.50
REVERSE_LIMIT = -0.45
FUEL_PRICE = 1.40  # game dollars per litre


@dataclass(frozen=True)
class BoatModel:
    id: str
    name: str
    bow: float
    stern: float
    half_beam: float
    draft: float
    eye_height: float
    price: float
    tank: float
    fuel_burn: float  # litres per game hour at full throttle, before upgrades
    speed_factor: float
    turn_factor: float
    acceleration: float
    well_bonus: float = 0.0
    sail_speed: float = 0.0

    @property
    def length(self):
        return self.bow - self.stern


BOATS = {
    "jon": BoatModel("jon", "12 ft Jon boat", HULL_BOW, HULL_STERN, HULL_HALF_BEAM,
                     0.47, 1.22, 0, 12, 1.8, 1.0, 1.0, 1.3),
    "sail": BoatModel("sail", "12 ft Daysailer", 2.63, -1.03, 0.86,
                      0.72, 1.30, 650, 6, 0.45, 0.57, 0.72, 0.65, sail_speed=4.6),
    "pontoon": BoatModel("pontoon", "15 ft Pontoon", 3.37, -1.20, 1.20,
                         0.44, 1.65, 1450, 36, 2.6, 0.83, 0.52, 0.72, well_bonus=40),
}

# Perimeter and interior samples, including every corner. Narrow solid props
# are checked geometrically as well, rather than relying on these samples.
_LOCAL = {
    model.id: np.array([(s,a) for a in np.linspace(model.stern-HULL_CLEARANCE,model.bow+HULL_CLEARANCE,8)
                       for s in (-model.half_beam-HULL_CLEARANCE,0,model.half_beam+HULL_CLEARANCE)],np.float64)
    for model in BOATS.values()
}


def axes(yaw):
    return np.array([math.sin(yaw),math.cos(yaw)]),np.array([math.cos(yaw),-math.sin(yaw)])


def hull_samples(x,z,yaw,boat_id="jon"):
    forward,right = axes(yaw)
    local = _LOCAL[boat_id]
    return np.array([x,z])+local[:,0:1]*right+local[:,1:2]*forward


def hits_rectangles(x,z,yaw,slip,rectangles,boat_id="jon"):
    """SAT between the entire hull and fixed rectangles in the dock's axes."""
    forward,right = axes(yaw)
    model = BOATS[boat_id]
    centre = np.array([x,z])+forward*(model.bow+model.stern)*0.5
    a,s = slip.local(*centre)
    centre = np.array([float(a),float(s)])
    f = np.array([forward@[slip.ix,slip.iz],forward@[slip.sx,slip.sz]])
    r = np.array([right@[slip.ix,slip.iz],right@[slip.sx,slip.sz]])
    half_l,half_w = model.length*0.5+HULL_CLEARANCE,model.half_beam+HULL_CLEARANCE
    delta = centre-rectangles[:,:2]
    extents = rectangles[:,2:]
    separate_a = abs(delta[:,0])>half_l*abs(f[0])+half_w*abs(r[0])+extents[:,0]
    separate_s = abs(delta[:,1])>half_l*abs(f[1])+half_w*abs(r[1])+extents[:,1]
    separate_f = abs(delta@f)>half_l+extents@abs(f)
    separate_r = abs(delta@r)>half_w+extents@abs(r)
    return bool(np.any(~(separate_a|separate_s|separate_f|separate_r)))


def hits_round_props(x,z,yaw,props,boat_id="jon"):
    model = BOATS[boat_id]
    forward,right = axes(yaw)
    delta = props[:,:2]-np.array([x,z])
    a = delta@forward
    s = delta@right
    da = np.maximum(np.maximum(model.stern-a,a-model.bow),0)
    ds = np.maximum(abs(s)-model.half_beam,0)
    return bool(np.any(da*da+ds*ds<(props[:,2]+HULL_CLEARANCE)**2))


def sailing_speed(yaw, wind_to, wind_speed, maximum=4.6):
    """A simple sailing polar: fastest on a reach, no thrust close to upwind."""
    angle = abs(math.atan2(math.sin(yaw-wind_to),math.cos(yaw-wind_to)))
    efficiency = float(np.interp(angle,[0,math.pi/4,math.pi/2,2*math.pi/3,3*math.pi/4,math.pi],
                                 [0.68,0.88,1.0,0.60,0.0,0.0]))
    return min(maximum,wind_speed*0.72*efficiency)
