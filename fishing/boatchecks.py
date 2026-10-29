"""Behavioral regressions for throttle controls and solid hull collisions."""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

import numpy as np

from .game import Keys,Session
from .sim import State
from .world import shore_sd,shore_xy
from .boat import BOATS,hull_samples


def boat_checks(world):
    with tempfile.TemporaryDirectory(prefix="briar-boat-") as temp:
        state = State.new(world,seed=45)
        state.x=state.z=0.0
        state.anchored=False
        session = Session(world,Path(temp)/"save.json",state,False)
        session.ui.mode="play"
        for _ in range(20):
            session.tick(Keys(held={"w"}),0.05)
        if not math.isclose(state.throttle_setting,0.5,abs_tol=1e-6):
            raise AssertionError("throttle did not rise gradually")
        setting=state.throttle_setting
        speed=state.speed
        for _ in range(20):
            session.tick(Keys(),0.05)
        if state.throttle_setting!=setting or state.speed<=speed:
            raise AssertionError("releasing W did not hold the throttle")
        speed=state.speed
        session.tick(Keys(held={"shift","w"}),0.05)
        if state.throttle_setting!=0 or state.throttle!=0 or not 0<state.speed<speed:
            raise AssertionError("Shift did not idle immediately and allow coasting")
        session.tick(Keys(held={"w"}),0.1)
        session.tick(Keys(held={"rshift"}),0.05)
        if state.throttle_setting!=0 or state.throttle!=0:
            raise AssertionError("right Shift did not idle")
        for _ in range(40):
            session.tick(Keys(held={"s"}),0.05)
        if state.throttle_setting!=-0.45 or state.speed>=0:
            raise AssertionError("reverse throttle did not engage")
        session.tick(Keys(),0.05)
        if state.throttle_setting!=-0.45:
            raise AssertionError("reverse throttle sprang back")
        session.tick(Keys(pressed={"space"}),0.05)
        if not state.anchored or state.throttle_setting!=0 or state.throttle!=0:
            raise AssertionError("dropping the anchor did not idle")
        state.throttle_setting=0.4
        session.save()
        loaded=State.load(session.save_path,world)
        if loaded.throttle_setting!=0 or loaded.throttle!=0:
            raise AssertionError("a saved game resumed under power")

    # Run the biggest motor into the narrow crossbeam with long normal ticks.
    state=State.new(world,seed=41)
    state.x,state.z=world.slip.world(6.0,0.0)
    state.yaw=math.atan2(world.slip.ix,world.slip.iz)
    state.anchored=False
    state.motor=2
    state.speed=state.max_speed()
    state.throttle=state.throttle_setting=1.0
    for _ in range(24):
        state.drive(0.25,0,0,world)
        if not world.hull_clear(state.x,state.z,state.yaw):
            raise AssertionError("hull crossed the dock crossbeam")
    a,_s=world.slip.local(state.x,state.z)
    if float(a)>8.55 or state.traveled>3.0:
        raise AssertionError("blocked travel passed the dock or inflated distance")

    # A clear boat alongside a pier must not rotate a bow corner into it.
    state=State.new(world,seed=42)
    state.x,state.z=world.slip.world(5.0,2.2)
    state.anchored=False
    original_yaw=state.yaw
    for _ in range(160):
        state.drive(0.05,0,1,world)
        if not world.hull_clear(state.x,state.z,state.yaw):
            raise AssertionError("rotation clipped a hull corner through the pier")
    if abs(state.yaw-original_yaw)>0.45:
        raise AssertionError("side-pier barrier did not stop the turn")

    # Approach several differently oriented banks at full speed.
    for angle in (0.0,0.8,1.6,2.2,3.3,4.4,5.5):
        state=State.new(world,seed=43)
        state.yaw=math.atan2(math.cos(angle),math.sin(angle))
        # The north flats can already be too shallow fourteen metres from
        # land. Start from a genuinely clear full-hull pose for every approach.
        for offset in (-14.0,-22.0,-30.0,-45.0):
            state.x,state.z=shore_xy(angle,offset)
            if world.hull_clear(state.x,state.z,state.yaw):
                break
        else:
            raise AssertionError("bank fixture has no clear starting water")
        state.anchored=False
        state.motor=2
        state.speed=state.max_speed()
        state.throttle=state.throttle_setting=1.0
        for _ in range(12):
            state.drive(0.25,0,0,world)
            if not world.hull_clear(state.x,state.z,state.yaw):
                raise AssertionError(f"boat crossed the bank at angle {angle}")
        points=hull_samples(state.x,state.z,state.yaw)
        if shore_sd(points[:,0],points[:,1]).max()>-2.19:
            raise AssertionError("bow or stern passed the shore clearance")

    # A narrow solid knee/post in otherwise open water must stop the hull,
    # including with a much longer simulation tick than the normal game uses.
    original_props=world.solid_props
    try:
        world.solid_props=np.vstack([original_props,[0.0,6.0,0.20]])
        state=State.new(world,seed=44)
        state.x=state.z=state.yaw=0.0
        state.anchored=False
        state.motor=2
        state.speed=state.max_speed()
        state.throttle=state.throttle_setting=1.0
        state.drive(1.0,0,0,world)
        if not world.hull_clear(state.x,state.z,state.yaw) or state.z>3.0:
            raise AssertionError("boat tunneled through a narrow solid prop")
    finally:
        world.solid_props=original_props

    # An old save stopped within a newly solid pier is relocated to water.
    x,z=world.slip.world(7.0,3.0)
    x,z,yaw=world.clear_boat_position(x,z,original_yaw)
    if not world.hull_clear(x,z,yaw):
        raise AssertionError("legacy collision recovery did not find water")
    every_hull_collides(world,original_yaw)
    print("boat ok  held throttle, both Shift keys, reverse, coasting, anchor, "
          f"dock, rotating corners, seven banks, thin obstacles and legacy saves; all {len(BOATS)} hulls")


def every_hull_collides(world,pier_yaw):
    """Each hull meets the bank, post, pier and dock rules with its own footprint."""
    for boat_id,model in BOATS.items():
        def fresh(seed,x,z,yaw):
            state=State.new(world,seed=seed)
            state.boat_id=boat_id
            state.fuel=state.boat.tank
            state.x,state.z,state.yaw=world.clear_boat_position(x,z,yaw,boat_id)
            state.anchored=False
            state.motor=2
            return state
        def full_speed(state):
            state.speed=state.max_speed()
            state.throttle=state.throttle_setting=1.0
        for angle in (0.0,0.8,1.6,2.2,3.3,4.4,5.5):
            yaw=math.atan2(math.cos(angle),math.sin(angle))
            for offset in (-14.0,-22.0,-30.0,-45.0,-60.0):
                x,z=shore_xy(angle,offset)
                if world.hull_clear(x,z,yaw,boat_id):
                    break
            else:
                raise AssertionError(f"{boat_id}: bank fixture has no clear starting water at {angle}")
            state=fresh(43,x,z,yaw)
            full_speed(state)
            for _ in range(12):
                state.drive(0.25,0,0,world)
                if not world.hull_clear(state.x,state.z,state.yaw,boat_id):
                    raise AssertionError(f"{boat_id} crossed the bank at angle {angle}")
        original_props=world.solid_props
        try:
            world.solid_props=np.vstack([original_props,[0.0,6.0+model.bow,0.20]])
            state=fresh(44,0.0,0.0,0.0)
            full_speed(state)
            state.drive(1.0,0,0,world)
            if not world.hull_clear(state.x,state.z,state.yaw,boat_id) or state.z>6.0:
                raise AssertionError(f"{boat_id} tunneled through a narrow solid prop")
        finally:
            world.solid_props=original_props
        state=fresh(42,*world.slip.world(5.0,2.2),pier_yaw)
        for _ in range(80):
            state.drive(0.05,0,1,world)
            if not world.hull_clear(state.x,state.z,state.yaw,boat_id):
                raise AssertionError(f"{boat_id} clipped a hull corner through the pier")
        state=fresh(41,*world.slip.world(6.0,0.0),math.atan2(world.slip.ix,world.slip.iz))
        full_speed(state)
        for _ in range(24):
            state.drive(0.25,0,0,world)
            if not world.hull_clear(state.x,state.z,state.yaw,boat_id):
                raise AssertionError(f"{boat_id} crossed the dock crossbeam")
