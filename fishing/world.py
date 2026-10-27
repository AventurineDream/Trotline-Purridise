"""The loaded water: Briar, Cedar's survey, or a small flat systems map.

Coordinates are meters. +X is east, +Z is north, Y is up. The water is y = 0.
The shoreline is an ellipse with a northwest creek cove, so the same function
feeds the boat, the bites, and the picture.
"""

from __future__ import annotations

import math
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .data import ZONE_NAME, ZONE_ORDER
from .boat import BOATS, hull_samples, hits_rectangles, hits_round_props
from .lakes import LAKES, LAKE_ZONE_NAMES

RX = 430.0
RZ = 285.0
INLET_THETA = math.atan2(165.0, -240.0)
DOCK_THETA = 2.90

# Height grid. Shore detail is a few meters; far ridges are added in the sample.
X0, X1 = -780.0, 780.0
Z0, Z1 = -620.0, 620.0
NX, NZ = 1240, 992  # about 1.25 m, so the bank does not facet up close


def _as(v) -> np.ndarray:
    return np.asarray(v, dtype=np.float32)


def smoothstep(x, e0, e1):
    t = np.clip((_as(x) - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def hash21(ix, iz) -> np.ndarray:
    ix = np.asarray(ix, dtype=np.int64)
    iz = np.asarray(iz, dtype=np.int64)
    n = (ix * np.int64(374761393) + iz * np.int64(668265263)) & np.int64(0xFFFFFFFF)
    n = (n ^ (n >> 13)) * np.int64(1274126177) & np.int64(0xFFFFFFFF)
    return ((n & np.int64(0xFFFFFF)).astype(np.float32) / np.float32(16777215.0))


def noise2(x, z) -> np.ndarray:
    x = _as(x)
    z = _as(z)
    x0 = np.floor(x).astype(np.int64)
    z0 = np.floor(z).astype(np.int64)
    fx = x - x0.astype(np.float32)
    fz = z - z0.astype(np.float32)
    sx = fx * fx * (3.0 - 2.0 * fx)
    sz = fz * fz * (3.0 - 2.0 * fz)
    v00 = hash21(x0, z0)
    v10 = hash21(x0 + 1, z0)
    v01 = hash21(x0, z0 + 1)
    v11 = hash21(x0 + 1, z0 + 1)
    return (v00 * (1 - sx) + v10 * sx) * (1 - sz) + (v01 * (1 - sx) + v11 * sx) * sz


def _warp(theta: np.ndarray) -> np.ndarray:
    inlet = np.exp(-((theta - np.float32(INLET_THETA)) ** 2) / np.float32(2 * 0.16 ** 2))
    return (
        1.0
        + 0.050 * np.sin(3.0 * theta)
        + 0.035 * np.sin(5.0 * theta + 0.7)
        + 0.020 * np.sin(8.0 * theta + 1.9)
        + 0.145 * inlet
    )


def shore_sd(x, z) -> np.ndarray:
    """Meters, negative in the water. Approximate, and monotonic along a ray from center."""
    x = _as(x)
    z = _as(z)
    theta = np.arctan2(z, x)
    rho = np.hypot(x, z)
    c = np.cos(theta)
    s = np.sin(theta)
    # Meters from the origin to the unwarped ellipse along this ray.
    radial = np.hypot(c * np.float32(RX), s * np.float32(RZ))
    limit = radial * _warp(theta)
    return rho - limit


def shore_radius(theta: float) -> float:
    lo, hi = 0.0, 900.0
    for _ in range(28):
        mid = (lo + hi) * 0.5
        x = math.cos(theta) * mid
        z = math.sin(theta) * mid
        if float(shore_sd(x, z)) < 0.0:
            lo = mid
        else:
            hi = mid
    return lo


def shore_xy(theta: float, extra: float = 0.0) -> tuple[float, float]:
    r = shore_radius(theta) + extra
    return math.cos(theta) * r, math.sin(theta) * r


class Slip:
    """A rectangular cut of water at the landing, in its own axes."""

    def __init__(self, ox, oz, inland, side, half_w, land_ext, water_ext):
        self.ox = float(ox)
        self.oz = float(oz)
        self.ix = float(inland[0])
        self.iz = float(inland[1])
        self.sx = float(side[0])
        self.sz = float(side[1])
        self.half_w = float(half_w)
        self.land_ext = float(land_ext)
        self.water_ext = float(water_ext)

    def local(self, x, z):
        dx = _as(x) - np.float32(self.ox)
        dz = _as(z) - np.float32(self.oz)
        a = dx * np.float32(self.ix) + dz * np.float32(self.iz)
        s = dx * np.float32(self.sx) + dz * np.float32(self.sz)
        return a, s

    def contains(self, x, z) -> np.ndarray:
        a, s = self.local(x, z)
        return (np.abs(s) <= self.half_w) & (a >= -self.water_ext) & (a <= self.land_ext)

    def world(self, a, s) -> tuple[float, float]:
        return (
            self.ox + a * self.ix + s * self.sx,
            self.oz + a * self.iz + s * self.sz,
        )


def make_slip() -> Slip:
    x, z = shore_xy(DOCK_THETA, 0.0)
    # Outward (toward land) is away from the lake center.
    length = math.hypot(x, z) or 1.0
    inland = (x / length, z / length)
    side = (-inland[1], inland[0])
    return Slip(x, z, inland, side, half_w=3.5, land_ext=12.0, water_ext=18.0)


@dataclass
class Prop:
    kind: str
    x: float
    z: float
    h: float
    shade: float


@dataclass
class Face:
    pts: np.ndarray  # (4, 3) world or camera
    normal: np.ndarray  # (3,)
    color: np.ndarray  # (3,) 0-1
    space: str = "world"


def _face(pts, normal, color) -> Face:
    n = np.asarray(normal, dtype=np.float32)
    n = n / (np.linalg.norm(n) + 1e-8)
    return Face(
        pts=np.asarray(pts, dtype=np.float32),
        normal=n,
        color=np.asarray(color, dtype=np.float32),
    )


def _box(center, ax, ay, az, size, color) -> list[Face]:
    """Axis-aligned in the frame of ax/ay/az. `size` is full width along each axis."""
    c = np.asarray(center, dtype=np.float32)
    ax = np.asarray(ax, dtype=np.float32)
    ay = np.asarray(ay, dtype=np.float32)
    az = np.asarray(az, dtype=np.float32)
    ax = ax / (np.linalg.norm(ax) + 1e-8) * (size[0] * 0.5)
    ay = ay / (np.linalg.norm(ay) + 1e-8) * (size[1] * 0.5)
    az = az / (np.linalg.norm(az) + 1e-8) * (size[2] * 0.5)

    def p(sx, sy, sz):
        return c + sx * ax + sy * ay + sz * az

    specs = (
        ((-1, 1, -1), (1, 1, -1), (1, 1, 1), (-1, 1, 1), ay),
        ((-1, -1, -1), (-1, -1, 1), (1, -1, 1), (1, -1, -1), -ay),
        ((1, -1, -1), (1, -1, 1), (1, 1, 1), (1, 1, -1), ax),
        ((-1, -1, -1), (-1, 1, -1), (-1, 1, 1), (-1, -1, 1), -ax),
        ((-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1), az),
        ((-1, -1, -1), (-1, 1, -1), (1, 1, -1), (1, -1, -1), -az),
    )
    faces = []
    for a, b, c_, d, nrm in specs:
        faces.append(_face([p(*a), p(*b), p(*c_), p(*d)], nrm, color))
    return faces


class World:
    def __init__(self,lake_id="briar"):
        if lake_id not in LAKES:
            raise ValueError("Unknown lake")
        self.id = lake_id
        self.name = LAKES[lake_id]["name"]
        self.landing = LAKES[lake_id]["landing"]
        self.zone_names = LAKE_ZONE_NAMES[lake_id]
        self.placeholder = LAKES[lake_id]["placeholder"]
        self.palette = LAKES[lake_id]["palette"]
        self.bounds = (X0,Z0,X1,Z1)
        self.nx,self.nz = NX,NZ
        self.shore_grid = None
        if lake_id=="cedar":
            assets = Path(__file__).with_name("assets")
            self.metadata = json.loads((assets/"cedar.json").read_text())
            with np.load(assets/"cedar.npz",allow_pickle=False) as data:
                self.shore_grid = data["shore"]
                self.depth_grid = data["depth"]
                self.coast = data["coast"]
            self.bounds = tuple(self.metadata["bounds"])
            self.nz,self.nx = self.shore_grid.shape
            ix,iz = self.metadata["slip_inland"]
            ox,oz = self.metadata["slip_origin"]
            self.slip = Slip(ox,oz,(ix,iz),(-iz,ix),3.0,10.0,10.0)
        elif self.placeholder:
            self.bounds = (-420.0, -320.0, 420.0, 320.0)
            self.nx, self.nz = 169, 129
            self.slip = Slip(-320, 0, (-1, 0), (0, -1), 3.5, 12, 18)
        else:
            self.slip = make_slip()
        self.dock = (self.slip.ox, self.slip.oz)
        self.zones = self._zone_table()
        self.height = self._bake_height()
        self.faces = self._build_camp()
        if self.id == "cedar":
            self.faces.extend(self._build_trinidad_cove())
        from .marina import Marina, build_marina
        self.marina = Marina([], (), ()) if self.placeholder else build_marina(self)
        self.faces.extend(self.marina.faces)
        self.props = [] if self.placeholder else self._place_props()
        # Static buildings and piers occupy these clearings. Keep random old
        # scenery from growing through them as the shoreline becomes richer.
        self.props = [p for p in self.props if not self._in_marina_clearing(p.x,p.z)]
        from .shoreline import shoreline_props
        if not self.placeholder:
            self.props.extend(shoreline_props(self, Prop))
        # Physical footprints of the two piers and the crossbeam. The values
        # match the camp meshes, including their extent into the slip.
        self.dock_barriers = np.array([
            (4.0,-self.slip.half_w-0.85,8.0,0.775),
            (4.0, self.slip.half_w+0.85,8.0,0.775),
            (self.slip.land_ext-0.4,0.0,0.20,self.slip.half_w+1.6),
        ],np.float64)
        self.dock_barriers = np.vstack((self.dock_barriers,self.marina.barriers))
        self.solid_props = np.array([
            (p.x,p.z,max(0.16,p.h*0.23)) for p in self.props
            if p.kind in ("rock","stump","knee")],np.float64).reshape(-1,3)
        self.map_rgb, self.map_small = self._bake_map()
        from .anchors import anchors_for_lake
        self.anchors = anchors_for_lake(self.id)

    def _in_marina_clearing(self,x,z):
        a,s = self.slip.local(x,z)
        # Leave existing obstacles in the original service lane alone. The
        # clearings follow only the new structures, with room for tree crowns.
        for footprint in (*self.marina.footprints,*self.marina.shore_buildings):
            if (abs(float(a)-footprint.a)<footprint.half_a+8
                    and abs(float(s)-footprint.s)<footprint.half_s+8):
                return True
        return False

    def zone_name(self,zone):
        return self.zone_names.get(zone,zone)

    def _sample_grid(self,grid,x,z):
        if np.isscalar(x) and np.isscalar(z):
            x0,z0,x1,z1 = self.bounds
            u = min(self.nx-1.001,max(0.0,(x-x0)/(x1-x0)*(self.nx-1)))
            v = min(self.nz-1.001,max(0.0,(z-z0)/(z1-z0)*(self.nz-1)))
            ix,iz = int(u),int(v)
            fx,fz = u-ix,v-iz
            return np.float32((grid[iz,ix]*(1-fx)+grid[iz,ix+1]*fx)*(1-fz)
                              +(grid[iz+1,ix]*(1-fx)+grid[iz+1,ix+1]*fx)*fz)
        x,z = np.broadcast_arrays(_as(x),_as(z))
        x0,z0,x1,z1 = self.bounds
        u = np.clip((x-x0)/(x1-x0)*(self.nx-1),0,self.nx-1.001)
        v = np.clip((z-z0)/(z1-z0)*(self.nz-1),0,self.nz-1.001)
        ix,iz = u.astype(np.int32),v.astype(np.int32)
        fx,fz = u-ix,v-iz
        return ((grid[iz,ix]*(1-fx)+grid[iz,ix+1]*fx)*(1-fz)
                +(grid[iz+1,ix]*(1-fx)+grid[iz+1,ix+1]*fx)*fz).astype(np.float32)

    def shore_sd(self,x,z):
        if self.placeholder:
            return np.maximum(np.abs(_as(x)) - 320.0, np.abs(_as(z)) - 240.0)
        return shore_sd(x,z) if self.shore_grid is None else self._sample_grid(self.shore_grid,x,z)

    def _zone_table(self):
        if self.id=="cedar":
            return tuple(tuple(row) for row in self.metadata["zones"])
        if self.placeholder:
            # Shared flat test water; later lake art can replace these charts.
            centres = (
                ("inlet", -170.0, 130.0, 60.0), ("flats", 20.0, 150.0, 62.0),
                ("lilies", -160.0, -120.0, 62.0), ("cypress", 220.0, 30.0, 62.0),
                ("rocks", 20.0, -160.0, 62.0), ("deep", 65.0, -20.0, 65.0),
                ("reeds", -230.0, 10.0, 42.0), ("springs", -180.0, 120.0, 62.0),
                ("current", 170.0, 110.0, 65.0),
            )
            return tuple(row for row in centres if row[0] in self.zone_names)
        # (id, x, z, radius). Landing is forced separately.
        return (
            ("inlet", -210.0, 155.0, 100.0),
            ("flats", 10.0, 205.0, 125.0),
            ("lilies", -175.0, -115.0, 115.0),
            ("cypress", 330.0, 20.0, 130.0),
            ("rocks", 15.0, -195.0, 120.0),
            ("deep", 75.0, -25.0, 100.0),
            ("reeds", -338.0, -42.0, 44.0),
        )

    def depth(self, x, z) -> np.ndarray:
        sd = self.shore_sd(x, z)
        if self.placeholder:
            return np.where((sd < 0) | self.slip.contains(x, z), 4.0, 0.0).astype(np.float32)
        if self.id=="cedar":
            depth = np.where(sd<0,self._sample_grid(self.depth_grid,x,z),0.0)
            return np.where(self.slip.contains(x,z),np.maximum(depth,1.35),depth).astype(np.float32)
        x = _as(x)
        z = _as(z)
        dist = np.clip(-sd, 0.0, None)
        shelf = 0.50 + 2.15 * (1.0 - np.exp(-dist / 16.0))
        shelf = shelf + 2.7 * smoothstep(dist, 12.0, 62.0)
        shelf = shelf + 11.5 * np.exp(-((x - 75.0) ** 2 + (z + 28.0) ** 2) / (2 * 72.0 ** 2))
        shelf = shelf + 1.6 * np.exp(-((x + 20.0) ** 2 + (z + 5.0) ** 2) / (2 * 120.0 ** 2))
        shelf = shelf - 3.15 * np.exp(-((x - 10.0) ** 2 + (z - 205.0) ** 2) / (2 * 64.0 ** 2))
        shelf = shelf + 2.3 * np.exp(-((x + 210.0) ** 2 + (z - 155.0) ** 2) / (2 * 52.0 ** 2))
        shelf = np.clip(shelf, 0.40, 18.0)
        out = np.where(sd < 0.0, shelf, np.float32(0.0)).astype(np.float32)
        out = np.where(self.slip.contains(x, z), np.maximum(out, np.float32(1.35)), out)
        return out

    def zone_at(self, x: float, z: float) -> str:
        if float(self.shore_sd(x, z)) >= 0.0 and not bool(self.slip.contains(x, z)):
            return "shore"
        dx = x - self.slip.ox
        dz = z - self.slip.oz
        if dx * dx + dz * dz < 50.0 * 50.0:
            return "landing"
        best = "open"
        best_d = 1e9
        for name, cx, cz, radius in self.zones:
            d = math.hypot(x - cx, z - cz)
            if d <= radius and d < best_d:
                best = name
                best_d = d
        return best

    def zone_ids(self, x, z) -> np.ndarray:
        """Integer ids matching ZONE_ORDER, for the water tint."""
        x = _as(x)
        z = _as(z)
        # Default open, index of "open" in ZONE_ORDER.
        open_i = ZONE_ORDER.index("open")
        best = np.full(x.shape, open_i, dtype=np.int32)
        best_d = np.full(x.shape, np.float32(1e9))
        for name, cx, cz, radius in self.zones:
            d = np.hypot(x - np.float32(cx), z - np.float32(cz))
            idx = ZONE_ORDER.index(name)
            take = (d <= radius) & (d < best_d)
            best = np.where(take, idx, best)
            best_d = np.where(take, d, best_d)
        dock_d = np.hypot(x - np.float32(self.slip.ox), z - np.float32(self.slip.oz))
        best = np.where(dock_d < 50.0, ZONE_ORDER.index("landing"), best)
        return best

    def navigable(self, x: float, z: float) -> bool:
        return bool(self.navigable_mask(x,z))

    def navigable_mask(self,x,z,draft=0.47):
        return self.slip.contains(x,z)|((self.shore_sd(x,z)<=-2.2)&(self.depth(x,z)>=draft+0.08))

    def hull_clear(self,x,z,yaw,boat_id="jon"):
        points = hull_samples(x,z,yaw,boat_id)
        if not np.all(self.navigable_mask(points[:,0],points[:,1],BOATS[boat_id].draft)):
            return False
        if hits_rectangles(x,z,yaw,self.slip,self.dock_barriers,boat_id):
            return False
        return not hits_round_props(x,z,yaw,self.solid_props,boat_id)

    def clear_boat_position(self,x,z,yaw,boat_id="jon"):
        """Recover a legacy save parked inside the new hull barriers."""
        if self.hull_clear(x,z,yaw,boat_id):
            return x,z,yaw
        for radius in (0.12,0.25,0.5,1.0,1.5,2.0,3.0,4.0,6.0):
            for angle in np.linspace(0,math.tau,24,endpoint=False):
                px,pz = x+math.cos(angle)*radius,z+math.sin(angle)*radius
                if self.hull_clear(px,pz,yaw,boat_id):
                    return px,pz,yaw
        px,pz = self.slip.world(4.0,0.0)
        return px,pz,math.atan2(-self.slip.ix,-self.slip.iz)

    def _ground(self, x, z) -> np.ndarray:
        """Smooth bank. One formula, baked once so the march stays cheap."""
        sd = self.shore_sd(x, z)
        if self.placeholder:
            return np.where((sd < 0) | self.slip.contains(x, z), 0.0, 0.45).astype(np.float32)
        inland = np.clip(sd, 0.0, None)
        h = inland * np.float32(0.035)
        h = h + smoothstep(inland, 1.5, 40.0) * np.float32(4.2)
        h = h + np.power(np.maximum(inland - np.float32(28.0), 0.0), np.float32(1.05)) * np.float32(0.016)
        n = noise2(x * np.float32(0.011), z * np.float32(0.011))
        h = h + (n - np.float32(0.35)) * np.clip(inland, 0.0, 40.0) * np.float32(0.045)
        # Low, rolling wooded hills beyond the bank. Avoid a single steep
        # enclosing wall dominating every view across the lake.
        rolling = (8.0+noise2(x*0.006,z*0.006)*15.0
                   +noise2(x*0.014+20,z*0.014)*8.0)
        blend = smoothstep(inland,70.0,220.0)
        h = h*(1.0-blend)+rolling*blend
        h = np.where(sd < 0.0, np.float32(0.0), h)
        a, s = self.slip.local(x, z)
        pad = (a > -3.0) & (a < 28.0) & (np.abs(s) < 18.0) & ~self.slip.contains(x, z)
        h = np.where(pad, np.float32(0.45), h)
        h = np.where(self.slip.contains(x, z), np.float32(0.0), h)
        return h.astype(np.float32)

    def _bake_height(self) -> np.ndarray:
        x0,z0,x1,z1 = self.bounds
        xs = np.linspace(x0,x1,self.nx,dtype=np.float32)
        zs = np.linspace(z0,z1,self.nz,dtype=np.float32)
        x, z = np.meshgrid(xs, zs)
        return self._ground(x, z)

    def sample_height(self, x, z) -> np.ndarray:
        if self.id=="cedar" or self.placeholder:
            return self._sample_grid(self.height,x,z)
        x = _as(x)
        z = _as(z)
        u = (x - X0) / (X1 - X0) * (NX - 1)
        v = (z - Z0) / (Z1 - Z0) * (NZ - 1)
        u = np.clip(u, 0.0, NX - 1.001)
        v = np.clip(v, 0.0, NZ - 1.001)
        u0 = np.floor(u).astype(np.int32)
        v0 = np.floor(v).astype(np.int32)
        fu = (u - u0).astype(np.float32)
        fv = (v - v0).astype(np.float32)
        g = self.height
        g00 = g[v0, u0]
        g10 = g[v0, np.minimum(u0 + 1, NX - 1)]
        g01 = g[np.minimum(v0 + 1, NZ - 1), u0]
        g11 = g[np.minimum(v0 + 1, NZ - 1), np.minimum(u0 + 1, NX - 1)]
        h = (g00 * (1 - fu) + g10 * fu) * (1 - fv) + (g01 * (1 - fu) + g11 * fu) * fv
        # Far ridges only. A batch that mixes a near ray with a far one must not
        # lift the shoreline: the old gate added the ridge to every sample.
        return self._add_far_ridge(h, x, z)

    def _add_far_ridge(self, h, x, z) -> np.ndarray:
        shape = h.shape
        h = np.array(h, dtype=np.float32, copy=True).reshape(-1)
        x = _as(x).reshape(-1)
        z = _as(z).reshape(-1)
        r2 = x * x + z * z
        far = np.flatnonzero(r2 > np.float32(640.0 * 640.0))
        if far.size:
            rf = np.sqrt(r2[far])
            theta = np.arctan2(z[far], x[far])
            ridge = 18.0 + 10.0 * np.sin(3.0 * theta) + 6.0 * np.sin(5.0 * theta + 1.1)
            # Zero at 640 m so the bank the boat approaches is the baked grid alone.
            fade = smoothstep(rf, 640.0, 780.0)
            extra = np.clip(rf - np.float32(640.0), 0.0, 700.0) * np.float32(0.009)
            extra = extra + ridge.astype(np.float32) * np.exp(-((rf - 980.0) ** 2) / (2 * 170.0 ** 2)) * fade
            h[far] = h[far] + extra
        return h.reshape(shape)

    def _build_camp(self) -> list[Face]:
        sl = self.slip
        inland = (sl.ix, 0.0, sl.iz)
        side = (sl.sx, 0.0, sl.sz)
        up = (0.0, 1.0, 0.0)
        faces: list[Face] = []
        wood = (0.62, 0.46, 0.28)
        wood_dark = (0.48, 0.34, 0.20)
        post = (0.42, 0.30, 0.18)
        wall = (0.70, 0.54, 0.36)
        roof = (0.32, 0.36, 0.38)
        tin = (0.55, 0.58, 0.56)

        def center(a, s, y):
            x, z = sl.world(a, s)
            return (x, y, z)

        # Piers along both sides of the slip, plus a beam across the inland end.
        for sign in (-1.0, 1.0):
            s = sign * (sl.half_w + 0.85)
            faces += _box(center(4.0, s, 0.46), inland, up, side, (16.0, 0.16, 1.55), wood)
            for a in (-2.0, 2.0, 6.0, 10.0):
                faces += _box(center(a, s, 0.20), inland, up, side, (0.28, 0.48, 0.28), post)
        faces += _box(center(sl.land_ext - 0.4, 0.0, 0.62), inland, up, side, (0.4, 0.70, sl.half_w * 2 + 3.2), wood_dark)
        # Shack on the pad, just inland of the beam.
        faces += _box(center(17.5, -1.2, 1.85), inland, up, side, (6.2, 2.5, 5.0), wall)
        # A pitched tin roof, with a real ridge rather than a floating slab.
        def roof_point(a,s,y):
            return np.array(center(a,s,y),np.float32)
        for sign in (-1,1):
            edge_s = -1.2+sign*3.0
            pts = [roof_point(13.9,edge_s,3.12),roof_point(21.1,edge_s,3.12),
                   roof_point(21.1,-1.2,4.05),roof_point(13.9,-1.2,4.05)]
            normal = np.array(up)*3+np.array(side)*sign*0.93
            faces.append(_face(pts,normal,roof))
        faces += _box(center(14.6, -1.2, 1.35), inland, up, side, (0.12, 1.6, 1.1), (0.20, 0.16, 0.12))
        # Individual dock boards, siding, window frames and a warm lantern.
        for sign in (-1,1):
            s = sign*(sl.half_w+0.85)
            for i in range(40):
                a = -3.8+i*0.40
                shade = 0.90+0.025*(i%5)
                faces += _box(center(a,s,0.548),inland,up,side,(0.374,0.012,1.48),
                              tuple(c*shade for c in wood))
        for i in range(13):
            s = -3.6+i*0.40
            faces += _box(center(14.38,s,1.85),inland,up,side,(0.045,2.5,0.025),wood_dark)
        for s in (-2.9,0.6):
            faces += _box(center(14.34,s,2.15),inland,up,side,(0.06,0.78,0.82),(0.12,0.22,0.23))
            for ds in (-0.46,0.46):
                faces += _box(center(14.28,s+ds,2.15),inland,up,side,(0.09,0.94,0.075),wood_dark)
            faces += _box(center(14.26,s,2.15),inland,up,side,(0.09,0.06,0.90),wood)
            for y in (1.70,2.60):
                faces += _box(center(14.28,s,y),inland,up,side,(0.09,0.08,1.0),wood_dark)
        # A lamp and a bait barrel.
        faces += _box(center(12.4, 2.4, 1.55), inland, up, side, (0.16, 2.2, 0.16), post)
        faces += _box(center(12.4, 2.4, 2.55), inland, up, side, (0.55, 0.18, 0.55), tin)
        faces += _box(center(12.4,2.4,2.32),inland,up,side,(0.21,0.32,0.21),(0.94,0.67,0.22))
        faces += _box(center(11.2, -3.6, 0.85), inland, up, side, (0.7, 0.7, 0.7), (0.35, 0.28, 0.18))
        return faces

    def _build_trinidad_cove(self) -> list[Face]:
        """A short cedar creek landing on the west bank, separate from the survey."""
        along = np.array([0.88, 0.0, 0.475], np.float32)
        across = np.array([-0.475, 0.0, 0.88], np.float32)
        up = (0.0, 1.0, 0.0)
        origin = np.array([181.25, 0.0, -858.36], np.float32)

        def center(t, s, y):
            p = origin + along * t + across * s
            return (float(p[0]), y, float(p[2]))

        faces: list[Face] = []
        wood = (0.46, 0.31, 0.18)
        board = (0.59, 0.42, 0.25)
        edge = (0.31, 0.23, 0.16)
        # A narrow plank launch reaches from the bank into the existing cove.
        for i, t in enumerate(np.arange(-3.0, 3.01, 0.78)):
            shade = 0.93 + 0.025 * (i % 4)
            faces += _box(center(float(t), 0.0, 0.51), along, up, across,
                          (0.72, 0.09, 1.28), tuple(c * shade for c in board))
        for t in (-2.45, -0.35, 1.75, 2.85):
            for s in (-0.53, 0.53):
                faces += _box(center(t, s, -0.46), along, up, across,
                              (0.16, 1.94, 0.16), wood)
        for s in (-0.53, 0.53):
            faces += _box(center(0.15, s, 0.40), along, up, across,
                          (5.45, 0.13, 0.11), edge)
        # A small bank-side marker and a stone approach path.
        faces += _box(center(-2.30, -0.92, 1.23), along, up, across,
                      (0.12, 0.76, 1.06), (0.23, 0.30, 0.24))
        faces += _box(center(-2.30, -0.92, 1.24), along, up, across,
                      (0.135, 0.07, 0.79), (0.83, 0.78, 0.63))
        for t in (-4.05, -3.62, -3.19, -2.76):
            faces += _box(center(t, -1.12, 0.13), along, up, across,
                          (0.34, 0.08, 0.72), (0.42, 0.42, 0.38))
        return faces

    def _place_props(self) -> list[Prop]:
        if self.id=="cedar":
            return self._cedar_props()
        rng = np.random.default_rng(7)
        props: list[Prop] = []

        def too_close(x, z, limit) -> bool:
            for p in props:
                if (p.x - x) ** 2 + (p.z - z) ** 2 < limit * limit:
                    return True
            return False

        def on_pad(x, z) -> bool:
            a, s = self.slip.local(x, z)
            return bool((-4.0 < float(a) < 30.0) and (abs(float(s)) < 20.0))

        def add(kind, x, z, h, shade, limit):
            if on_pad(x, z) or too_close(x, z, limit):
                return False
            sd = float(shore_sd(x, z))
            if kind == "knee":
                if sd >= -0.4:
                    return False
            elif kind == "reed":
                if sd >= -0.5 or sd < -7.5:
                    return False
            elif sd < 1.5:
                return False
            props.append(Prop(kind, x, z, h, shade))
            return True

        # Eastern treeline, the thing you see from the landing at dawn.
        for i in range(46):
            theta = -0.75 + 1.55 * (i / 45.0)
            extra = 6.0 + (i % 5) * 3.2
            x, z = shore_xy(theta, extra)
            kind = "cypress" if extra < 16 or i % 4 else "oak"
            h = 16.0 + (i % 5) * 1.3 if kind == "cypress" else 10.0
            add(kind, x, z, h, 0.82 + (i % 4) * 0.05, 5.0)

        for i in range(1100):
            theta = float(rng.uniform(-math.pi, math.pi))
            if abs(theta - DOCK_THETA) < 0.28:
                continue
            extra = float(rng.uniform(5.0, 34.0))
            x, z = shore_xy(theta, extra)
            t = (theta + math.pi) % (2 * math.pi) - math.pi
            if abs(t) < 0.95 and extra < 20:
                kind = "cypress" if rng.random() < 0.7 else "oak"
            elif -2.05 < t < -0.85:
                kind = "pine" if rng.random() < 0.65 else "oak"
            else:
                kind = "pine" if rng.random() < 0.55 else "oak"
            if kind == "cypress":
                h = float(rng.uniform(14.0, 20.0))
            elif kind == "pine":
                h = float(rng.uniform(10.0, 16.0))
            else:
                h = float(rng.uniform(8.0, 12.5))
            add(kind, x, z, h, float(rng.uniform(0.78, 1.05)), 6.5)
            if sum(1 for p in props if p.kind in ("pine", "oak", "cypress")) >= 330:
                break

        # A second forest layer gives the bank a continuous, varied silhouette.
        # Deterministic placements and a fixed count keep storage bounded.
        for i in range(460):
            theta = float(rng.uniform(-math.pi, math.pi))
            extra = rng.uniform(38.0,135.0) if i<260 else rng.uniform(140.0,320.0)
            x, z = shore_xy(theta, float(extra))
            kind = "oak" if rng.random() < 0.45 else "pine"
            add(kind, x, z, float(rng.uniform(12.0, 23.0)),
                float(rng.uniform(0.75, 1.0)), 9.0)

        for i in range(16):
            theta = float(rng.uniform(-2.1, -0.8))
            x, z = shore_xy(theta, float(rng.uniform(2.0, 12.0)))
            add("rock", x, z, float(rng.uniform(0.7, 1.6)), float(rng.uniform(0.7, 1.0)), 5.0)

        for i in range(10):
            theta = float(rng.uniform(-math.pi, math.pi))
            x, z = shore_xy(theta, float(rng.uniform(3.0, 14.0)))
            add("stump", x, z, float(rng.uniform(0.9, 1.5)), 0.9, 6.0)

        # Cypress knees in the east shallows.
        for i in range(18):
            theta = float(rng.uniform(-0.45, 0.55))
            x, z = shore_xy(theta, float(rng.uniform(-7.0, -1.2)))
            add("knee", x, z, float(rng.uniform(0.7, 1.3)), 0.85, 3.5)

        for i in range(48):
            theta = float(rng.uniform(-math.pi, math.pi))
            x, z = shore_xy(theta, float(rng.uniform(-7.0, -1.2)))
            add("reed", x, z, float(rng.uniform(1.6, 2.4)), 0.95, 4.0)

        return props

    def _cedar_props(self):
        rng = np.random.default_rng(152)
        props = []
        for i in range(2800):
            x,z,nx,nz = self.coast[int(rng.integers(len(self.coast)))]
            distance = float(rng.uniform(5,32) if i<2100 else rng.uniform(36,155))
            x,z = float(x+nx*distance),float(z+nz*distance)
            a,s = self.slip.local(x,z)
            if -8<float(a)<35 and abs(float(s))<22:
                continue
            if float(self.shore_sd(x,z))<2:
                continue
            kind = "oak" if rng.random()<0.7 else "pine"
            props.append(Prop(kind,x,z,float(rng.uniform(10,22)),float(rng.uniform(0.78,1.02))))
        # Denser groves around the fishing coves and the landing make nearby
        # banks feel inhabited without loading an unbounded reservoir forest.
        targets = [(self.slip.ox,self.slip.oz),*[(row[1],row[2]) for row in self.zones]]
        for tx,tz in targets:
            nearby = np.flatnonzero(np.hypot(self.coast[:,0]-tx,self.coast[:,1]-tz)<280)
            for _ in range(100):
                if not len(nearby):
                    break
                x,z,nx,nz = self.coast[int(rng.choice(nearby))]
                distance = float(rng.uniform(8,95))
                x,z = float(x+nx*distance),float(z+nz*distance)
                a,s = self.slip.local(x,z)
                if (-8<float(a)<35 and abs(float(s))<22) or float(self.shore_sd(x,z))<2:
                    continue
                props.append(Prop("oak" if rng.random()<0.75 else "pine",x,z,
                                  float(rng.uniform(11,21)),float(rng.uniform(0.78,1.02))))
        for i in range(80):
            x,z,nx,nz = self.coast[int(rng.integers(len(self.coast)))]
            distance = -float(rng.uniform(2,5)) if i<40 else float(rng.uniform(3,12))
            x,z = float(x+nx*distance),float(z+nz*distance)
            if math.hypot(x-self.slip.ox,z-self.slip.oz)<45:
                continue
            kind = "reed" if i<40 else "rock"
            props.append(Prop(kind,x,z,float(rng.uniform(0.8,2.1)),0.9))
        # Trinidad Cove's quieter west bank has cypress shade, limestone and reeds.
        props.extend([
            Prop("cypress", 173.8, -866.7, 17.0, 0.88),
            Prop("cypress", 170.4, -860.0, 15.5, 0.91),
            Prop("oak", 176.6, -851.6, 12.5, 0.85),
            Prop("reed", 184.0, -861.0, 1.9, 0.92),
            Prop("reed", 187.0, -862.1, 1.7, 0.86),
            Prop("reed", 191.4, -859.7, 1.8, 0.90),
            Prop("rock", 180.2, -861.8, 1.2, 0.88),
            Prop("rock", 178.7, -856.1, 1.0, 0.82),
        ])
        return props

    def _bake_map(self):
        w, h = 360, 240
        x0,z0,x1,z1 = self.bounds
        if self.id=="cedar":
            h = int(w*(z1-z0)/(x1-x0))
        xs = np.linspace(x0,x1,w,dtype=np.float32)
        zs = np.linspace(z1,z0,h,dtype=np.float32)  # row 0 is north
        x, z = np.meshgrid(xs, zs)
        sd = self.shore_sd(x, z)
        water = (sd < 0) | self.slip.contains(x, z)
        dep = self.depth(x, z)
        ids = self.zone_ids(x, z)
        # Muted chart colors, darker with depth.
        palette = np.array([
            [78, 64, 40],    # landing
            [28, 58, 62],    # inlet
            [56, 86, 52],    # flats
            [36, 74, 48],    # lilies
            [30, 58, 44],    # cypress
            [48, 52, 44],    # rocks
            [14, 32, 48],    # deep
            [20, 48, 56],    # open
            [42, 82, 48],    # reeds
            [42, 72, 90],    # springs
            [52, 42, 94],    # current
        ], dtype=np.float32)
        col = palette[ids]
        shade = np.clip(1.05 - dep / 16.0, 0.45, 1.05)
        col = col * np.where(water, shade, np.float32(1.0))[..., None]
        land = np.array([34, 48, 30], dtype=np.float32)
        sand = np.array([92, 78, 52], dtype=np.float32)
        if self.placeholder:
            col = col * 0.35 + np.array(self.palette["water"], np.float32) * 255 * 0.65
            land = np.array(self.palette["land"], np.float32) * 255
            sand = land * 1.15
        bank = (sd >= 0) & (sd < 8)
        rgb = np.where(water[..., None], col, land)
        rgb = np.where(bank[..., None] & ~water[..., None], sand, rgb)
        # Thin sounding contours turn the map into a useful lake chart.
        contour = (np.abs(dep/2.0-np.round(dep/2.0))<0.025)&water
        rgb = np.where(contour[...,None],rgb*0.72,rgb)
        rgb = np.clip(rgb, 0, 255).astype(np.uint8)
        small = rgb[::2, ::2].copy()
        return rgb, small

    def map_pixel(self, x: float, z: float, w: int, h: int) -> tuple[int, int]:
        x0,z0,x1,z1 = self.bounds
        u = int((x-x0)/(x1-x0)*(w-1))
        v = int((z1-z)/(z1-z0)*(h-1))
        return u, v


# Module-level convenience for tests and data that don't need the grids.
def zone_label(zone: str, lake_id="briar") -> str:
    return LAKE_ZONE_NAMES.get(lake_id, ZONE_NAME).get(zone, zone)
