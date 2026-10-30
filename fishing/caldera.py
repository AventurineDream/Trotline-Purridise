"""Crater's bounded scenery and clear-night reflection hook.

The hook is visual and read-only. Future chapter four can observe this condition
without this environment advancing the story or opening a travel route.
"""

from __future__ import annotations

import math
import numpy as np


def reflection_strength(state, light):
    if state.lake_id == 'nebula':
        from .finale import settle_still
        return settle_still(state)  # Settle In's first cue: the stars stop rippling (V1-35)
    if state.lake_id != 'crater':
        return 0.0
    return float(np.clip(light['night']*(1-light['cloud_shade'])*(1-light['rain'])*
                         (1-light.get('mist',0)),0,1))


def caldera_props(world, prop_type):
    parameters=world.environment
    rng=np.random.default_rng(parameters['seed'])
    result=[]
    for index in range(parameters['tree_count']*3):
        angle=float(rng.uniform(0,math.tau))
        radius=float(world.fields.radius(angle))+float(rng.uniform(7,135))
        x,z=math.cos(angle)*radius,math.sin(angle)*radius
        a,s=world.slip.local(x,z)
        if -65<float(a)<80 and abs(float(s))<85:
            continue
        kind='hemlock' if index%3 else 'whitebark'
        result.append(prop_type(kind,x,z,float(rng.uniform(13,23)),float(rng.uniform(.82,1.03))))
        if len(result)==parameters['tree_count']:
            break
    _,snag_x,snag_z,_radius=next(row for row in world.zones if row[0]=="cypress")
    for i in range(12):
        x,z=snag_x+40+(i%3)*9,snag_z-62+(i//3)*27
        if float(world.shore_sd(x,z)) < -3:
            result.append(prop_type('deadpine',x,z,6+(i%4)*.65,.88))
    # Pale pumice fragments and dark boulders stay on dry margins.
    for angle in np.linspace(4.25,5.2,16):
        radius=float(world.fields.radius(angle))+3
        result.append(prop_type('rock',math.cos(angle)*radius,math.sin(angle)*radius,.6,.95))
    return result


def survey_faces(world):
    from .world import _box
    sl=world.slip
    x,z=sl.world(22,10)
    along,up,side=(sl.ix,0,sl.iz),(0,1,0),(sl.sx,0,sl.sz)
    y=float(world.sample_height(x,z))
    faces=_box((x,y+1.15,z),along,up,side,(.18,2.3,.18),(.26,.28,.31))
    faces+=_box((x,y+2.25,z),along,up,side,(.24,.11,.24),(.75,.61,.31))
    # Brass survey plaque and six engraved calibration marks face the water.
    px,pz=sl.world(21.85,10)
    faces+=_box((px,y+1.45,pz),along,up,side,(.06,.68,1.08),(.59,.51,.30))
    for i in range(6):
        px,pz=sl.world(21.81,9.62+i*.15)
        faces+=_box((px,y+1.45,pz),along,up,side,(.012,.34 if i%2 else .48,.018),(.18,.20,.22))
    return faces


def thermal_faces(state, world):
    from .world import _face
    t=0 if state.v2.get('settings',{}).get('reduced_motion',False) else float(state.anim)
    out=[]
    # Two authored vents, three crossed wisps and one eight-segment bubble each.
    # Everything is derived from the clock, never retained as particle history.
    for vent,(x,z) in enumerate(world.environment['thermal']):
        for i in range(3):
            age=(t*.16+i/3+vent*.21)%1
            radius=.45+age*.9
            cx,cy,cz=x+math.sin(i+t*.12)*.6, .9+age*4,z+age*.8
            color=(.65+age*.13,.68+age*.13,.72+age*.13)
            out.append(_face([(cx-radius,cy-radius,cz),(cx+radius,cy-radius,cz),
                              (cx+radius,cy+radius,cz),(cx-radius,cy+radius,cz)],(0,0,1),color))
            out.append(_face([(cx,cy-radius,cz-radius),(cx,cy-radius,cz+radius),
                              (cx,cy+radius,cz+radius),(cx,cy+radius,cz-radius)],(1,0,0),color))
        life=(t*.35+vent*.43)%1
        radius=.2+life*.95
        for j in range(8):
            a,b=j*math.tau/8,(j+1)*math.tau/8
            pts=[(x+math.cos(theta)*r,.035,z+math.sin(theta)*r)
                 for theta,r in ((a,radius),(b,radius),(b,radius+.04),(a,radius+.04))]
            out.append(_face(pts,(0,1,0),(.42,.52,.73)))
    return out


def recover_displaced_lines(state, world):
    """Move ropes buried by the new island into the clear launch approach.

    Keep the deployed object, ID, hooks, catches and unknown metadata intact.
    The geometry check makes this safe to repeat after saving; wet lines stay
    exactly where the player placed them. No fishing RNG or inventory is used.
    """
    from .sim import _point_seg
    sl=world.slip
    fx,fz=-sl.ix,-sl.iz
    yaw=math.atan2(fx,fz)
    moved=0
    offsets=(0, *[sign*n for n in range(12,85,12) for sign in (1,-1)])
    for line in state.lines:
        coordinates=(line.x0,line.z0,line.x1,line.z1)
        if not all(math.isfinite(value) for value in coordinates):
            continue
        length=math.hypot(line.x1-line.x0,line.z1-line.z0)
        fractions=np.linspace(0,1,min(1024,max(8,math.ceil(length)+1)))
        x=line.x0+(line.x1-line.x0)*fractions
        z=line.z0+(line.z1-line.z0)*fractions
        dry=(world.shore_sd(x,z)>=0) & ~sl.contains(x,z)
        if not bool(np.any(dry)):
            continue
        replacement=None
        for a in (-85,-135,-185,-235):
            for side in offsets:
                x0,z0=sl.world(a,side)
                x1,z1=x0+fx*length,z0+fz*length
                samples=[(x0+(x1-x0)*t,z0+(z1-z0)*t) for t in fractions]
                if not all(world.hull_clear(px,pz,yaw,state.boat_id) for px,pz in samples):
                    continue
                if any(_point_seg(px,pz,other.x0,other.z0,other.x1,other.z1)<8
                       for other in state.lines if other is not line for px,pz in samples):
                    continue
                # Approach along the already clear central launch, then move
                # sideways beyond the marina before running the relocated rope.
                route=(sl.world(-55,0),sl.world(a,0),(x0,z0))
                safe=True
                for start,end in zip(route,route[1:]):
                    heading=math.atan2(end[0]-start[0],end[1]-start[1])
                    steps=max(2,math.ceil(math.dist(start,end)/2)+1)
                    for t in np.linspace(0,1,steps):
                        px,pz=start[0]+(end[0]-start[0])*t,start[1]+(end[1]-start[1])*t
                        if not world.hull_clear(px,pz,heading,state.boat_id):
                            safe=False
                            break
                    if not safe:
                        break
                if safe:
                    replacement=(x0,z0,x1,z1)
                    break
            if replacement is not None:
                break
        if replacement is None:
            continue
        line.x0,line.z0,line.x1,line.z1=replacement
        line.zone=world.zone_at((line.x0+line.x1)/2,(line.z0+line.z1)/2)
        if state.bot_target_line_id==line.line_id:
            state.bot_tx,state.bot_tz=line.point_at(0)
        moved+=1
    if moved:
        noun='line' if moved==1 else 'lines'
        state.toast(f'The changed shoreline moved {moved} {noun} to clear water by the dock.')
    return moved
