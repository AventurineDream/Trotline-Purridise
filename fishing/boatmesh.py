"""Small, detailed first-person daysailer and pontoon meshes, and the jon's outboard."""

import math
from dataclasses import replace

import numpy as np

from .data import paint_rgb
from .world import Face
from .weather import wind_at

HULL_GLOW = 0.55  # night-emission strength of a `glow` hull


def glow_hull(state, faces):
    """A `glow` boat is lit at night. Faces that set their own emission keep it."""
    if "glow" not in state.boat.traits:
        return faces
    return [face if face.emissive is not None else replace(face, emissive=HULL_GLOW) for face in faces]


# The jon's tiller outboard, eye frame, metres. The clamp bracket straddles the transom
# plane at HULL_STERN (-0.80); the steering axis sits 4 cm astern of it. The cowl rides
# above the rail; the propeller is submerged below the 1.22 m eye-height waterline and the
# skeg stays inside the jon's 0.47 m draft, so it never reaches below what navigation allows.
OUTBOARD_PIVOT = (0.0, -0.84)  # (x, z) of the clamp's steering axis
OUTBOARD_YAW = 0.45  # radians of motor yaw at full steer
_PROP = (-1.45, -0.34, 0.11)  # hub y, hub local z, blade radius
# (name, local centre, half size, paint): local -z is astern of the pivot. Stacked parts sink
# into the part above rather than meeting face to face, so no two skins share a plane.
_OUTBOARD_PARTS = (
    ("clamp", (0.0, -0.433, 0.02), (0.10, 0.03, 0.05), "steel"),  # 2-3 mm clear of rail and cowl
    ("cowl", (0.0, -0.24, -0.24), (0.17, 0.16, 0.22), "cowl"),
    ("pan", (0.0, -0.44, -0.225), (0.15, 0.05, 0.19), "leg"),
    ("midsection", (0.0, -0.905, -0.12), (0.055, 0.435, 0.08), "leg"),
    ("plate", (0.0, -1.35, -0.16), (0.13, 0.012, 0.15), "leg"),
    ("gearcase", (0.0, -1.45, -0.16), (0.05, 0.07, 0.16), "leg"),
    ("skeg", (0.0, -1.59, -0.20), (0.012, 0.09, 0.08), "leg"),
    ("hub", (0.0, -1.45, -0.34), (0.035, 0.035, 0.03), "steel"),
)


def _outboard_frame(steer):
    """`place(lx, y, lz)` and `turn(nx, ny, nz)` for the outboard yawed by `steer` about its clamp."""
    yaw = float(steer) * OUTBOARD_YAW
    c, s = math.cos(yaw), math.sin(yaw)
    px, pz = OUTBOARD_PIVOT

    def place(lx, y, lz):
        # Rotating by +yaw carries an aft (-z) point toward +x.
        return (px + lx * c - lz * s, y, pz + lx * s + lz * c)

    def turn(nx, ny, nz):
        return (nx * c - nz * s, ny, nx * s + nz * c)

    return place, turn, (c, s)


def outboard_faces(steer, cowl_rgb):
    """The jon's outboard as camera-space faces, yawed about its clamp by `steer`.

    The GL path tags these like the rest of the boat's hardware, so close up they share
    the hull's sheet-seam detail; at this size that reads as metalwork and is accepted.

    Args:
        steer: The boat's steer, -1..1. Positive turns to starboard, so the lower unit's
            aft end swings to starboard (+x), as a real tiller motor does.
        cowl_rgb: The `motor` paint, 0-1 RGB, for the cowl.

    Returns:
        A list of `Face`s: clamp bracket, cowl and pan, midsection, cavitation plate,
        gearcase, skeg and a three-blade propeller. Each box has outward normals.
    """
    place, turn, _cs = _outboard_frame(steer)
    paints = {"cowl": np.asarray(cowl_rgb, np.float32),
              "leg": np.array([0.20, 0.21, 0.22], np.float32),
              "steel": np.array([0.55, 0.58, 0.60], np.float32)}
    faces = []

    def quad(points, normal, colour):
        faces.append(Face(np.array([place(*p) for p in points], np.float32),
                          np.array(turn(*normal), np.float32), np.asarray(colour, np.float32), "cam"))

    for _name, (x, y, z), (a, b, d), paint in _OUTBOARD_PARTS:
        colour = paints[paint]
        quad([(x-a,y+b,z-d),(x+a,y+b,z-d),(x+a,y+b,z+d),(x-a,y+b,z+d)], (0,1,0), colour)
        quad([(x-a,y-b,z+d),(x+a,y-b,z+d),(x+a,y-b,z-d),(x-a,y-b,z-d)], (0,-1,0), colour * 0.7)
        quad([(x-a,y-b,z+d),(x-a,y+b,z+d),(x+a,y+b,z+d),(x+a,y-b,z+d)], (0,0,1), colour * 0.9)
        quad([(x+a,y-b,z-d),(x+a,y+b,z-d),(x-a,y+b,z-d),(x-a,y-b,z-d)], (0,0,-1), colour * 0.85)
        quad([(x-a,y-b,z-d),(x-a,y+b,z-d),(x-a,y+b,z+d),(x-a,y-b,z+d)], (-1,0,0), colour * 0.8)
        quad([(x+a,y-b,z+d),(x+a,y+b,z+d),(x+a,y+b,z-d),(x+a,y-b,z-d)], (1,0,0), colour * 0.8)
    # Three blades round the hub. Each blade is two one-sided quads, the forward one 4 mm
    # ahead so the GL pass, which draws both, never depth-fights them.
    hub_y, hub_z, radius = _PROP
    for k in range(3):
        angle = k * math.tau / 3 + 0.3
        tip_x, tip_y = math.cos(angle) * radius, hub_y + math.sin(angle) * radius
        side_x, side_y = -math.sin(angle) * 0.035, math.cos(angle) * 0.035
        blade = [(-side_x, hub_y - side_y), (side_x, hub_y + side_y),
                 (tip_x + side_x, tip_y + side_y), (tip_x - side_x, tip_y - side_y)]
        quad([(bx, by, hub_z) for bx, by in blade], (0, 0, -1), paints["steel"])
        quad([(bx, by, hub_z + 0.004) for bx, by in blade[::-1]], (0, 0, 1), paints["steel"] * 0.8)
    return faces


def outboard_boxes(steer):
    """Boat-space occluder boxes for the outboard's cowl and midsection at `steer`.

    Uses the same yaw as `outboard_faces`. Each box is the axis-aligned bound of the
    yawed part, because the lighting shader's boxes cannot rotate.

    Returns:
        [(centre, half size)] as float32 (3,) arrays, eye frame, metres.
    """
    place, _turn, (c, s) = _outboard_frame(steer)
    boxes = []
    for name, centre, (a, b, d), _paint in _OUTBOARD_PARTS:
        if name in ("cowl", "midsection"):
            half = (abs(a * c) + abs(d * s), b, abs(a * s) + abs(d * c))
            boxes.append((np.asarray(place(*centre), np.float32), np.asarray(half, np.float32)))
    return boxes


def boat_faces(state):
    faces = []
    hull = np.asarray(paint_rgb("hull",state.look_paint["hull"]),np.float32)
    if state.look_paint["hull"]=="aluminum":
        hull = np.array([0.87,0.89,0.86],np.float32)
    deck = np.asarray(paint_rgb("deck",state.look_paint["deck"]),np.float32)
    if state.look_paint["deck"]=="aluminum":
        deck = np.array([0.67,0.65,0.57],np.float32)
    metal = (0.65,0.70,0.73)
    teak = np.array([0.55,0.39,0.23],np.float32)
    blue = (0.14,0.29,0.38)
    motor = np.asarray(paint_rgb("motor",state.look_paint["motor"]),np.float32)

    def quad(points,color,normal=None):
        points = np.asarray(points,np.float32)
        if len(points)==3:
            points = np.vstack([points,points[-1]])
        n = np.cross(points[1]-points[0],points[2]-points[0]) if normal is None else np.array(normal,np.float32)
        n /= np.linalg.norm(n)+1e-8
        faces.append(Face(points,n,np.asarray(color,np.float32),"cam"))

    def box(c,size,color):
        x,y,z = c
        a,b,d = np.asarray(size)*0.5
        quad([(x-a,y+b,z-d),(x+a,y+b,z-d),(x+a,y+b,z+d),(x-a,y+b,z+d)],color,(0,1,0))
        quad([(x-a,y-b,z-d),(x-a,y-b,z+d),(x+a,y-b,z+d),(x+a,y-b,z-d)],color,(0,-1,0))
        quad([(x-a,y-b,z-d),(x+a,y-b,z-d),(x+a,y+b,z-d),(x-a,y+b,z-d)],color,(0,0,-1))
        quad([(x-a,y-b,z+d),(x-a,y+b,z+d),(x+a,y+b,z+d),(x+a,y-b,z+d)],color,(0,0,1))
        quad([(x-a,y-b,z-d),(x-a,y+b,z-d),(x-a,y+b,z+d),(x-a,y-b,z+d)],color,(-1,0,0))
        quad([(x+a,y-b,z-d),(x+a,y-b,z+d),(x+a,y+b,z+d),(x+a,y+b,z-d)],color,(1,0,0))

    def tube(a,b,r,color,sides=8):
        a,b = np.asarray(a,np.float32),np.asarray(b,np.float32)
        direction = b-a
        direction /= np.linalg.norm(direction)+1e-8
        reference = np.array([0,1,0] if abs(direction[1])<0.9 else [1,0,0],np.float32)
        u = np.cross(direction,reference)
        u /= np.linalg.norm(u)+1e-8
        v = np.cross(direction,u)
        for i in range(sides):
            t,s = i*math.tau/sides,(i+1)*math.tau/sides
            n,m = math.cos(t)*u+math.sin(t)*v,math.cos(s)*u+math.sin(s)*v
            quad([a+n*r,b+n*r,b+m*r,a+m*r],color,n+m)

    model = state.boat
    if not model.handcrafted:
        from .boatfamilies import family_faces
        return family_faces(state)
    if state.boat_id=="rowboat":
        beam,bow,stern = model.half_beam,model.bow,model.stern
        # Blue molded shell, cream liner, shallow floor and a blunt transom.
        shell = (np.array([0.08,0.29,0.67],np.float32)
                if state.look_paint.get("hull", "aluminum")=="aluminum"
                else np.asarray(paint_rgb("hull",state.look_paint["hull"]),np.float32))
        cream = (0.84,0.81,0.68)
        dark_blue = tuple(np.asarray(shell)*0.66)
        stations = [(-1.34,0.44),(-1.10,0.57),(-0.58,0.65),
                    (0.48,0.65),(1.08,0.52),(1.62,0.045)]
        for side in (-1,1):
            for (z0,w0),(z1,w1) in zip(stations,stations[1:]):
                inner0,inner1 = w0*0.62,w1*0.62
                # The lower chine tapers in to keep the 10-foot hull shallow.
                lower0,lower1 = max(0.12,w0*0.66),max(0.08,w1*0.66)
                quad([(side*w0,-0.44,z0),(side*w1,-0.44,z1),
                      (side*lower1,-1.53,z1),(side*lower0,-1.53,z0)],
                     shell,(-side,0.08,0))
                quad([(side*inner0,-0.48,z0),(side*inner1,-0.48,z1),
                      (side*w1,-0.44,z1),(side*w0,-0.44,z0)],cream,(0,1,0))
            # Continuous molded blue gunwale and thin dark rub strip.
            for (z0,w0),(z1,w1) in zip(stations,stations[1:]):
                tube((side*w0,-0.405,z0),(side*w1,-0.405,z1),0.035,shell,8)
                tube((side*(w0+0.012),-0.49,z0),(side*(w1+0.012),-0.49,z1),
                     0.012,dark_blue,6)
        quad([(-0.29,-1.53,-1.24),(0.29,-1.53,-1.24),
              (0.31,-1.53,0.80),(-0.31,-1.53,0.80)],shell,(0,-1,0))
        # Cream floor and molded footwells.
        quad([(-0.40,-0.88,-1.12),(0.40,-0.88,-1.12),
              (0.44,-0.88,0.87),(-0.44,-0.88,0.87)],cream,(0,1,0))
        for x in (-0.29,0.29):
            box((x,-0.975,-0.47),(0.055,0.025,0.94),(0.77,0.75,0.61))
        # Two molded benches leave the center seat as a separate backless stool.
        box((0,-0.45,1.12),(1.04,0.18,0.30),cream)
        box((0,-0.79,-1.02),(0.94,0.17,0.32),cream)
        for x in (-0.33,0.33):
            box((x,-0.69,-1.02),(0.25,0.055,0.24),(0.91,0.87,0.73))
        # A plain plastic stool: flat seat and four short legs, with no back.
        stool = (0.96,0.93,0.82)
        box((0,-0.265,0.74),(0.34,0.13,0.36),stool)
        for x in (-0.11,0.11):
            for z in (0.63,0.85):
                tube((x,-0.33,z),(x*1.12,-0.82,z*1.10),0.022,stool,6)
        # Oarlocks and oars remain fitted even if the optional motor is installed.
        for side in (-1,1):
            tube((side*0.55,-0.29,0.96),(side*0.66,-0.29,0.96),0.045,metal,8)
            tube((side*0.59,-0.26,0.96),(side*0.59,-0.39,0.96),0.025,metal,8)
            tube((side*0.59,-0.33,0.96),(side*1.42,-0.46,0.74),0.026,teak,8)
            blade_x = side*1.42
            quad([(blade_x-0.11,-0.38,0.60),(blade_x+0.11,-0.38,0.60),
                  (blade_x+0.12,-0.50,0.88),(blade_x-0.12,-0.50,0.88)],
                 (0.62,0.43,0.25),(0,1,0))
        # Transom motor pad is part of the boat; the electric unit is optional.
        box((0,-0.49,stern-0.02),(0.66,0.16,0.12),dark_blue)
        if state.rowboat_trolling_motor:
            electric = (0.12,0.15,0.17)
            box((0,-0.65,stern-0.11),(0.36,0.32,0.30),electric)
            tube((0,-0.76,stern-0.12),(0,-1.47,stern-0.16),0.035,electric,10)
            tube((0,-1.45,stern-0.16),(-0.11,-1.49,stern-0.16),0.018,metal,8)
            tube((0,-1.45,stern-0.16),(0.11,-1.49,stern-0.16),0.018,metal,8)
            tube((0.12,-0.60,stern-0.08),(0.43,-0.50,stern+0.12),0.018,electric,8)
            # A short tiller grip sits within reach from the center stool.
            tube((0.50,-0.31,0.43),(0.50,-0.27,0.88),0.018,electric,8)
            box((0.50,-0.24,0.89),(0.09,0.06,0.16),electric)
            box((0.04,-0.57,stern-0.11),(0.045,0.045,0.045),(0.21,0.72,0.58))
    elif state.boat_id=="sail":
        beam,bow,stern = model.half_beam,model.bow,model.stern
        rim = [(-beam,stern),(-beam,1.25),(-0.56,2.05),(0,bow),(0.56,2.05),(beam,1.25),(beam,stern)]
        quad([(-0.76,-1.00,stern),(0.76,-1.00,stern),(0.76,-1.00,1.12),(-0.76,-1.00,1.12)],deck,(0,1,0))
        for (x,z),(xx,zz) in zip(rim,rim[1:]):
            normal = (zz-z,0,x-xx)
            quad([(x,-1.76,z),(xx,-1.76,zz),(xx,-0.48,zz),(x,-0.48,z)],hull,normal)
            quad([(x,-1.00,z),(x,-0.48,z),(xx,-0.48,zz),(xx,-1.00,zz)],hull*0.86,tuple(-n for n in normal))
            tube((x,-0.43,z),(xx,-0.43,zz),0.025,metal)
        quad([(-0.76,-0.48,1.12),(0.76,-0.48,1.12),(0,-0.48,bow)],hull,(0,1,0))
        box((0,-0.75,1.0),(1.47,0.12,0.30),teak)
        for side in (-1,1):
            box((side*0.68,-0.73,0.22),(0.20,0.13,1.40),teak)
        box((0,-0.84,0.58),(0.15,0.30,0.86),hull)
        box((0,-0.46,1.82),(0.40,0.06,0.44),blue)
        box((0,-0.422,1.82),(0.30,0.008,0.32),(0.20,0.31,0.34))
        # Mast, shrouds, boom, and a mainsail with visible panel seams.
        mast = (0,-0.42,1.13)
        top = (0,4.05,1.13)
        tube(mast,top,0.032,metal,12)
        for side in (-1,1):
            tube((side*0.76,-0.42,0.85),top,0.005,(0.56,0.60,0.60))
        tube((0,-0.43,bow-.05),top,0.005,metal)
        boom_angle = 0.0
        if state.sail_raised:
            wind,_ = wind_at(state.game_minutes+state.minute_acc)
            relative = math.atan2(math.sin(wind-state.yaw),math.cos(wind-state.yaw))
            boom_angle = -math.copysign(min(1.08,0.25+abs(relative)*0.50),relative)
        clew = (math.sin(boom_angle)*1.85,-0.14,1.13-math.cos(boom_angle)*1.85)
        tack = (0,-0.14,1.13)
        tube(tack,clew,0.022,metal)
        cloth = np.array([0.94,0.92,0.82],np.float32)
        if state.sail_raised:
            # Double faces make the sail visible from either tack and in CPU QA.
            quad([tack,clew,top],cloth)
            quad([top,clew,tack],cloth)
            for t in (0.25,0.50,0.75):
                a = np.asarray(top)*(1-t)+np.asarray(tack)*t
                b = np.asarray(top)*(1-t)+np.asarray(clew)*t
                tube(a,b,0.006,(0.70,0.74,0.71),4)
            tube(clew,(0,-0.80,0.18),0.006,(0.63,0.49,0.30),4)
        else:
            tube(tack,clew,0.068,cloth,10)
        box((-0.38,-0.76,0.46),(0.36,0.38,0.43),(0.73,0.77,0.74))
        box((0.43,-0.71,0.66),(0.28,0.25,0.20),motor)
        tube((0.12,-0.55,0.14),(0.12+state.steer*0.14,-0.54,0.68),0.022,teak)
    else:
        beam,bow,stern = model.half_beam,model.bow,model.stern
        box((0,-1.01,(bow+stern)*0.5),(beam*2,0.18,model.length),deck)
        for i,z in enumerate(np.linspace(stern,bow,27)):
            box((0,-0.909,z),(beam*2-0.08,0.012,0.015),deck*0.76)
        # Twin aluminum pontoons, including tapered noses and end caps.
        for side in (-1,1):
            x = side*0.94
            tube((x,-1.57,stern),(x,-1.57,bow-.26),0.255,metal,16)
            for i in range(16):
                a,b = i*math.tau/16,(i+1)*math.tau/16
                p = (x+math.cos(a)*0.255,-1.57+math.sin(a)*0.255,bow-.26)
                q = (x+math.cos(b)*0.255,-1.57+math.sin(b)*0.255,bow-.26)
                quad([p,q,(x,-1.57,bow)],metal)
            for z in (stern+.35,1.0,bow-.6):
                tube((x-.23,-1.57,z),(x+.23,-1.57,z),0.015,(0.42,0.47,0.49))
            # Solid fence panels below tubular safety rails.
            box((side*(beam-.045),-0.58,(bow+stern)*0.5),(0.055,0.62,model.length-.10),hull)
            tube((side*beam,-0.20,stern),(side*beam,-0.20,bow),0.025,metal)
            for z in np.linspace(stern,bow,8):
                tube((side*beam,-0.88,z),(side*beam,-0.18,z),0.025,metal)
            for a,b in ((-beam,-0.43),(0.43,beam)):
                tube((a,-0.20,bow),(b,-0.20,bow),0.025,metal)
            box((side*0.84,-0.72,2.40),(0.42,0.36,1.10),blue)
            box((side*0.86,-0.45,2.40),(0.39,0.15,1.08),(0.87,0.84,0.72))
            box((side*1.04,-0.22,2.40),(0.15,0.40,1.08),(0.86,0.84,0.73))
        # Steering console, wood fascia, gauges, and an actual wheel rim.
        box((0.22,-0.59,1.27),(0.58,0.63,0.56),hull)
        box((0.22,-0.25,1.02),(0.57,0.18,0.075),teak)
        box((0.22,-0.18,1.33),(0.48,0.07,0.44),(0.14,0.22,0.25))
        for x in (0.08,0.28):
            box((x,-0.24,0.976),(0.10,0.10,0.012),(0.08,0.14,0.17))
            tube((x,-0.245,0.965),(x+.02,-0.22,0.965),0.005,(0.84,0.76,0.46),4)
        centre = (0.22,-0.40,0.91)
        for i in range(24):
            a,b = i*math.tau/24,(i+1)*math.tau/24
            tube((centre[0]+math.cos(a)*.13,centre[1]+math.sin(a)*.13,centre[2]),
                 (centre[0]+math.cos(b)*.13,centre[1]+math.sin(b)*.13,centre[2]),.012,(0.13,0.16,0.16),4)
        for angle in (0,math.tau/3,2*math.tau/3):
            angle += state.steer*0.7
            tube(centre,(centre[0]+math.cos(angle)*.12,centre[1]+math.sin(angle)*.12,centre[2]),.007,metal,4)
        box((-0.65,-0.62,0.86),(0.46,0.55,0.70),(0.75,0.79,0.74))
        # Navy bimini canopy and stainless uprights frame the upper view.
        for x in (-1.0,1.0):
            for z in (-0.72,1.45):
                tube((x,-0.85,z),(x,1.14,z),0.023,metal)
        box((0,1.18,0.35),(2.18,0.065,2.36),blue)
        for z in (-0.82,0.35,1.53):
            tube((-1.06,1.15,z),(1.06,1.15,z),0.023,metal)
        box((0,-1.07,stern-.10),(0.48,0.60,0.32),motor)
    if state.light:
        y = -0.36 if state.boat_id=="sail" else -0.16
        box((0,y,model.bow-.15),(0.17,0.13,0.16),(0.16,0.19,0.19))
    return faces
