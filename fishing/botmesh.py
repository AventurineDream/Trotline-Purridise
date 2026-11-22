"""Five small procedural shells, one shared wool collar, and the scout and idle rigs.

Twelve immutable local-mesh cache entries; no textures, frame histories or lake
references. The same faces feed the OpenGL and software renderers. Idle motion is an
`Idle` pose applied per frame to the cached mesh; the cache itself is never rewritten.
"""
from dataclasses import dataclass
from functools import lru_cache
from typing import NamedTuple
import math
import numpy as np

from .data import BOT_SHELLS
from .world import Face

WOOL = (.72, .20, .28)
DARK = (.10, .14, .17)
LAMP = (1., .66, .18)
MAX_FACES = 1024
# Face part ids: 0 still, 1–3 the scouting joints (propeller or star, legs or wings),
# EYE the lamp and glint the dialogue portrait shutters. No joint moves EYE.
# Idle parts: HEAD turns with the look, ANTENNA and the EAR parts flick, and HEAD_PARTS
# all ride the head. The star's spinning tip (part 1) is added to them by its shell.
EYE = 4
HEAD = 5
ANTENNA = 6
EAR_LEFT = 7
EAR_RIGHT = 8
HEAD_PARTS = (HEAD, EYE, ANTENNA, EAR_LEFT, EAR_RIGHT)
MAX_FLICK = .25  # radians a full flick swings an antenna or ear
SHUT = .92  # how far a fully blinking lamp flattens toward its centre (1 would close it to a line)
YAW_LIMIT = .55  # radians the head may turn either way from its rest facing
PITCH_LIMIT = .30  # radians the head may tip up or down


def rotation(axis, angle):
    axis = np.asarray(axis, np.float32)
    axis = axis / np.linalg.norm(axis)
    x, y, z = axis
    c, s, t = math.cos(angle), math.sin(angle), 1-math.cos(angle)
    return np.array(((t*x*x+c, t*x*y-s*z, t*x*z+s*y),
                     (t*x*y+s*z, t*y*y+c, t*y*z-s*x),
                     (t*x*z-s*y, t*y*z+s*x, t*z*z+c)), np.float32)


@dataclass(frozen=True)
class LocalMesh:
    points: np.ndarray
    normals: np.ndarray
    colors: np.ndarray
    emission: np.ndarray
    parts: np.ndarray
    joints: tuple
    head: tuple  # neck pivot (x,y,z) the head turns about; () when the shell has no head
    head_parts: tuple  # part ids that rotate with the head
    flicks: tuple  # (part, pivot, sign, side) for each antenna or ear

    @property
    def nbytes(self):
        return sum(x.nbytes for x in (self.points, self.normals, self.colors, self.emission, self.parts))


class Builder:
    def __init__(self):
        self.points, self.normals, self.colors, self.emission, self.parts = [], [], [], [], []
        self.part, self.joints = 0, []
        self.head, self.head_parts, self.flicks = (), HEAD_PARTS, []

    def quad(self, points, color, outward=None, glow=0.):
        p = np.asarray(points, np.float32)
        if len(p) == 3:
            p = np.concatenate((p, p[-1:]))
        n = np.cross(p[1]-p[0], p[2]-p[0])
        if np.linalg.norm(n) < 1e-9:
            n = np.cross(p[2]-p[0], p[3]-p[0])
        length = float(np.linalg.norm(n))
        if length < 1e-9:
            return
        n /= length
        if outward is not None and float(n @ np.asarray(outward)) < 0:
            p, n = p[[0, 3, 2, 1]], -n
        self.points.append(p); self.normals.append(n)
        self.colors.append(np.clip(color, 0, 1)); self.emission.append(glow); self.parts.append(self.part)

    def box(self, center, size, color, basis=None, glow=0.):
        center = np.asarray(center, np.float32)
        basis = np.eye(3, dtype=np.float32) if basis is None else basis
        half = np.asarray(size, np.float32) / 2
        for axis in range(3):
            a, b = (axis+1) % 3, (axis+2) % 3
            for side in (-1, 1):
                pts = []
                for u, v in ((-1,-1), (1,-1), (1,1), (-1,1)):
                    p = np.zeros(3, np.float32)
                    p[axis], p[a], p[b] = side*half[axis], u*half[a], v*half[b]
                    pts.append(center+basis @ p)
                self.quad(pts, color, basis[:, axis]*side, glow)

    def ellipsoid(self, center, radii, color, segments=10, rings=6, glow=0.):
        center, radii = np.asarray(center), np.asarray(radii)
        def point(u, v):
            return center + radii * (math.cos(v)*math.cos(u), math.sin(v), math.cos(v)*math.sin(u))
        for j in range(rings):
            a, b = -math.pi/2+j*math.pi/rings, -math.pi/2+(j+1)*math.pi/rings
            for i in range(segments):
                u, v = i*math.tau/segments, (i+1)*math.tau/segments
                pts = np.array((point(u,a), point(v,a), point(v,b), point(u,b)))
                self.quad(pts, color, pts.mean(axis=0)-center, glow)

    def torus(self, center, radii, tube, color, plane='y', segments=16, sides=4, glow=0.):
        center = np.asarray(center)
        def p(u, v):
            a = (radii[0]+tube*math.cos(v))*math.cos(u)
            b = (radii[1]+tube*math.cos(v))*math.sin(u)
            h = tube*math.sin(v)
            return center + (np.array((a,h,b)) if plane == 'y' else np.array((a,b,h)) if plane == 'z' else np.array((h,a,b)))
        for i in range(segments):
            a,b = i*math.tau/segments,(i+1)*math.tau/segments
            for j in range(sides):
                c,d = j*math.tau/sides,(j+1)*math.tau/sides
                pts = np.array((p(a,c),p(b,c),p(b,d),p(a,d)))
                # Tube outward direction, relative to the ring's centreline.
                u,v = (a+b)/2,(c+d)/2
                hint = (math.cos(u)*math.cos(v),math.sin(v),math.sin(u)*math.cos(v))
                if plane == 'z': hint = (hint[0],hint[2],hint[1])
                if plane == 'x': hint = (hint[1],hint[0],hint[2])
                self.quad(pts, color, hint, glow)

    def rod(self, start, end, radius, color, segments=6, glow=0.):
        start, end = np.asarray(start), np.asarray(end)
        axis = end-start
        axis = axis / np.linalg.norm(axis)
        side = np.cross(axis, (0,1,0) if abs(axis[1]) < .9 else (1,0,0))
        side /= np.linalg.norm(side)
        up = np.cross(axis, side)
        for i in range(segments):
            a,b = i*math.tau/segments,(i+1)*math.tau/segments
            da,db = radius*(side*math.cos(a)+up*math.sin(a)),radius*(side*math.cos(b)+up*math.sin(b))
            self.quad((start+da,start+db,end+db,end+da),color,(da+db)/2,glow)
        for point, normal in ((start,-axis),(end,axis)):
            for i in range(1,segments-1):
                self.quad((point+radius*side, point+radius*(side*math.cos(i*math.tau/segments)+up*math.sin(i*math.tau/segments)),
                           point+radius*(side*math.cos((i+1)*math.tau/segments)+up*math.sin((i+1)*math.tau/segments))),color,normal,glow)

    def head_pivot(self, point, *joint_parts):
        """Set the neck pivot the head turns about, and any joint parts that ride the head at rest.

        Params: point (x, y, z) in shell metres; joint_parts: extra part ids (the star's spinning tip).
        Side effect: records geometry only; no faces are added.
        """
        self.head = tuple(point)
        self.head_parts = HEAD_PARTS + tuple(joint_parts)

    def flick(self, part, pivot, sign, side):
        """Tag `part` as an antenna or ear root that twitches about its z axis.

        Params: pivot (x, y, z) root in metres; sign ±1 the swing direction; side 0 for the
        left flick or 1 for the right, indexing Idle.flick. Swing in radians = sign * flick * MAX_FLICK.
        """
        self.flicks.append((part, tuple(pivot), sign, side))

    def joint(self, part, pivot, axis, rate, amplitude=1., spin=False):
        self.part = part
        self.joints.append((part, pivot, axis, rate, amplitude, spin))

    def finish(self):
        if len(self.points) > MAX_FACES:
            raise ValueError(f'Bot mesh exceeds {MAX_FACES} faces: {len(self.points)}')
        arrays = [np.asarray(x, dtype) for x,dtype in ((self.points,np.float32),(self.normals,np.float32),
                  (self.colors,np.float32),(self.emission,np.float32),(self.parts,np.uint8))]
        for a in arrays: a.setflags(write=False)
        return LocalMesh(*arrays, tuple(self.joints), self.head, self.head_parts, tuple(self.flicks))


def _eye(b, x, y, z, radius, trim):
    b.torus((x,y,z), (radius,radius), .006, trim, plane='z', segments=12)
    # The lamp and its glint are tagged EYE so the dialogue portrait can shutter them
    # (botportrait); the trim ring stays the socket the shutter closes inside.
    part, b.part = b.part, EYE
    b.quad(((x-radius*.70,y-radius*.65,z+.004),(x+radius*.70,y-radius*.65,z+.004),
            (x+radius*.70,y+radius*.65,z+.004),(x-radius*.70,y+radius*.65,z+.004)),LAMP,(0,0,1),1.)
    b.box((x+.010,y+.009,z+.006),(.010,.014,.003),(.98,.96,.77),glow=.8)
    b.part = part


def _propeller(b, pivot, trim):
    b.ellipsoid(pivot, (.026,.026,.018),trim,8,4)
    b.joint(1,pivot,(0,0,1),12.,spin=True)
    for angle in (0,math.pi/2):
        b.box(pivot,(.11,.018,.009),trim,rotation((0,0,1),angle))
    b.part = 0


def _collar(b, neck, style):
    # A loose collar's tail can sway in the wind: 'loose@-1.00' to 'loose@1.00' (V1-35).
    style, _, sway = style.partition('@')
    sway = float(sway or 0.)
    if style == 'none': return
    x,y,z,rx,rz = neck
    b.torus((x,y,z),(rx,rz),.013,WOOL,segments=20,sides=4)
    # Raised contrasting stitches make the wool read without a texture atlas.
    for i in range(12):
        a=i*math.tau/12
        b.rod((x+rx*math.cos(a),y-.008,z+rz*math.sin(a)),
              (x+(rx+.008)*math.cos(a+.05),y+.009,z+(rz+.008)*math.sin(a+.05)),.0035,(.88,.39,.39),4)
    front = z+rz+.012
    if style in ('loop','loose'):
        end = (x+.07+.035*sway,y-.095+.012*abs(sway),front+.025) if style == 'loose' else (x+.028,y-.043,front)
        b.rod((x,y,front),end,.010,WOOL)
        if style == 'loose': b.rod(end,(x+.105+.07*sway,y-.065+.02*abs(sway),front+.04),.009,WOOL)
        return
    if style == 'bow':
        for side in (-1,1):
            b.torus((x+side*.031,y,front),(.026,.021),.008,WOOL,plane='z',segments=10)
        b.box((x,y,front),(.027,.022,.020),WOOL)
        for side in (-1,1):
            b.rod((x+side*.008,y-.007,front),(x+side*.025,y-.055,front+.004),.008,WOOL)
    elif style == 'square':
        b.rod((x-.028,y-.012,front),(x+.025,y+.012,front),.011,WOOL)
        b.rod((x+.028,y-.012,front+.008),(x-.025,y+.012,front+.008),.010,(.85,.31,.34))
        for side in (-1,1): b.rod((x+side*.020,y-.009,front),(x+side*.034,y-.048,front),.008,WOOL)
    else:
        for dy in (-.009,.009):
            b.torus((x,y+dy,front),(.018,.012),.008,WOOL,plane='z',segments=10)
        b.rod((x+.019,y,front),(x+.046,y-.065,front+.01),.009,WOOL)


@lru_cache(maxsize=12)
def local_mesh(shell_id='tin', style='none'):
    shell = BOT_SHELLS.get(shell_id, BOT_SHELLS['tin'])
    body, trim, secondary = shell.body, shell.trim, shell.secondary
    b = Builder()
    if shell.id == 'tin':
        b.box((0,.12,0),(.19,.17,.19),body)
        b.part = HEAD
        b.box((0,.265,.016),(.145,.105,.13),body)
        _eye(b,0,.265,.085,.037,trim)
        for side in (-1,1):
            b.part = HEAD
            b.ellipsoid((side*.095,.265,.008),(.024,.035,.019),trim,8,4)
            b.part = 0
            b.box((side*.064,.025,.013),(.052,.035,.16),DARK)
        for x in (-.067,.067):
            for y in (.07,.17): b.ellipsoid((x,y,.098),(.008,.008,.005),trim,6,3)
        b.part = ANTENNA
        b.rod((0,.315,0),(0,.435,0),.006,DARK)
        b.ellipsoid((0,.45,0),(.025,.025,.025),LAMP,8,4,glow=1.)
        b.part = 0
        _propeller(b,(0,.11,-.12),trim)
        b.head_pivot((0,.21,0))
        b.flick(ANTENNA,(0,.315,0),1,1)
        neck=(0,.202,.01,.078,.073)
    elif shell.id == 'frog':
        b.ellipsoid((0,.14,-.015),(.155,.115,.16),body)
        b.part = HEAD
        b.ellipsoid((0,.285,.035),(.14,.085,.12),body)
        b.part = 0
        b.ellipsoid((0,.14,.137),(.10,.075,.015),secondary,10,4)
        for side in (-1,1):
            b.part = HEAD
            b.ellipsoid((side*.078,.355,.08),(.050,.052,.050),body,8,4)
            _eye(b,side*.078,.358,.124,.024,trim)
            # Webbed brass ears fan out beside the wide enamel head.
            b.part = EAR_LEFT if side<0 else EAR_RIGHT
            root=(side*.12,.28,.025)
            for j in range(4):
                a,beta=j*math.pi/5,(j+1)*math.pi/5
                b.quad((root,(side*(.15+.045*math.sin(a)),.28+.065*math.cos(a),.025),
                         (side*(.15+.045*math.sin(beta)),.28+.065*math.cos(beta),.025)),trim,(0,0,1))
            b.joint(2 if side<0 else 3,(side*.11,.06,0),(1,0,0),5.,.20)
            b.box((side*.12,.045,.045),(.075,.045,.13),body)
            for toe in (-1,0,1):
                b.rod((side*.12,.026,.09),(side*.12+toe*.026,.020,.16-abs(toe)*.015),.011,trim)
            b.part=0
        b.head_pivot((0,.25,0))
        b.flick(EAR_LEFT,(-.12,.28,.025),-1,0)
        b.flick(EAR_RIGHT,(.12,.28,.025),1,1)
        neck=(0,.222,.032,.115,.100)
    elif shell.id == 'duck':
        b.ellipsoid((0,.15,-.025),(.15,.12,.185),body,12,6)
        b.part = HEAD
        b.ellipsoid((0,.32,.085),(.09,.09,.085),body)
        b.box((0,.290,.178),(.125,.035,.095),trim)
        b.part = 0
        for side in (-1,1):
            part, b.part = b.part, EYE  # the duck's painted eyes take the portrait's lids too
            b.ellipsoid((side*.048,.35,.153),(.017,.020,.010),DARK,8,4)
            b.ellipsoid((side*.048,.355,.161),(.006,.007,.004),(.97,.97,.90),6,3)
            b.part = part
            b.joint(2 if side<0 else 3,(side*.13,.18,-.035),(0,0,1),4.,side*.25)
            b.ellipsoid((side*.14,.18,-.045),(.025,.075,.10),body,8,4)
            b.part=0
            b.torus((side*.149,.14,-.025),(.043,.043),.007,secondary,plane='x',segments=12)
            for j in range(6):
                a=j*math.tau/6
                b.rod((side*.155,.14,-.025),(side*.155,.14+.038*math.cos(a),-.025+.038*math.sin(a)),.004,secondary,4)
            b.box((side*.06,.025,.015),(.060,.035,.14),trim)
        b.box((0,.20,-.19),(.10,.025,.065),body,rotation((1,0,0),-.4))
        b.head_pivot((0,.26,.03))
        neck=(0,.245,.08,.078,.073)
    elif shell.id == 'sub':
        b.ellipsoid((0,.145,0),(.145,.105,.225),body,12,6)
        b.part = HEAD
        b.ellipsoid((0,.285,.01),(.105,.105,.115),secondary,12,5)
        b.torus((0,.226,.01),(.108,.12),.012,trim,segments=16)
        _eye(b,0,.285,.124,.035,trim)
        for side in (-1,1):
            b.part = HEAD
            b.quad(((side*.03,.36,.068),(side*.06,.34,.09),(side*.06,.305,.108),(side*.03,.33,.096)),(.64,.85,.85),(0,0,1))
            b.part = 0
            b.box((side*.145,.11,-.09),(.080,.020,.11),trim)
            b.box((side*.07,.022,0),(.042,.030,.19),DARK)
        b.part = ANTENNA
        b.rod((0,.38,-.035),(0,.445,-.035),.009,trim)
        b.rod((0,.445,-.035),(.04,.445,-.035),.010,trim)
        b.part = 0
        _propeller(b,(0,.14,-.24),trim)
        b.head_pivot((0,.23,0))
        b.flick(ANTENNA,(0,.37,-.035),1,1)
        neck=(0,.230,.01,.112,.120)
    else:
        b.ellipsoid((0,.14,0),(.135,.115,.145),body,10,6,glow=.38)
        # An extruded five-point star is a recognisable silhouette from any view.
        outline=[]
        for i in range(10):
            a=math.pi/2+i*math.pi/5;r=.14 if i%2==0 else .072
            outline.append((r*math.cos(a),.30+r*math.sin(a)))
        b.part = HEAD
        for i in range(10):
            a,c=outline[i],outline[(i+1)%10]
            b.quad(((0,.30,.105),(*a,.105),(*c,.105)),body,(0,0,1),.45)
            b.quad(((0,.30,-.035),(*c,-.035),(*a,-.035)),trim,(0,0,-1),.30)
            b.quad(((*a,-.035),(*c,-.035),(*c,.105),(*a,.105)),trim,(a[0]+c[0],a[1]+c[1]-.6,0),.45)
        _eye(b,0,.30,.110,.029,secondary)
        for x,y,z in ((-.07,.16,.12),(.055,.13,.13),(.00,.08,.13),(-.055,.33,.111),(.060,.34,.111)):
            b.ellipsoid((x,y,z),(.006,.006,.004),secondary,6,3,glow=1.)
        b.part = 0
        for side in (-1,1): b.box((side*.055,.022,0),(.042,.028,.15),trim,glow=.25)
        b.part = HEAD
        b.rod((0,.435,0),(0,.48,0),.004,trim,glow=.4)
        b.joint(1,(0,.49,0),(0,1,0),1.8,spin=True)
        for side in (-1,1):
            b.quad(((0,.53,0),(side*.025,.49,.018),(0,.46,0),(side*.025,.49,-.018)),secondary,(side,0,0),1.)
        b.part=0
        b.head_pivot((0,.26,0),1)
        neck=(0,.225,.01,.090,.079)
    _collar(b,neck,style)
    return b.finish()


def collar_style(stage='none', knot=None, collar_visible=True):
    """The local_mesh collar style for a collar stage, chosen knot and visibility setting."""
    if not collar_visible or stage == 'none':
        return 'none'
    if stage == 'loose':
        return 'loose'
    return knot if knot in ('square', 'bow', 'sailors_hitch') else 'loop'


class Idle(NamedTuple):
    """One frame of Bot's idle pose at home. The all-zero pose is the rest pose.

    yaw, pitch: head turn in radians; +yaw turns the face toward local +x, +pitch tips the nose down.
    blink: 0 open to 1 shut; the lamp shutters toward its centre.
    flick: (left, right) 0-1 twitch of each antenna or ear.
    hum: body lift in metres above the perch.
    """
    yaw: float = 0.
    pitch: float = 0.
    blink: float = 0.
    flick: tuple = (0., 0.)
    hum: float = 0.


def _turn(points, normals, mask, pivot, matrix):
    """Rotate the faces under `mask` about `pivot` by `matrix`, points and normals alike, in place."""
    p = np.asarray(pivot, np.float32)
    points[mask] = (points[mask]-p) @ matrix.T + p
    normals[mask] = normals[mask] @ matrix.T


def _posed(mesh, idle):
    """Copies of the mesh's points and normals with the idle pose applied.

    Order matters: the lamp shutter and the flicks are shaped in each part's own frame, then
    the head turns them about its neck pivot. The cached mesh is never written.
    """
    points, normals = mesh.points.copy(), mesh.normals.copy()
    if idle.blink:
        mask = mesh.parts == EYE
        if mask.any():
            # Scale each lamp face toward its own centre so the shutter closes inside the socket.
            centre = points[mask].mean(axis=1, keepdims=True)
            points[mask] = centre + (points[mask]-centre) * np.array((1., 1.-SHUT*idle.blink, 1.), np.float32)
    for part, pivot, sign, side in mesh.flicks:
        angle = sign * idle.flick[side] * MAX_FLICK
        mask = mesh.parts == part
        if angle and mask.any():
            _turn(points, normals, mask, pivot, rotation((0, 0, 1), angle))
    if mesh.head and (idle.yaw or idle.pitch):
        matrix = rotation((0, 1, 0), idle.yaw) @ rotation((1, 0, 0), idle.pitch)
        _turn(points, normals, np.isin(mesh.parts, mesh.head_parts), mesh.head, matrix)
    return points, normals


def _turn_rows(pts, nrm, mask, pivot, matrix):
    """Rotate the masked faces of (N, 6, 3) packed points and normals about a world pivot, in place."""
    p = np.asarray(pivot, np.float32)
    pts[mask] = (pts[mask]-p) @ matrix.T + p
    nrm[mask] = nrm[mask] @ matrix.T


def posed_rows(rows, mesh, origin, basis, idle):
    """The packed rest pose with `idle` applied in world space: the NumPy twin of `faces`' idle pose.

    rows: (6N, 10) packed rest pose, six rows per face in mesh order, built from the bob-free rest
    `origin`. mesh: the shell's LocalMesh, for its parts, pivots and flicks. basis: (3, 3) with
    columns right, up, forward. Each shell-frame rotation R becomes basis @ R @ basis.T, and each
    pivot maps through the basis, so the rows match `_posed` followed by the basis map. The
    hum lifts the whole pose. Returns a new array; `rows` is not changed.
    """
    out = rows.copy()
    pts = out[:, :3].reshape(-1, 6, 3).copy()
    nrm = out[:, 3:6].reshape(-1, 6, 3).copy()
    hum = np.array((0., idle.hum, 0.), np.float32)
    origin = np.asarray(origin, np.float32) + hum
    pts += hum
    parts = mesh.parts
    if idle.blink:
        mask = parts == EYE
        if mask.any():
            # The packed triangles repeat corners 0 and 2, so a face's four corners are 0, 1, 2 and 5.
            corners = pts[mask]
            centre = (corners[:, 0] + corners[:, 1] + corners[:, 2] + corners[:, 5]) / 4
            along = (corners - centre[:, None]) @ basis[:, 1]
            pts[mask] = corners - (SHUT * idle.blink) * along[..., None] * basis[:, 1]
    for part, pivot, sign, side in mesh.flicks:
        angle = sign * idle.flick[side] * MAX_FLICK
        mask = parts == part
        if angle and mask.any():
            _turn_rows(pts, nrm, mask, origin + basis @ np.asarray(pivot, np.float32),
                       basis @ rotation((0, 0, 1), angle) @ basis.T)
    if mesh.head and (idle.yaw or idle.pitch):
        local = rotation((0, 1, 0), idle.yaw) @ rotation((1, 0, 0), idle.pitch)
        _turn_rows(pts, nrm, np.isin(parts, mesh.head_parts), origin + basis @ np.asarray(mesh.head, np.float32),
                   basis @ local @ basis.T)
    out[:, :3] = pts.reshape(-1, 3)
    out[:, 3:6] = nrm.reshape(-1, 3)
    return out


def faces(origin, right, up, forward, *, shell='tin', stage='none', knot=None,
          collar_visible=True, scale=1., anim=0., scouting=False, reduced_motion=False, sway=0., idle=None):
    """World-space faces of one Bot shell placed by an origin and a basis (right, up, forward).

    origin: world (x, y, z) in metres of the shell's base centre. right/up/forward: unit axes
    that map the shell's local x, y, z. scale: a size multiplier. anim: the clock in seconds.
    scouting: animate the scout joints (propeller, legs, wings, star) and ignore `idle`.
    reduced_motion: hold every joint and idle motion still. idle: an Idle pose for the home
    rig, or None for the rest pose. Returns a list of Face; the cached local mesh is not changed.
    """
    style = collar_style(stage, knot, collar_visible)
    if style == 'loose' and sway:
        style = f'loose@{max(-1., min(1., sway)):.2f}'
    mesh = local_mesh(shell,style)
    if idle is not None and not scouting and not reduced_motion:
        points, normals = _posed(mesh, idle)
    else:
        points, normals = mesh.points, mesh.normals
    if scouting and not reduced_motion and mesh.joints:
        points, normals = points.copy(), normals.copy()
        for part,pivot,axis,rate,amp,spin in mesh.joints:
            mask=mesh.parts==part
            angle=anim*rate if spin else math.sin(anim*rate)*amp
            matrix=rotation(axis,angle)
            p=np.asarray(pivot,np.float32)
            points[mask]=(points[mask]-p) @ matrix.T+p
            normals[mask]=normals[mask] @ matrix.T
    basis=np.stack((right,up,forward),axis=1).astype(np.float32)
    world_points=points @ basis.T*np.float32(scale)+np.asarray(origin,np.float32)
    world_normals=normals @ basis.T
    return [Face(world_points[i],world_normals[i],mesh.colors[i],'world',float(mesh.emission[i])) for i in range(len(world_points))]
