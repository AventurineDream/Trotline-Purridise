"""Boat models, handling, and shared full-hull collision geometry, in metres."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from .data import BOAT_DATA, WELLS

# Paddled, rowed and starlight boats carry no fuel (03 §6 "Power").
UNFUELLED_POWER = frozenset({"paddle", "oars", "starlight"})
# Existing livewell upgrades (+40/+100 lb) apply to tiers 2-7 only.
WELL_UPGRADE_TIERS = range(2, 8)
HANDCRAFTED_BOATS = frozenset({"jon", "rowboat", "sail", "pontoon"})
# How quickly each power sheds speed when easing off, per second. Paddles stop
# short, inboards carry way, and starlight barges glide. Tiller, oars and sail
# keep the original 0.65, so the four older boats handle exactly as before.
COAST_RATE = {"paddle": 1.1, "oars": 0.65, "tiller": 0.65, "console": 0.75,
              "inboard": 0.5, "sail": 0.65, "starlight": 0.22}

HULL_BOW = 2.86
HULL_STERN = -0.80
HULL_HALF_BEAM = 0.70
HULL_INNER_BEAM = 0.64
HULL_CLEARANCE = 0.04
# The jon's outboard hangs astern of its hull. These bound boatmesh.outboard_faces at every
# steer (test_jon_outboard checks it), in the eye frame, metres.
JON_OUTBOARD_AFT = -1.34
JON_OUTBOARD_HALF_WIDTH = 0.36
THROTTLE_RATE = 0.50
REVERSE_LIMIT = -0.45
FUEL_PRICE = 1.40  # game dollars per litre
ROWBOAT_ROW_SPEED = 1.55  # m/s under oars
ROWBOAT_ELECTRIC_SPEED = 4.25  # m/s, 9.9 hp-equivalent trolling motor
ROWBOAT_MOTOR_POWER_KW = 7.4
ROWBOAT_BATTERY_KWH = 18.0
ROWBOAT_MOTOR_PRICE = 350.0
ELECTRICITY_PRICE = 0.35  # game dollars per kWh at the landing
BATTERY_CHARGE_KWH = 5.0  # maximum per landing visit


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
    lines: int
    tank: float
    fuel_burn: float  # litres per game hour at full throttle, before upgrades
    speed_factor: float
    turn_factor: float
    acceleration: float
    well_bonus: float = 0.0
    sail_speed: float = 0.0
    traits: tuple[str, ...] = ()
    tier: int = 3
    family: str = "jon"
    power: str = "tiller"
    top_speed: float = 0.0  # m/s for powers without motor upgrades
    blurb: str = ""
    sold_at: tuple[str, ...] = ()  # lake ids; empty means every landing

    @property
    def length(self):
        return self.bow - self.stern

    @property
    def handcrafted(self) -> bool:
        """The four original boats keep their hand-built meshes; the rest are generated."""
        return self.id in HANDCRAFTED_BOATS

    @property
    def fuelled(self) -> bool:
        return self.power not in UNFUELLED_POWER

    def well_cap(self, well_tier: int) -> float:
        upgraded = WELLS[well_tier] if self.tier in WELL_UPGRADE_TIERS else WELLS[0]
        return upgraded + self.well_bonus


BOATS = {
    row["id"]: BoatModel(**{**row, "traits": tuple(row["traits"]),
                            "sold_at": tuple(row.get("sold_at", ()))})
    for row in BOAT_DATA
}


def footprint(model):
    """The boat's plan-view parts as (aft z, fore z, half width) boxes in the eye frame, metres.

    Every boat has its hull box. The jon adds a narrow box for the outboard astern of its
    transom, so docks, posts and shallows stop the motor as well as the hull.
    """
    parts = [(model.stern, model.bow, model.half_beam)]
    if model.id == "jon":
        parts.append((JON_OUTBOARD_AFT, model.stern, JON_OUTBOARD_HALF_WIDTH))
    return parts


def wake_along(along, speed, model):
    """Where a point lies along the hull's travel, for the wake art, metres ahead of the eye.

    The wake terms in software.py and water.frag are authored for forward travel. Reversing,
    the stern leads, so `along` mirrors about the hull's middle: the wake trails the bow and
    the bow wave forms at the stern. Every wake term fades with |speed|, so the flip at
    zero speed cannot be seen. water.frag mirrors the same way from its boat_ends uniform.

    Args:
        along: distance ahead of the eye along the heading, metres (scalar or array).
        speed: signed boat speed, m/s; negative is reversing.
        model: the BoatModel whose `stern` and `bow` bound the hull.

    Returns:
        `along` unchanged going forward, else `stern + bow - along`, in the same shape.
    """
    return model.stern + model.bow - along if speed < 0 else along


# Perimeter and interior samples of every footprint part, including every corner. Narrow
# solid props are checked geometrically as well, rather than relying on these samples.
_LOCAL = {
    model.id: np.array([(s,a) for aft,fore,half in footprint(model)
                        for a in np.linspace(aft-HULL_CLEARANCE,fore+HULL_CLEARANCE,8 if fore-aft>1.0 else 2)
                        for s in (-half-HULL_CLEARANCE,0,half+HULL_CLEARANCE)],np.float64)
    for model in BOATS.values()
}


def axes(yaw):
    return np.array([math.sin(yaw),math.cos(yaw)]),np.array([math.cos(yaw),-math.sin(yaw)])


def hull_samples(x,z,yaw,boat_id="jon"):
    forward,right = axes(yaw)
    local = _LOCAL[boat_id]
    return np.array([x,z])+local[:,0:1]*right+local[:,1:2]*forward


def hits_rectangles(x,z,yaw,slip,rectangles,boat_id="jon"):
    """SAT between each footprint part and fixed rectangles in the dock's axes."""
    forward,right = axes(yaw)
    f = np.array([forward@[slip.ix,slip.iz],forward@[slip.sx,slip.sz]])
    r = np.array([right@[slip.ix,slip.iz],right@[slip.sx,slip.sz]])
    extents = rectangles[:,2:]
    for aft,fore,half in footprint(BOATS[boat_id]):
        a,s = slip.local(*(np.array([x,z])+forward*(fore+aft)*0.5))
        delta = np.array([float(a),float(s)])-rectangles[:,:2]
        half_l,half_w = (fore-aft)*0.5+HULL_CLEARANCE,half+HULL_CLEARANCE
        separate_a = abs(delta[:,0])>half_l*abs(f[0])+half_w*abs(r[0])+extents[:,0]
        separate_s = abs(delta[:,1])>half_l*abs(f[1])+half_w*abs(r[1])+extents[:,1]
        separate_f = abs(delta@f)>half_l+extents@abs(f)
        separate_r = abs(delta@r)>half_w+extents@abs(r)
        if np.any(~(separate_a|separate_s|separate_f|separate_r)):
            return True
    return False


def hits_round_props(x,z,yaw,props,boat_id="jon"):
    forward,right = axes(yaw)
    delta = props[:,:2]-np.array([x,z])
    a = delta@forward
    s = delta@right
    for aft,fore,half in footprint(BOATS[boat_id]):
        da = np.maximum(np.maximum(aft-a,a-fore),0)
        ds = np.maximum(abs(s)-half,0)
        if np.any(da*da+ds*ds<(props[:,2]+HULL_CLEARANCE)**2):
            return True
    return False


def sailing_speed(yaw, wind_to, wind_speed, maximum=4.6):
    """A simple sailing polar: fastest on a reach, no thrust close to upwind."""
    angle = abs(math.atan2(math.sin(yaw-wind_to),math.cos(yaw-wind_to)))
    efficiency = float(np.interp(angle,[0,math.pi/4,math.pi/2,2*math.pi/3,3*math.pi/4,math.pi],
                                 [0.68,0.88,1.0,0.60,0.0,0.0]))
    return min(maximum,wind_speed*0.72*efficiency)
