"""Small CPU framebuffer used when OpenGL is unavailable.

The lake is a heightfield ray march plus a shaded water plane. The jon boat,
the landing, and the trees are a handful of triangles and sprites on top.
The default is 480×270 in full color, smoothly upscaled by the window.
"""

from __future__ import annotations

import math

import numpy as np

from .camera import Camera
from .data import ZONE_ORDER, paint_rgb
from .raster import blit_sprite, clip_near, raster_tri
from .sprites import bake
from .world import Face, World, hash21, noise2
from .boat import HULL_BOW, HULL_STERN, HULL_HALF_BEAM, HULL_INNER_BEAM, wake_along
from .weather import lighting_at
from . import comfort

VIEW_W = 360
VIEW_H = 270
FOV = math.radians(74.0)
BASE_PITCH = -0.055

_BAYER = np.array(
    [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]],
    dtype=np.float32,
) / 16.0

_ZONE_TINT = np.array([
    [1.04, 0.98, 0.86],  # landing
    [0.86, 1.00, 0.96],  # inlet
    [1.16, 1.08, 0.72],  # flats
    [0.82, 1.16, 0.78],  # lilies
    [1.08, 0.94, 0.68],  # cypress
    [0.78, 0.96, 1.08],  # rocks
    [0.68, 0.88, 1.08],  # deep
    [0.92, 1.00, 1.02],  # open
    [0.88, 1.12, 0.76],  # reeds
    [0.88, 0.98, 1.12],  # springs
    [1.08, 0.86, 1.14],  # current
], dtype=np.float32)

_LILY = ZONE_ORDER.index("lilies")


def _legacy_birds_visible(light: dict) -> bool:
    return light["night"] < 0.65 and light["rain"] < 0.8


def sky_color(dx, dy, dz, light: dict) -> np.ndarray:
    inv = 1.0 / np.maximum(np.sqrt(dx * dx + dy * dy + dz * dz), 1e-6)
    dx, dy, dz = dx * inv, dy * inv, dz * inv
    t = np.clip(dy * 0.85 + 0.08, 0.0, 1.0)[..., None]
    col = light["horizon"] * (1.0 - t) + light["zenith"] * t
    band = np.exp(-((dy - 0.02) ** 2) / 0.02) * light["gold"]
    col = col + np.array([0.55, 0.22, 0.05], np.float32) * band[..., None]
    sun = light["sun"]
    sdot = dx * sun[0] + dy * sun[1] + dz * sun[2]
    glow = np.exp((sdot - 1.0) * 26.0) * light["sun_i"]
    disc = np.clip((sdot - 0.99915) / 0.00085, 0.0, 1.0) * light["sun_i"]
    col = col + np.array([1.0, 0.95, 0.82], np.float32) * (glow * 0.75 + disc)[..., None]
    moon = light["moon"]
    mdot = dx * moon[0] + dy * moon[1] + dz * moon[2]
    mdisc = np.clip((mdot - 0.99945) / 0.00055, 0.0, 1.0) * light["moon_i"]
    col = col + np.array([0.82, 0.86, 0.95], np.float32) * (mdisc * 1.4)[..., None]
    return np.clip(col, 0.0, 1.0).astype(np.float32)


def _reflect_sky(rx, ry, rz, light: dict) -> np.ndarray:
    """A cheaper sky for water. The specular highlight carries the sun."""
    t = np.clip(ry * 0.85 + 0.08, 0.0, 1.0)[..., None]
    col = light["horizon"] * (1.0 - t) + light["zenith"] * t
    sun = light["sun"]
    sdot = rx * float(sun[0]) + ry * float(sun[1]) + rz * float(sun[2])
    glow = np.exp((sdot - 1.0) * 14.0) * light["sun_i"]
    col = col + np.array([1.0, 0.86, 0.62], np.float32) * glow[..., None] * 0.75
    return col


def _fbm(x, z):
    a = np.float32(0.55)
    f = np.float32(1.0)
    total = np.zeros_like(_as_f(x))
    amp = 0.0
    for _ in range(2):
        total = total + a * noise2(x * f, z * f)
        amp += a
        a *= 0.5
        f *= 2.1
    return total / amp


def _as_f(x):
    return np.asarray(x, dtype=np.float32)


class SoftwareRenderer:
    def __init__(self, world: World, width=480, height=270):
        self.world = world
        self.h = int(height)
        self.w = int(width)
        self.backend = "CPU fallback"
        self.col = np.zeros((self.h, self.w, 3), dtype=np.float32)
        self.z = np.full((self.h, self.w), 1e6, dtype=np.float32)
        tile = np.tile(_BAYER, (self.h // 4 + 1, self.w // 4 + 1))[: self.h, : self.w]
        self.bayer = tile
        # Leafy parts take this lake's palette, as the GL atlas does (sprites.sprite_hd, forest.tree_hd).
        self.sprites = bake(paint_rgb("buoy", "orange"), lake=world.id)
        self._buoy_id = "orange"
        if world.nebula:
            from .nebula import lane_circles
            from .sprites import nebula_sprites
            self.sprites.update(nebula_sprites())
            self._lanes = lane_circles(world)
        else:
            # Trees the baked set lacks take this lake's palette, as the GL atlas does (forest.tree_hd).
            from .forest import TREE_KINDS, tree
            placed = {prop.kind for prop in world.props} & set(TREE_KINDS)
            kinds = sorted(kind for kind in placed if kind not in self.sprites)
            if "larch" in placed:
                kinds.append("larchgold")
            self.sprites.update({kind: tree(kind, 0, lake=world.id) for kind in kinds})
        self.last_ms = 0.0
        self.splashes: list[tuple[float, float, float]] = []
        px = np.array([p.x for p in world.props],np.float32)
        pz = np.array([p.z for p in world.props],np.float32)
        gy = world.sample_height(px,pz)
        from .sprites import WATERLINE_KINDS
        wet = np.array([p.kind in WATERLINE_KINDS for p in world.props])
        self.prop_positions = np.stack([px,np.where(wet,0,gy),pz],axis=1)
        from .actors import ActorCache
        self.actor_cache = ActorCache(world)
        self._actor_paint: dict = {}
        from .skipperview import SkipperFigure
        self.skipper = SkipperFigure()
        self._skipper_paint = None  # (mesh, (rgb, glow)) of the look last drawn

    def _actors(self, cam, state, light):
        """Resident cats as Gouraud-lit meshes over the frame, their boats as faces (V1-29)."""
        from .actors import LOD1_RANGE, pose_state, roster
        from .catmesh import LOD0, LOD1, paint
        actors = self.actor_cache.sync(getattr(state, "npcs", ()) or (), roster())
        live = {(actor.npc_id, lod) for actor in actors for lod in (LOD0, LOD1)}
        for key in [key for key in self._actor_paint if key not in live]:
            del self._actor_paint[key]
        reduced = bool(state.v2.get("settings", {}).get("reduced_motion", False))
        for actor in actors:
            distance = math.hypot(actor.x - cam.x, actor.z - cam.z)
            # _faces culls past 170 m face by face; a whole boat that far is skipped at once.
            if distance < 180.0:
                self._faces(cam, actor.boat_faces, light, boat=False)
            if distance > LOD1_RANGE:
                continue
            lod = LOD0 if distance < 12.0 else LOD1
            mesh = actor.mesh(lod)
            if (actor.npc_id, lod) not in self._actor_paint:
                self._actor_paint[actor.npc_id, lod] = paint(mesh)
            self._cat(cam, actor, mesh, self._actor_paint[actor.npc_id, lod],
                      pose_state(actor, state.x, state.z, state.anim, reduced), distance, state, light)

    def _skipper(self, cam, state, light):
        """The Skipper's own rig at the helm, for views off the eye (skipperview.SkipperFigure)."""
        from .catmesh import LOD0, paint
        actor = self.skipper.place(state, cam.boat)
        mesh = actor.mesh(LOD0)
        if self._skipper_paint is None or self._skipper_paint[0] is not mesh:
            self._skipper_paint = (mesh, paint(mesh))
        reduced = bool(state.v2.get("settings", {}).get("reduced_motion", False))
        distance = math.hypot(actor.x - cam.x, actor.z - cam.z)
        self._cat(cam, actor, mesh, self._skipper_paint[1], self.skipper.params(state, reduced), distance, state,
                  light)

    def _cat(self, cam, actor, mesh, painted, params, distance, state, light):
        """One posed cat mesh, Gouraud-lit as cat.frag lights it, depth-tested into the frame."""
        from .actors import animate
        from .raster import cover
        rgb, glow = painted
        sun = np.asarray(light["sun"], np.float32)
        amb = 0.70 + (0.18 - 0.70) * light["night"] + light["moon_i"] * 0.17 + light.get("starlight", 0.0) * light["night"] * 0.22
        warm = np.asarray((1.0, 0.91, 0.73), np.float32) * 0.55 * light["sun_i"]
        rim_c = np.asarray((1.0, 0.82, 0.55), np.float32) * 0.18 * (1.0 - light["night"] * 0.6)
        fog_c = np.asarray(light["horizon"], np.float32)
        pos, nrm = animate(mesh, params)
        world_pts = actor.local_to_world(pos)
        pts = cam.world_to_cam(world_pts)
        if pts[:, 2].max() < 0.25:
            return
        with np.errstate(divide="ignore", invalid="ignore"):
            sx, sy, zz = cam.cam_to_screen(pts)
        pixels, owner, bary, depth = cover(sx, sy, zz, mesh.triangles, self.w, self.h, near=0.22)
        flat_z = self.z.reshape(-1)
        nearer = depth < flat_z[pixels]
        if not nearer.any():
            return
        pixels, owner, bary, depth = pixels[nearer], owner[nearer], bary[nearer], depth[nearer]
        # Light each vertex as cat.frag does, two-sided, then blend across the triangle.
        n = (actor.local_to_world(nrm) - actor.local_to_world(np.zeros((1, 3), np.float32)))
        n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-6)
        view = cam.eye - world_pts
        view /= np.maximum(np.linalg.norm(view, axis=1, keepdims=True), 1e-6)
        facing = (n * view).sum(1, keepdims=True)
        n = np.where(facing < 0, -n, n)
        diffuse = np.clip(n @ sun, 0.0, 1.0)[:, None]
        rim = (1.0 - np.abs(facing)) ** 3
        lit = rgb * (amb + warm * diffuse) + rim_c * rim
        lit = lit + (rgb * 1.15 - lit) * np.clip(glow, 0.0, 1.0)[:, None]
        tri = mesh.triangles[owner]
        colour = (lit[tri[:, 0]] * bary[:, 0:1] + lit[tri[:, 1]] * bary[:, 1:2] + lit[tri[:, 2]] * bary[:, 2:3])
        fog = float(np.clip(1.0 - math.exp(-distance * (1 / 380.0 + light.get("mist", 0.0) / 250.0)), 0.0, 0.82))
        fog *= float(comfort.fog_factor(state, distance))
        colour = colour * (1.0 - fog) + fog_c * fog
        self.col.reshape(-1, 3)[pixels] = np.clip(colour, 0.0, 1.0)
        flat_z[pixels] = depth

    def actor_memory(self) -> dict:
        from .actors import memory_report
        paint = sum(rgb.nbytes + glow.nbytes for rgb, glow in self._actor_paint.values())
        if self._skipper_paint is not None:
            mesh, (rgb, glow) = self._skipper_paint
            paint += mesh.nbytes + rgb.nbytes + glow.nbytes
        return memory_report(self.actor_cache, paint_bytes=paint)

    def _paws(self, cam, state, light):
        """The Skipper's paws in the eye frame, lit like the cockpit faces (V1-29)."""
        from .raster import cover
        from .skipper import paw_mesh
        pos, nrm, rgb, tris = paw_mesh(state, bool(state.v2.get("settings", {}).get("reduced_motion", False)))
        if not len(tris):
            return
        # A mouse-turned view places the paws in its level eye frame, as it does the hull,
        # so they follow yaw and not pitch.
        frame = cam.boat_frame()
        if frame is not cam:
            pos = cam.reframe_points(frame, pos)
        with np.errstate(divide="ignore", invalid="ignore"):
            sx, sy, zz = cam.cam_to_screen(pos)
        pixels, owner, bary, depth = cover(sx, sy, zz, tris, self.w, self.h, near=0.22)
        flat_z = self.z.reshape(-1)
        nearer = depth < flat_z[pixels]
        pixels, owner, bary, depth = pixels[nearer], owner[nearer], bary[nearer], depth[nearer]
        key = np.array([0.18, 0.82, -0.40], np.float32)
        base = 0.60 + 0.28 * (1.0 - light["night"] * 0.40)
        lit = rgb * (base * (0.70 + 0.48 * np.clip(nrm @ key, 0.0, 1.0)))[:, None]
        tri = tris[owner]
        colour = lit[tri[:, 0]] * bary[:, 0:1] + lit[tri[:, 1]] * bary[:, 1:2] + lit[tri[:, 2]] * bary[:, 2:3]
        self.col.reshape(-1, 3)[pixels] = np.clip(colour, 0.0, 1.0)
        flat_z[pixels] = depth

    def _skipper_reflection(self, cam, state, light, water):
        """A soft stamp of the Skipper's mirrored head on calm water at idle (V1-29)."""
        from .raster import cover
        from .skipper import head_silhouette, shows_reflection, silhouette_rgb
        # Off the eye the Skipper stands in the boat, and a floating head beyond the bow would be a second one.
        if cam.boat is not None or not shows_reflection(state, light):
            return
        pos, _nrm, _rgb, tris = head_silhouette(state)
        pts = cam.world_to_cam(pos * np.array((1.0, -1.0, 1.0), np.float32))
        with np.errstate(divide="ignore", invalid="ignore"):
            sx, sy, zz = cam.cam_to_screen(pts)
        pixels = cover(sx, sy, zz, tris, self.w, self.h, near=0.3)[0]
        pixels = pixels[water.reshape(-1)[pixels]]
        col = self.col.reshape(-1, 3)
        col[pixels] = col[pixels] * 0.6 + silhouette_rgb(state) * 0.4

    def _sync_buoy(self, state):
        bid = state.look_paint["buoy"]
        if bid != self._buoy_id:
            self.sprites.update(bake(paint_rgb("buoy", bid)))
            self._buoy_id = bid

    def _hull_faces(self, cam, state) -> list[Face]:
        """The boat's faces in the space `cam` draws them, so the hull and the paws agree.

        Args:
            cam: The view being drawn. A staged or chase view sets ``boat``, which places the
                boat where it floats. A mouse-turned view sets ``hull``, its unturned eye.
            state: The save; its boat and paint choose the faces.

        Returns:
            World-space faces for a staged or chase view (V1-35). Otherwise faces in the view's
            own level eye frame, drawn through the camera-space path the unturned hull takes, so
            a turn of zero changes nothing and a pitch-only turn leaves the boat where it is.
        """
        boat = self._boat_faces(state)
        frame = cam.boat_frame()
        if cam.boat is not None:  # a staged or chase view sees the boat where it floats (V1-35)
            return [Face(frame.eye_to_world(f.pts), frame.eye_to_world(f.normal) - frame.eye,
                         f.color, "world", f.emissive) for f in boat]
        if frame is not cam:  # a mouse-turned view: the hull in its level eye frame, like the paws
            return [Face(cam.reframe_points(frame, f.pts), cam.reframe_dirs(frame, f.normal),
                         f.color, "cam", f.emissive) for f in boat]
        return boat

    def render(self, state, cam: Camera | None = None) -> np.ndarray:
        import time as _time
        t0 = _time.perf_counter()
        self._sync_buoy(state)
        if cam is None:
            cam = self.camera_for(state)
        world = self.world
        light = lighting_at(state.game_minutes + state.minute_acc, state)
        col = self.col
        zbuf = self.z
        zbuf[:] = 1e6
        dirs = cam.dirs
        col[:] = sky_color(dirs[:, :, 0], dirs[:, :, 1], dirs[:, :, 2], light)
        if world.nebula:
            from .nebula import gas_rgb, sky_add
            half = dirs[::2, ::2]
            gas = gas_rgb(half[:, :, 0], half[:, :, 1], half[:, :, 2], light)
            col += gas.repeat(2, axis=0).repeat(2, axis=1)[: self.h, : self.w]
            col += sky_add(dirs[:, :, 0], dirs[:, :, 1], dirs[:, :, 2], light, self._still_anim(state))
        self._add_clouds(dirs, state.anim, light)
        if not world.nebula:
            self._add_stars(dirs, light)

        dy = dirs[:, :, 1]
        t_plane = np.full((self.h, self.w), np.float32(1e6))
        down = dy < -1e-4
        t_plane[down] = np.float32(-cam.y) / dy[down]
        hx = cam.x + dirs[:, :, 0] * t_plane
        hz = cam.z + dirs[:, :, 2] * t_plane
        sd = self.world.shore_sd(hx, hz)
        slip = world.slip.contains(hx, hz)
        water = down & (t_plane < 1400) & ((sd < 0) | slip)
        # The waterline is the shore function itself. Marching that last meter
        # made the bank hop as the step bracket moved.
        close = water & (t_plane < 900)
        if np.any(close):
            self._shade_water(np.flatnonzero(close), hx, hz, t_plane, dirs, state, cam, light)

        march = (dy < (0.55 if world.generated else 0.12)) & ~close & (t_plane > 0.35)
        self._march_and_shade(cam, dirs, march, state, light)
        self._skipper_reflection(cam, state, light, close)

        self._sprites(cam, state, light)
        self._faces(cam, world.faces, light, boat=False)
        self._actors(cam, state, light)
        self._faces(cam, self._hull_faces(cam, state), light, boat=True)
        if cam.boat is None:
            self._paws(cam, state, light)
        else:  # a staged view sees the Skipper standing at the helm, not floating paws
            self._skipper(cam, state, light)
        from .bot import faces as bot_faces
        self._faces(cam, bot_faces(state), light, boat=False)
        from .ambient import faces as ambient_faces
        self._faces(cam, ambient_faces(state,world,light), light, boat=False, two_sided=True)
        if light["rain"] > 0.0:
            self._rain(state.anim, light["rain"])
        if light.get("snow", 0) > 0:
            self._snow(0 if bool(state.v2.get("settings", {}).get("reduced_motion", False)) else state.anim, light["snow"])
        if _legacy_birds_visible(light) and not world.nebula:
            self._birds(cam, state.anim)
        rgb = self._quantize(col)
        self.last_ms = (_time.perf_counter() - t0) * 1000.0
        return rgb

    @staticmethod
    def _still_anim(state):
        """Animation time for twinkles, aurora and dashes; held under Reduced Motion."""
        return 0.0 if bool(state.v2.get("settings", {}).get("reduced_motion", False)) else float(state.anim)

    def camera_for(self, state, yaw=None, pitch=None, x=None, z=None) -> Camera:
        # Keep the horizon locked. Ripples and the wake supply surface motion.
        bob = 0.0
        roll = 0.0
        return Camera(
            state.x if x is None else x,
            state.boat.eye_height + bob,
            state.z if z is None else z,
            state.yaw if yaw is None else yaw,
            BASE_PITCH + state.look if pitch is None else pitch,
            roll,
            FOV,
            self.w,
            self.h,
        )

    def _add_clouds(self, dirs, anim, light):
        cover = light["cloud_cover"]
        d = dirs[::2, ::2]
        dy = d[:, :, 1]
        valid = dy > 0.05
        u = np.zeros(dy.shape, np.float32)
        v = np.zeros(dy.shape, np.float32)
        u[valid] = d[:, :, 0][valid] / dy[valid]
        v[valid] = d[:, :, 2][valid] / dy[valid]
        n = _fbm(u * 0.13 + np.float32(anim * 0.008), v * 0.13)
        cloud = np.clip((n - 0.52) / 0.28, 0.0, 1.0) * np.clip(dy * 4.5, 0.0, 1.0) * cover
        cloud = np.where(valid, cloud, 0.0).astype(np.float32)
        up = cloud.repeat(2, axis=0).repeat(2, axis=1)[: self.h, : self.w]
        white = (np.array([0.93, 0.94, 0.96], np.float32) * (1.0 - light["night"])
                 + np.array([0.11, 0.15, 0.23], np.float32) * light["night"])
        cloudy = np.array([0.50, 0.53, 0.56], np.float32) * (1.0 - 0.75 * light["night"])
        white = white * (1.0 - light["cloud_shade"]) + cloudy * light["cloud_shade"]
        if self.world.nebula:
            # Thin lilac stardust instead of a gray deck, as in common.glsl.
            white = white * 0.35 + np.array([0.62, 0.52, 0.80], np.float32) * (1.0 - light["night"] * 0.62) * 0.65
            cloud = cloud * 0.6
            up = cloud.repeat(2, axis=0).repeat(2, axis=1)[: self.h, : self.w]
        c = up[..., None]
        self.col[:] = self.col * (1.0 - c * 0.72) + white * c

    def _add_stars(self, dirs, light):
        visibility = max(0.0, (light["night"] - 0.25) / 0.75) * (1.0 - light["cloud_shade"])
        if visibility <= 0.0:
            return
        qx = np.floor(dirs[:, :, 0] * 200).astype(np.int64)
        qy = np.floor(dirs[:, :, 1] * 200).astype(np.int64)
        qz = np.floor(dirs[:, :, 2] * 200).astype(np.int64)
        hsh = hash21(qx + qz * 13, qy + 31)
        stars = (hsh > 0.9965) & (dirs[:, :, 1] > 0.08)
        bright = ((hsh - 0.9965) / 0.0035).astype(np.float32)
        add = stars.astype(np.float32) * bright * visibility
        self.col += add[..., None] * np.array([0.85, 0.88, 1.0], np.float32)

    def _march_and_shade(self, cam, dirs, mask, state, light):
        idx = np.flatnonzero(mask)
        if idx.size == 0:
            return
        d = dirs.reshape(-1, 3)[idx]
        n = idx.size
        # Tight steps where a bank can fill the view, then a few for the far ridge.
        ts = np.array(
            [2.0, 4.5, 8.0, 14.0, 24.0, 40.0, 70.0, 120.0, 220.0, 420.0, 780.0],
            dtype=np.float32,
        )
        limit = 1900.0 if self.world.generated else 800.0
        if self.world.generated:
            ts = np.append(ts, np.array([1000, 1200, 1400, 1650, 1890], np.float32))
        lo = np.full(n, np.float32(0.4))
        hi = np.full(n, np.float32(1.0e6))
        px = cam.x + d[:, 0] * lo
        py = cam.y + d[:, 1] * lo
        pz = cam.z + d[:, 2] * lo
        gap_lo = py - self.world.sample_height(px, pz)
        gap_hi = np.zeros(n, np.float32)
        found = gap_lo <= 0.0
        hi = np.where(found, lo, hi)
        for step in ts:
            if bool(np.all(found)):
                break
            t = np.maximum(np.full(n, step, dtype=np.float32), lo + np.float32(0.04))
            py = cam.y + d[:, 1] * t
            px = cam.x + d[:, 0] * t
            pz = cam.z + d[:, 2] * t
            gap = py - self.world.sample_height(px, pz)
            cross = (~found) & (gap_lo > 0.0) & (gap <= 0.0)
            hi = np.where(cross, t, hi)
            gap_hi = np.where(cross, gap, gap_hi)
            still = ~found & ~cross
            lo = np.where(still, t, lo)
            gap_lo = np.where(still, gap, gap_lo)
            found = found | cross
        # Tighten the bracket, then take the secant. Six midpoint cuts on a
        # 6–16 m bracket left a slab of pixels on the near sample, so the
        # bank stood up as a wall and jumped to the next sample as you closed in.
        alive = found & (hi < limit)
        ai = np.flatnonzero(alive & ((hi - lo) > np.float32(0.20)))
        for _ in range(8):
            if ai.size == 0:
                break
            mid = (lo[ai] + hi[ai]) * np.float32(0.5)
            gap = (cam.y + d[ai, 1] * mid) - self.world.sample_height(
                cam.x + d[ai, 0] * mid, cam.z + d[ai, 2] * mid
            )
            above = gap > 0.0
            lo[ai] = np.where(above, mid, lo[ai])
            gap_lo[ai] = np.where(above, gap, gap_lo[ai])
            hi[ai] = np.where(above, hi[ai], mid)
            gap_hi[ai] = np.where(above, gap_hi[ai], gap)
            ai = ai[(hi[ai] - lo[ai]) > np.float32(0.20)]
        span = hi - lo
        denom = gap_lo - gap_hi
        alpha = np.clip(np.where(np.abs(denom) > np.float32(1.0e-4), gap_lo / denom, np.float32(0.5)), 0.0, 1.0)
        guess = np.where(span < np.float32(1.0e-3), lo, lo + span * alpha)
        best = np.where(alive, guess, np.float32(1.0e6))
        hit = best < limit
        if not np.any(hit):
            return
        sel = idx[hit]
        bt = best[hit]
        dd = d[hit]
        hx = cam.x + dd[:, 0] * bt
        hz = cam.z + dd[:, 2] * bt
        hy = cam.y + dd[:, 1] * bt
        hgt = self.world.sample_height(hx, hz)
        sd = self.world.shore_sd(hx, hz)
        slip = self.world.slip.contains(hx, hz)
        is_water = ((sd < 0) | slip) & (hgt < 0.4)
        # Full-frame coordinates for the shaders that sample by flat index.
        # Write via compact arrays instead.
        if np.any(is_water):
            self._shade_water_compact(sel[is_water], hx[is_water], hz[is_water], bt[is_water], dd[is_water], state, cam, light)
        if np.any(~is_water):
            self._shade_terrain(sel[~is_water], hx[~is_water], hy[~is_water], hz[~is_water], bt[~is_water], state, cam, light)

    def _shade_water(self, idx, hx, hz, t_plane, dirs, state, cam, light):
        # Nearby water is shaded per pixel so the chop reads. Far water is a
        # 2×2 block; the dither covers the steps.
        w = self.w
        dist = t_plane.reshape(-1)[idx]
        near = dist < 46.0
        self._shade_subset(idx[near], hx, hz, t_plane, dirs, state, cam, light)
        far = idx[~near]
        if far.size == 0:
            return
        ys = far // w
        xs = far - ys * w
        anchors = far[((ys & 1) == 0) & ((xs & 1) == 0)]
        if anchors.size:
            self._shade_subset(anchors, hx, hz, t_plane, dirs, state, cam, light)
            self._spread_water(anchors, far)
        zflat = self.z.reshape(-1)
        left = far[zflat[far] > 1.0e5]
        if left.size:
            self._shade_subset(left, hx, hz, t_plane, dirs, state, cam, light)

    def _shade_subset(self, idx, hx, hz, t_plane, dirs, state, cam, light):
        if idx.size == 0:
            return
        self._shade_water_compact(
            idx,
            hx.reshape(-1)[idx], hz.reshape(-1)[idx],
            t_plane.reshape(-1)[idx], dirs.reshape(-1, 3)[idx],
            state, cam, light,
        )

    def _spread_water(self, src, water_idx):
        w = self.w
        h = self.h
        mark = np.zeros(h * w, np.bool_)
        mark[water_idx] = True
        col = self.col.reshape(-1, 3)
        z = self.z.reshape(-1)
        sy = src // w
        sx = src - sy * w
        for oy, ox in ((0, 1), (1, 0), (1, 1)):
            ny = sy + oy
            nx = sx + ox
            inside = (ny < h) & (nx < w)
            if not np.any(inside):
                continue
            dst = ny * w + nx
            take = inside.copy()
            take[inside] &= mark[dst[inside]]
            if not np.any(take):
                continue
            col[dst[take]] = col[src[take]]
            z[dst[take]] = z[src[take]]

    def _shade_water_compact(self, idx, hx, hz, dist, dirs, state, cam, light):
        world = self.world
        depth = np.asarray(world.depth(hx, hz), dtype=np.float32).reshape(-1)
        ids = world.zone_ids(hx, hz).reshape(-1)
        tint = _ZONE_TINT[ids]
        t1 = np.clip(depth / 1.35, 0.0, 1.0)[:, None]
        t2 = np.clip((depth - 1.1) / 8.0, 0.0, 1.0)[:, None]
        shallow = np.array([0.32, 0.52, 0.26], np.float32)
        mid = np.array([0.03, 0.30, 0.40], np.float32)
        deep = np.array([0.015, 0.11, 0.20], np.float32)
        body = shallow * (1.0 - t1) + mid * t1
        body = body * (1.0 - t2) + deep * t2
        body *= tint
        if world.placeholder:
            body = body * 0.25 + np.array(world.palette["water"], np.float32) * tint * 0.75
        if world.generated:
            blend = np.clip(depth / 20, 0, 1)[:, None]
            shallow = np.array(world.environment["water_shallow"], np.float32)
            deep = np.array(world.environment["water_deep"], np.float32)
            body = shallow*(1-blend) + deep*blend
        if world.caldera:
            moss = (ids == _LILY)[:,None] * np.clip(1-depth/12,0,1)[:,None]*.65
            body = body*(1-moss) + np.array([.09,.19,.15],np.float32)*moss
        if world.nebula:
            # Teal shallows, violet mid-water, and a starry void bed below 30 m.
            mid = np.array(world.environment["water_mid"], np.float32)
            t1 = np.clip((depth-.5)/6.5, 0, 1)[:, None]
            t2 = np.clip((depth-7)/33, 0, 1)[:, None]
            body = (shallow*(1-t1) + mid*t1)*(1-t2) + deep*t2
            cx, cz = np.floor(hx*.9).astype(np.int64), np.floor(hz*.9).astype(np.int64)
            seed = hash21(cx+31, cz+17)
            point = np.hypot(hx*.9-cx-.5, hz*.9-cz-.5) < .16
            star = (seed > .93) * point * np.clip((depth-6)/24, 0, 1) * np.clip(1-(dist-25)/65, 0, 1)
            body = body + star[:, None]*np.array([.75, .80, 1.0], np.float32)
        # Bottom shows through the skinniest water.
        sand = np.array([0.55, 0.52, 0.66] if world.nebula else [0.55, 0.50, 0.32], np.float32)
        clear = np.clip(depth / 1.1, 0.0, 1.0)[:, None]
        body = sand * (1.0 - clear) * 0.65 + body * (0.35 + 0.65 * clear)
        # Broad patches and a swell, so open water is not one smooth ramp.
        patch = hash21(np.floor(hx / 22.0).astype(np.int64), np.floor(hz / 22.0).astype(np.int64))
        anim = np.float32(state.anim)
        ph1 = hx * np.float32(0.17) + anim * np.float32(0.9)
        ph2 = hz * np.float32(0.13) - anim * np.float32(0.65) + hx * np.float32(0.04)
        crest = np.float32(0.5) + np.float32(0.5) * np.sin(ph1)
        body = body * (0.72 + 0.26 * patch + 0.28 * crest)[:, None]

        from .caldera import reflection_strength
        still = reflection_strength(state, light)
        ripple = light["ripple"]*(1-still*.95)*(.55 if world.nebula else 1)
        amp = np.float32(0.22 * ripple)
        chop = np.sin(hx * np.float32(1.15) + anim * np.float32(2.4)) * np.float32(0.06 * ripple)
        chop *= 1-still*.95
        nx = amp * np.float32(0.46) * np.cos(ph1) + chop
        nz = amp * np.float32(0.32) * np.cos(ph2) + chop * np.float32(0.6)
        ny = np.ones_like(nx)
        ln = np.sqrt(nx * nx + ny * ny + nz * nz)
        nx, ny, nz = nx / ln, ny / ln, nz / ln
        dx, dy, dz = dirs[:, 0], dirs[:, 1], dirs[:, 2]
        nd = nx * dx + ny * dy + nz * dz
        rx = dx - 2 * nd * nx
        ry = dy - 2 * nd * ny
        rz = dz - 2 * nd * nz
        reflected = _reflect_sky(rx, ry, rz, light)
        if world.nebula:
            # The glassy Lagoon mirrors its stars and aurora.
            from .nebula import sky_add
            reflected = reflected + sky_add(rx, ry, rz, light, self._still_anim(state))
        if still>0 and not world.nebula:  # the Lagoon already mirrors its own stars
            full_sky = sky_color(rx,ry,rz,light)
            qx,qy,qz = (np.floor(axis*200).astype(np.int64) for axis in (rx,ry,rz))
            stars = hash21(qx+qz*13,qy+31)
            bright = np.clip((stars-.9965)/.0035,0,1)*(ry>.08)
            if state.lake_id != "crater":  # a legendary's glassy water mirrors no stars by day (V1-37)
                bright = bright*light["night"]
            full_sky += bright[:,None]*np.array([.85,.88,1.0],np.float32)
            reflected = reflected*(1-still) + full_sky*still
        fres = 0.05 + 0.24 * np.power(1.0 - np.clip(-dy, 0.0, 1.0), 3.0)
        fres = np.clip(fres, 0.0, 0.30)
        fres = fres*(1-still) + .94*still
        if world.nebula:
            fres = np.maximum(fres, .42)
        sun = light["sun"]
        sdot = np.clip(rx * sun[0] + ry * sun[1] + rz * sun[2], 0.0, 1.0)
        glitter = (np.sin(ph1 * 1.7) + np.sin(ph2 * 1.4)) > 0.35
        # A tight glitter path and a gentle sheen near the sun's reflection. The old broad
        # sheen (from 44 degrees off) blew whole stretches of water out to white whenever
        # the sun sat low ahead (V1-42).
        spec = (sdot ** 48) * glitter.astype(np.float32) * light["sun_i"] * 0.70
        spec = spec + np.clip((sdot - 0.88) / 0.12, 0.0, 1.0) ** 2 * light["sun_i"] * 0.28
        moon = light["moon"]
        mdot = np.clip(rx * moon[0] + ry * moon[1] + rz * moon[2], 0.0, 1.0)
        spec = spec + (mdot ** 40) * light["moon_i"] * 0.8
        colr = body * (1.0 - fres)[:, None] + reflected * fres[:, None]
        colr = colr + spec[:, None] * np.array([1.0, 0.96, 0.86], np.float32)

        sdv = np.asarray(self.world.shore_sd(hx, hz), dtype=np.float32).reshape(-1)
        slip = self.world.slip.contains(hx, hz)
        # A thin lap line at the bank, as the GL water draws it, and none in the slip. The
        # old band was 7 m wide, added at 72%, so the water round a docked boat swirled
        # white (V1-42).
        foam = np.exp(-((sdv + 0.2) ** 2) * 3.0) * ~slip
        fn = 0.5 + 0.5 * np.sin(hx * 1.7 + anim * 2.1) * np.sin(hz * 1.25 - anim * 1.4)
        lap = (foam * np.clip(fn, 0, 1) * 0.16)[:, None]
        colr = colr * (1.0 - lap) + np.array([0.57, 0.59, 0.47], np.float32) * lap

        cell = np.float32(3.6)
        cell_x = np.floor(hx / cell)
        cell_z = np.floor(hz / cell)
        hsh = hash21(cell_x.astype(np.int64), cell_z.astype(np.int64))
        fx = hx / cell - cell_x - 0.5
        fz = hz / cell - cell_z - 0.5
        r2 = fx * fx + fz * fz
        # Keep the slip and the water at your feet clear. Pads belong in the cove
        # and along skinny shore, and a pad a few meters ahead fills the frame.
        dockx, dockz = self.world.dock
        near_dock = np.hypot(hx - dockx, hz - dockz) < 60.0
        pad = (dist > 24.0) & (~slip) & (~near_dock) & (r2 < 0.11) & (
            ((ids == _LILY) & (hsh > 0.66))
            | ((depth < 1.65) & (sdv < -3.5) & (hsh > 0.84))
        )
        if world.nebula:
            pad &= ids == _LILY
        elif world.generated:
            pad &= (ids == _LILY) & (np.abs(fx) < .075) & (np.abs(fz) < .38)
        if world.caldera:
            pad[:] = False
        rim = pad & (r2 > 0.055)
        green = np.array([0.22, 0.55, 0.16], np.float32)
        leaf = np.array([0.08, 0.30, 0.10], np.float32)
        if world.nebula:
            # Zero-G pads with luminous rims.
            green, leaf = np.array([0.16, 0.38, 0.42], np.float32), np.array([0.42, 0.85, 0.90], np.float32)
        colr = np.where(pad[:, None], green, colr)
        colr = np.where(rim[:, None], leaf, colr)

        colr = self._wake_rope_light(colr, hx, hz, dist, state, cam, light)
        colr = self._rises(colr, hx, hz, state)
        if world.nebula:
            colr = self._nebula_water(colr, hx, hz, sdv, dist, fres, slip, state, light)
        fog_density = (1.0 - light["rain"]) / 820.0 + light["rain"] / 240.0 + light.get("mist", 0.0) / 250.0
        fog = np.clip(1.0 - np.exp(-dist * fog_density), 0.0, 0.72)
        fog *= comfort.fog_factor(state, dist)
        colr = colr * (1.0 - fog)[:, None] + light["horizon"] * fog[:, None]
        # Night keeps the water dark, but not a flat black.
        dim = 0.42 + 0.58 * (1.0 - light["night"]) + light["moon_i"] * 0.20
        if world.nebula:
            dim = 0.62 + 0.38 * (1.0 - light["night"]) + light.get("starlight", 0.0) * 0.12
        colr *= dim
        if state.light and light["night"] > 0.0:
            fx, fz = math.sin(state.yaw), math.cos(state.yaw)
            relx = hx - cam.x
            relz = hz - cam.z
            dd = np.hypot(relx, relz) + 1e-3
            along = (relx * fx + relz * fz) / dd
            # A soft-edged pool that fades by inverse square, matching the GL bow light (V1-42).
            cone = np.clip((along - 0.80) / 0.185, 0.0, 1.0)
            cone = cone * cone * (3.0 - 2.0 * cone)
            fall = np.clip((62.0 - dd) / 32.0, 0.0, 1.0) / (1.0 + dd * dd / 256.0)
            spot = cone * fall * light["night"]
            colr = colr + spot[:, None] * np.array([1.0, 0.90, 0.68], np.float32) * 0.45
        self.col.reshape(-1, 3)[idx] = np.clip(colr, 0.0, 1.0)
        self.z.reshape(-1)[idx] = dist

    def _nebula_water(self, colr, hx, hz, sdv, dist, fres, slip, state, light):
        """Lane glow and flow dashes, luminous banks and aurora glow (CPU)."""
        from .nebula import dashes, lane_strength
        night = light["night"]
        glow = np.exp(-((sdv + .6) ** 2) * 1.2) * .22 * (.5 + .5 * night) * ~slip
        colr = colr + glow[:, None] * np.array([.30, .85, .90], np.float32)
        lane = lane_strength(self._lanes, hx, hz)
        inside = np.flatnonzero(lane > 0)
        if inside.size:
            strength = lane[inside][:, None]
            near = np.clip(1 - (dist[inside] - 40) / 90, 0, 1)
            dash = dashes(hx[inside], hz[inside], self._still_anim(state)) * near
            teal = np.array([.10, .40, .52], np.float32) * (.75 + .25 * (1 - night))
            lit = colr[inside] * (1 - strength * .38) + teal * strength * .38
            lit = lit + np.array([.12, .48, .60], np.float32) * strength * (.10 + .16 * night)
            colr[inside] = lit + (dash[:, None] * strength) * np.array([.70, .97, 1.0], np.float32) * 1.05
        aurora = light.get("aurora", 0.0)
        if aurora > 0:
            colr = colr + (aurora * (.25 + .75 * fres) * .35)[:, None] * np.array([.10, .42, .30], np.float32)
        return colr

    def _rises(self, colr, hx, hz, state):
        # Rings follow anim, same as the GL water shader, and never move depth.
        if hx.size == 0:
            return colr
        anim = float(state.anim)
        bx, bz = float(state.x), float(state.z)
        slip = self.world.slip.contains(hx, hz)
        acc = np.zeros(hx.shape[0], np.float32)
        for i in range(5):
            sx = math.sin((i + 1) * 12.9898) * 43758.5453
            sz = math.sin((i + 1) * 78.233) * 43758.5453
            sx, sz = sx - math.floor(sx), sz - math.floor(sz)
            life = (anim * 0.07 + sx) % 1.0
            cx = bx + (sx * 2.0 - 1.0) * 28.0 + math.sin(anim * 0.15 + i) * 6.0
            cz = bz + (sz * 2.0 - 1.0) * 22.0 + math.cos(anim * 0.11 + i * 1.7) * 6.0
            if math.hypot(cx - bx, cz - bz) < 9.0:
                continue
            rad = life * 2.4
            fade = 1.0 - min(1.0, max(0.0, (life - 0.62) / 0.38))
            d = np.hypot(hx - np.float32(cx), hz - np.float32(cz))
            acc += np.exp(-((d - np.float32(rad)) ** 2) / np.float32(0.085 ** 2)) * np.float32(fade)
        acc = np.clip(acc, 0.0, 0.7) * np.float32(0.5)
        acc = np.where(slip, np.float32(0.0), acc)
        foam = np.array([0.78, 0.84, 0.80], np.float32)
        return colr * (1.0 - acc)[:, None] + foam * acc[:, None]

    def _wake_rope_light(self, colr, hx, hz, dist, state, cam, light):
        fx, fz = math.sin(state.yaw), math.cos(state.yaw)
        rx, rz = math.cos(state.yaw), -math.sin(state.yaw)
        relx = hx - state.x
        relz = hz - state.z
        # Mirrored about the hull's middle when reversing, so the wake trails the travel.
        along = wake_along(relx * fx + relz * fz, state.speed, state.boat)
        side = np.abs(relx * rx + relz * rz)
        behind = -along
        spread = 0.35 + behind * 0.15
        rail = np.exp(-((side - spread) ** 2) / 0.08)
        wake = rail * (behind > 0.4) * (behind < 6.0 + abs(state.speed) * 2.5) * min(1.0, abs(state.speed) / 1.5)
        colr = colr + wake.astype(np.float32)[:, None] * np.array([0.65, 0.70, 0.68], np.float32) * 0.55

        for line in state.lines:
            # Distance from hit to the segment, vectorized.
            abx = line.x1 - line.x0
            abz = line.z1 - line.z0
            apx = hx - line.x0
            apz = hz - line.z0
            ab2 = abx * abx + abz * abz + 1e-6
            tt = np.clip((apx * abx + apz * abz) / ab2, 0.0, 1.0)
            d = np.hypot(hx - (line.x0 + abx * tt), hz - (line.z0 + abz * tt))
            rope = np.clip(1.0 - d / 0.18, 0.0, 1.0) * (dist < 90)
            colr = colr * (1.0 - rope * 0.45)[:, None] + np.array([0.05, 0.07, 0.05], np.float32) * rope[:, None]
            if line.fish_on():
                travel = 0.5 + 0.5 * np.sin(tt * np.float32(16.0) - np.float32(state.anim) * np.float32(2.4))
                glow = np.exp(-(d * d) / np.float32(0.22)) * (dist < 90)
                glow = glow * (np.float32(0.25) + np.float32(0.75) * travel) * np.float32(0.18)
                colr = colr + glow.astype(np.float32)[:, None] * np.array([0.72, 0.58, 0.24], np.float32)

        rises = list(self.splashes)
        bite_age = float(state.anim) - float(state.splash_anim)
        if 0.0 <= bite_age <= 2.4:
            rises.append((state.splash_x, state.splash_z, state.splash_anim))
        for sx, sz, born in rises:
            age = state.anim - born
            if age < 0 or age > 2.4:
                continue
            radius = 0.4 + age * 2.4
            d = np.hypot(hx - sx, hz - sz)
            ring = np.exp(-((d - radius) ** 2) / 0.25) * max(0.0, 1.0 - age / 2.4)
            colr = colr + ring.astype(np.float32)[:, None] * 0.35

        lx, lz = self.world.slip.world(12.4, 2.4)
        lamp = np.exp(-np.hypot(hx - lx, hz - lz) / 24.0) * (0.20 + 0.80 * light["night"])
        colr = colr + lamp.astype(np.float32)[:, None] * np.array([1.0, 0.72, 0.40], np.float32) * 0.28
        return colr

    def _shade_terrain(self, idx, hx, hy, hz, dist, state, cam, light):
        world = self.world
        sdv = np.asarray(self.world.shore_sd(hx, hz), dtype=np.float32).reshape(-1)
        h = np.asarray(hy, dtype=np.float32)  # noqa: F841 — hit height comes from the ray
        # Use the baked height so banks that the ray entered match the mesh.
        h = world.sample_height(hx, hz)
        hL = world.sample_height(hx - 2.5, hz)
        hR = world.sample_height(hx + 2.5, hz)
        hD = world.sample_height(hx, hz - 2.5)
        hU = world.sample_height(hx, hz + 2.5)
        nx = hL - hR
        nz = hD - hU
        ny = np.full_like(nx, np.float32(5.0))
        ln = np.sqrt(nx * nx + ny * ny + nz * nz) + 1e-6
        sun = light["sun"]
        ndotl = np.clip((nx * sun[0] + ny * sun[1] + nz * sun[2]) / ln, 0.0, 1.0)
        ambient = 0.16 + 0.50 * (1.0 - light["night"]) + light["moon_i"] * 0.35
        lit = ambient + ndotl * light["sun_i"] * 0.8
        nse = hash21(np.floor(hx / 5).astype(np.int64), np.floor(hz / 5).astype(np.int64))
        grass = np.array([0.30, 0.50, 0.18], np.float32)
        grass2 = np.array([0.16, 0.34, 0.12], np.float32)
        mud = np.array([0.42, 0.32, 0.18], np.float32)
        rock = np.array([0.46, 0.44, 0.40], np.float32)
        sand = np.array([0.72, 0.62, 0.40], np.float32)
        g = grass * (1.0 - nse)[:, None] + grass2 * nse[:, None]
        shore_t = np.clip((sdv - 1.5) / 10.0, 0.0, 1.0)[:, None]
        low = mud * (1.0 - shore_t) + g * shore_t
        high = np.clip((h - 9.0) / 18.0, 0.0, 1.0)[:, None]
        colr = low * (1.0 - high) + rock * high
        sand_m = (sdv > -0.3) & (sdv < 7.0) & (h < 1.8)
        colr = np.where(sand_m[:, None], sand * (0.85 + 0.15 * nse[:, None]), colr)
        if world.generated:
            gravel = np.array([.49, .50, .46], np.float32)
            meadow = np.array([.24, .34, .24], np.float32)
            alpine_rock = np.array([.37, .42, .44], np.float32)
            bank = gravel*(1-shore_t) + meadow*shore_t
            rocky = np.clip((h-18)/65, 0, 1)[:, None]
            colr = bank*(1-rocky) + alpine_rock*rocky
            snow = np.clip((h-world.environment["snow_line"]+nse*24)/26, 0, 1)[:, None]
            colr = colr*(1-snow) + np.array([.84,.89,.91], np.float32)*snow
        if world.caldera:
            ash = np.array([.42,.43,.46],np.float32)
            basalt = np.array([.16,.18,.23],np.float32)
            colr = ash*(1-nse[:,None]) + basalt*nse[:,None]
            # Caldera walls in horizontal strata: 1.6 m bands that shift every 40 m along
            # the rim, so a cliff reads as layered rock, not grey columns (V1-42).
            steep = (1.0 - np.clip((ny / ln - 0.45) / 0.40, 0.0, 1.0))[:, None]
            band = hash21(np.floor(h / 1.6).astype(np.int64),
                          np.floor((hx - hz) / 40.0).astype(np.int64))[:, None]
            rock = (np.array([.27,.25,.26],np.float32)*(1-band)
                    + np.array([.53,.49,.45],np.float32)*band)
            colr = colr*(1-steep) + rock*steep
            cx,cz,rx,rz,_height = world.environment['islands'][0]
            island = (hx-cx)**2/rx**2 + (hz-cz)**2/rz**2 < 1.3
            colr = np.where(island[:,None],np.array([.07,.08,.12],np.float32)*(1+nse[:,None]*.45),colr)
            _,mx,mz,_radius = next(row for row in world.zones if row[0]=="lilies")
            moss = np.hypot(hx-mx,hz-mz)<110
            colr = np.where((moss & (sdv<30))[:,None],np.array([.14,.28,.19],np.float32),colr)
        if world.nebula:
            # Pale stardust beaches, violet dunes and floating lily drifts.
            dust = (np.array([.26,.22,.36],np.float32)*(1-nse[:,None])
                    + np.array([.44,.38,.56],np.float32)*nse[:,None])
            colr = np.array([.55,.52,.66],np.float32)*(1-shore_t) + dust*shore_t
            ridge = np.clip((h-30)/60,0,1)[:,None]
            colr = colr*(1-ridge) + np.array([.62,.56,.80],np.float32)*ridge
            for cx,cz,rx,rz in world.environment["drifts"]:
                mat = ((hx-cx)/rx)**2 + ((hz-cz)/rz)**2 < 1.1
                colr = np.where(mat[:,None],np.array([.12,.36,.34],np.float32)*(1+nse[:,None]*.6),colr)
            lit = lit + light.get("starlight",0.0)*light["night"]*.30
        # Shade under the treeline so the bank is not one flat stripe.
        canopy = np.clip((sdv - 2.0) / 5.0, 0.0, 1.0) * np.clip((16.0 - sdv) / 8.0, 0.0, 1.0)
        if not world.nebula:
            colr = colr * (1.0 - 0.32 * canopy)[:, None]
        colr = colr * lit[:, None]
        if state.light and light["night"] > 0.0:
            fx, fz = math.sin(state.yaw), math.cos(state.yaw)
            relx = hx - cam.x
            relz = hz - cam.z
            dd = np.hypot(relx, relz) + 1e-3
            along = (relx * fx + relz * fz) / dd
            cone = np.clip((along - 0.78) / 0.20, 0.0, 1.0)
            cone = cone * cone * (3.0 - 2.0 * cone)
            fall = np.clip((62.0 - dd) / 32.0, 0.0, 1.0) / (1.0 + dd * dd / 256.0)
            colr = colr + (cone * fall * light["night"])[:, None] * np.array([0.45, 0.38, 0.24], np.float32)
        fog_density = (1.0 - light["rain"]) / 480.0 + light["rain"] / 220.0 + light.get("mist", 0.0) / 250.0
        if world.caldera:
            mist = light.get("mist",0)
            fog_density *= .35+.65*np.exp(-np.maximum(h,0)/(12+mist*35))
        fog = np.clip(1.0 - np.exp(-dist * fog_density), 0.0, 1.0)
        fog *= comfort.fog_factor(state, dist)
        colr = colr * (1.0 - fog)[:, None] + light["horizon"] * fog[:, None]
        self.col.reshape(-1, 3)[idx] = np.clip(colr, 0.0, 1.0)
        self.z.reshape(-1)[idx] = dist

    def _sprites(self, cam, state, light):
        sun = light["sun"]
        ambient = 0.22 + 0.70 * (1.0 - light["night"]) + light["moon_i"] * 0.4
        fog_c = light["horizon"]
        items = []
        from .forest import TREE_KINDS
        from .lakegen import larch_gold
        gold = self.world.generated and larch_gold(state)
        pts = cam.world_to_cam(self.prop_positions)
        front = np.flatnonzero(pts[:,2]>0.3)
        sx_all,sy_all,zz_all = cam.cam_to_screen(pts[front])
        for i,sx,sy,zz in zip(front,sx_all,sy_all,zz_all):
            prop = self.world.props[i]
            if zz > 750 or sx < -80 or sx > self.w + 80:
                continue
            tree = prop.kind in TREE_KINDS
            kind = prop.kind
            if kind == "larch":
                kind = "larchgold" if gold else kind
            items.append((zz, kind, prop.x, prop.z, prop.h, prop.shade, sx, sy, tree))
        sprite_name = "buoy_flag"
        for line in state.lines:
            kind = sprite_name if line.fish_on() else "buoy"
            for bx, bz in line.buoys():
                hit = cam.project_world(bx, 0.0, bz)
                if hit is None:
                    continue
                sx, sy, zz = hit
                items.append((zz, kind, bx, bz, 0.62, 1.0, sx, sy, False))
        cork_pts = []
        cork_meta = []
        for line in state.lines:
            for i, hook in enumerate(line.hooks):
                if hook.catch is None and not hook.baited:
                    continue
                x, z = line.point_at(i)
                if (x - cam.x) ** 2 + (z - cam.z) ** 2 > 110.0 ** 2:
                    continue
                bob = math.sin(state.anim * 1.7 + x * 0.3 + i) * 0.018
                cork_pts.append((x, bob, z))
                fish = hook.catch is not None
                cork_meta.append(("buoy_flag" if fish else "buoy", 0.42 if fish else 0.20))
                if len(cork_pts) >= 192:
                    break
        if cork_pts:
            cam_pts = cam.world_to_cam(np.array(cork_pts, np.float32))
            sx_all, sy_all, zz_all = cam.cam_to_screen(cam_pts)
            for (kind, height), sx, sy, zz in zip(cork_meta, sx_all, sy_all, zz_all):
                if zz < 0.3 or sx < -40 or sx > self.w + 40:
                    continue
                items.append((float(zz), kind, 0.0, 0.0, height, 1.0, float(sx), float(sy), False))
        items.sort(key=lambda it: -it[0])
        fx = float(sun[0])
        fy = float(sun[1])
        fz = float(sun[2])
        for zz, kind, x, z, height, shade, sx, sy, tree in items:
            dest_h = (height / max(zz, 0.4)) / cam.tany * 0.5 * self.h
            if tree:
                vx, vy, vz = x - cam.x, height * 0.45 - cam.y, z - cam.z
                vl = math.sqrt(vx * vx + vy * vy + vz * vz) + 1e-6
                back = max(0.0, (vx / vl) * fx + (vy / vl) * fy + (vz / vl) * fz) * light["sun_i"]
                tint_v = shade * ambient * (1.0 - 0.20 * back)
                dest_h *= 1.55
            else:
                tint_v = max(ambient, 0.45)
                if shade >= 1.5:
                    # A self-lit Nebula crystal: shade - 2 is its emission.
                    tint_v = max(ambient, 0.45) + (shade - 2.0) * (0.35 + 0.85 * light["night"])
            tint = np.array([tint_v, tint_v, tint_v], np.float32)
            fog = float(np.clip(1.0 - math.exp(-zz * (1 / 380.0 + light.get("mist", 0.0) / 250.0)), 0.0, 0.82))
            fog *= float(comfort.fog_factor(state, zz))
            if kind in ("buoy", "buoy_flag") and comfort.has_buff(state, "glow_buoys"):
                tint = np.maximum(tint, np.array([1.3, 1.15, .85], np.float32))
                fog *= .35
            blit_sprite(self.col, self.z, self.sprites[kind], sx, sy, zz, int(dest_h), tint, fog, fog_c)

    def _faces(self, cam, faces: list[Face], light, boat: bool, two_sided: bool = False):
        sun = light["sun"]
        for face in faces:
            if face.space == "world":
                center = face.pts.mean(axis=0)
                delta = center - cam.eye
                if float(delta @ delta) > 170.0 * 170.0:
                    continue
                if not two_sided and float(np.dot(face.normal, -delta)) <= 0.0:
                    continue
                pts = cam.world_to_cam(face.pts)
                ndotl = float(np.clip(np.dot(face.normal, sun), 0.0, 1.0))
                ambient = 0.22 + 0.55 * (1.0 - light["night"]) + light["moon_i"] * 0.3
                lit = ambient + ndotl * light["sun_i"] * 0.85
            else:
                center = face.pts.mean(axis=0)
                if float(np.dot(face.normal, -center)) <= 0.0:
                    continue
                pts = face.pts
                # Light from above and from the eye, so the flat bow is not a black plate.
                key = np.array([0.18, 0.82, -0.40], np.float32)
                ndotl = float(np.clip(np.dot(face.normal, key), 0.0, 1.0))
                base = 0.60 + 0.28 * (1.0 - light["night"] * 0.40)
                lit = base * (0.70 + 0.48 * ndotl)
            poly = clip_near(pts, 0.22)
            if len(poly) < 3:
                continue
            emission = 0.0 if face.emissive is None else face.emissive
            rgb = np.clip(face.color * np.float32(lit + light["night"] * emission * .85), 0.0, 1.0)
            for i in range(1, len(poly) - 1):
                tri = np.stack([poly[0], poly[i], poly[i + 1]])
                sx, sy, zz = cam.cam_to_screen(tri)
                if np.any(zz < 0.2):
                    continue
                raster_tri(self.col, self.z, list(zip(sx, sy)), zz, rgb)

    def _boat_faces(self, state) -> list[Face]:
        """Square-bow jon boat, camera space. Sides stay parallel. The bow is a flat plate."""
        from .boatmesh import boat_faces, glow_hull, outboard_faces, tiller_faces
        if state.boat_id!="jon":
            return glow_hull(state, boat_faces(state))
        hull = np.array(paint_rgb("hull", state.look_paint["hull"]), np.float32)
        deck = np.array(paint_rgb("deck", state.look_paint["deck"]), np.float32)
        till = np.array(paint_rgb("motor", state.look_paint["motor"]), np.float32)
        bare = state.look_paint["hull"] == "aluminum"
        deck_bare = state.look_paint["deck"] == "aluminum"
        rail = np.array([0.76, 0.79, 0.82], np.float32)
        wall = np.array([0.68, 0.72, 0.76], np.float32) if bare else hull * np.float32(0.92)
        floor_c = np.array([0.62, 0.64, 0.66], np.float32) if deck_bare else deck
        bow_c = np.array([0.58, 0.62, 0.66], np.float32) if bare else hull * np.float32(0.82)
        rib = floor_c * np.float32(0.72)
        wood = np.array([0.55, 0.40, 0.24], np.float32)
        beam = HULL_INNER_BEAM
        rail_o = HULL_HALF_BEAM
        fy = -0.96
        gy = -0.50
        z_near = HULL_STERN
        z_bow = HULL_BOW
        deck_start = z_bow-0.46
        seat_half = beam-0.035

        def q(pts, normal, color):
            n = np.array(normal, np.float32)
            n = n / (np.linalg.norm(n) + 1e-8)
            return Face(np.array(pts, np.float32), n, np.array(color, np.float32), "cam")

        faces = [
            # Floor, one rectangle. No taper and no center seam.
            q([(-beam, fy, z_near), (beam, fy, z_near), (beam, fy, z_bow), (-beam, fy, z_bow)], (0, 1, 0), floor_c),
            # Cross ribs.
            q([(-beam + 0.02, fy + 0.02, 1.88), (beam - 0.02, fy + 0.02, 1.88),
               (beam - 0.02, fy + 0.02, 1.96), (-beam + 0.02, fy + 0.02, 1.96)], (0, 1, 0), rib),
            q([(-beam + 0.02, fy + 0.02, 2.08), (beam - 0.02, fy + 0.02, 2.08),
               (beam - 0.02, fy + 0.02, 2.16), (-beam + 0.02, fy + 0.02, 2.16)], (0, 1, 0), rib),
            # Inner walls, parallel the whole way.
            q([(-beam, fy, z_near), (-beam, gy, z_near), (-beam, gy, z_bow), (-beam, fy, z_bow)], (1, 0, 0), wall),
            q([(beam, fy, z_near), (beam, fy, z_bow), (beam, gy, z_bow), (beam, gy, z_near)], (-1, 0, 0), wall),
            # Exterior skins continue below the waterline. Separate inner and
            # outer faces give the rails real thickness and seal the hull.
            q([(-rail_o,-1.46,z_near),(-rail_o,-1.46,z_bow),(-rail_o,gy,z_bow),(-rail_o,gy,z_near)],(-1,0,0),hull),
            q([(rail_o,-1.46,z_near),(rail_o,gy,z_near),(rail_o,gy,z_bow),(rail_o,-1.46,z_bow)],(1,0,0),hull),
            q([(-rail_o,-1.46,z_bow),(rail_o,-1.46,z_bow),(rail_o,gy,z_bow),(-rail_o,gy,z_bow)],(0,0,1),hull),
            # Flat bow plate. Normal points back at the seat.
            q([(-beam, fy, z_bow), (beam, fy, z_bow), (beam, gy, z_bow), (-beam, gy, z_bow)], (0, 0, -1), bow_c),
            # Rub rail across the bow, so the end reads as a cut plate.
            q([(-beam + 0.04, -0.74, z_bow - 0.012), (beam - 0.04, -0.74, z_bow - 0.012),
               (beam - 0.04, -0.68, z_bow - 0.012), (-beam + 0.04, -0.68, z_bow - 0.012)],
              (0, 0, -1), np.array([0.22, 0.24, 0.26], np.float32)),
            # Front deck, full beam, sitting on the bow.
            q([(-beam, gy, deck_start), (beam, gy, deck_start), (beam, gy, z_bow), (-beam, gy, z_bow)], (0, 1, 0), floor_c * np.float32(1.06)),
            q([(-beam, gy - 0.08, deck_start), (beam, gy - 0.08, deck_start), (beam, gy, deck_start), (-beam, gy, deck_start)],
              (0, 0, -1), bow_c),
            # Gunwales, constant width, closed by a bow rail.
            q([(-rail_o, gy + 0.035, z_near), (-beam + 0.02, gy + 0.035, z_near),
               (-beam + 0.02, gy + 0.035, z_bow), (-rail_o, gy + 0.035, z_bow)], (0, 1, 0), rail),
            q([(beam - 0.02, gy + 0.035, z_near), (rail_o, gy + 0.035, z_near),
               (rail_o, gy + 0.035, z_bow), (beam - 0.02, gy + 0.035, z_bow)], (0, 1, 0), rail),
            q([(-rail_o, gy + 0.045, z_bow - 0.03), (rail_o, gy + 0.045, z_bow - 0.03),
               (rail_o, gy + 0.045, z_bow + 0.02), (-rail_o, gy + 0.045, z_bow + 0.02)], (0, 1, 0), rail),
            q([(-rail_o, gy - 0.01, z_bow + 0.015), (rail_o, gy - 0.01, z_bow + 0.015),
               (rail_o, gy + 0.055, z_bow + 0.015), (-rail_o, gy + 0.055, z_bow + 0.015)], (0, 0, -1), rail),
            # Wooden bench across the cockpit.
            q([(-seat_half, -0.74, 1.70), (seat_half, -0.74, 1.70), (seat_half, -0.74, 1.84), (-seat_half, -0.74, 1.84)], (0, 1, 0), wood),
            q([(-seat_half, -0.80, 1.70), (seat_half, -0.80, 1.70), (seat_half, -0.74, 1.70), (-seat_half, -0.74, 1.70)], (0, 0, -1), wood * 0.8),
        ]
        for z in (0.55,0.96,1.30):
            faces.append(q([(-beam,fy+0.012,z),(beam,fy+0.012,z),
                            (beam,fy+0.012,z+0.038),(-beam,fy+0.012,z+0.038)],
                           (0,1,0),rib))
        grow = 1.0 + state.well_tier * 0.12
        cy0, cy1 = fy, fy + 0.36 * grow
        box = np.array([0.74, 0.77, 0.75], np.float32)
        faces.append(q([(-0.48, cy1, 1.92), (-0.14, cy1, 1.92), (-0.14, cy1, 2.20), (-0.48, cy1, 2.20)], (0, 1, 0), box))
        faces.append(q([(-0.48, cy0, 1.92), (-0.14, cy0, 1.92), (-0.14, cy1, 1.92), (-0.48, cy1, 1.92)], (0, 0, -1), box * 0.86))
        faces.append(q([(-0.14, cy0, 1.92), (-0.14, cy0, 2.20), (-0.14, cy1, 2.20), (-0.14, cy1, 1.92)], (1, 0, 0), box * 0.78))
        if state.light:
            lamp = np.array([0.16, 0.16, 0.15], np.float32)
            faces.append(q([(-0.08, gy + 0.02, 2.66), (0.08, gy + 0.02, 2.66), (0.08, gy + 0.02, 2.78), (-0.08, gy + 0.02, 2.78)], (0, 1, 0), lamp))
            faces.append(q([(-0.08, gy + 0.02, 2.66), (0.08, gy + 0.02, 2.66), (0.08, gy + 0.10, 2.66), (-0.08, gy + 0.10, 2.66)], (0, 0, -1), lamp))
        # A transom plate closes the stern; the outboard clamps to it from astern. The inner
        # skin sits 5 mm inside the outer one, because the GL pass draws both sides and two
        # coplanar skins would depth-fight there.
        faces.append(q([(-beam, fy, z_near + 0.005), (-beam, gy, z_near + 0.005), (beam, gy, z_near + 0.005),
                        (beam, fy, z_near + 0.005)], (0, 0, 1), wall))
        faces.append(q([(-rail_o, -1.46, z_near), (rail_o, -1.46, z_near), (rail_o, gy, z_near),
                        (-rail_o, gy, z_near)], (0, 0, -1), hull))
        faces.append(q([(-rail_o, gy + 0.035, z_near - 0.02), (rail_o, gy + 0.035, z_near - 0.02),
                        (rail_o, gy + 0.035, z_near + 0.06), (-rail_o, gy + 0.035, z_near + 0.06)],
                       (0, 1, 0), rail))
        faces.extend(outboard_faces(state.steer, till))
        # The tiller runs forward from the outboard's swivel and swings with it; its extension
        # ends at the grip the Skipper's paw holds (boatmesh.tiller_faces, issue #192).
        faces.extend(tiller_faces(state.steer, till))
        return glow_hull(state, faces)

    def _snow(self, anim: float, amount: float):
        # A fixed foreground lattice: no particle history or scene depth changes.
        for i in range(96):
            x = int((i*73.37 + math.sin(i+anim*.18)*7) % self.w)
            y = int((i*47.11 + anim*(5+i%7)) % self.h)
            alpha = amount*(.30+.06*(i%4))
            self.col[y:min(y+2,self.h), x:min(x+2,self.w)] *= 1-alpha
            self.col[y:min(y+2,self.h), x:min(x+2,self.w)] += np.array([.85,.9,.94])*alpha

    def _rain(self, anim: float, amount: float):
        h, w, _ = self.col.shape
        tint = np.array([0.62, 0.66, 0.70], np.float32)
        alpha = 0.45 * amount
        for i in range(80):
            x = int((i * 97 + anim * 220) ) % w
            y = int((i * 53 + anim * 380)) % h
            for k in range(4):
                yy = y + k
                xx = x - k // 2
                if 0 <= yy < h and 0 <= xx < w:
                    self.col[yy, xx] = self.col[yy, xx] * (1.0 - alpha) + tint * alpha

    def _birds(self, cam, anim: float):
        for i in range(5):
            ang = anim * 0.10 + i * 1.27
            rad = 80.0 + i * 26.0
            bx = math.cos(ang) * rad
            bz = math.sin(ang) * rad * 0.75
            by = 24.0 + (i % 3) * 7.0
            hit = cam.project_world(bx, by, bz)
            if hit is None:
                continue
            sx, sy, zz = hit
            if zz > 500:
                continue
            ix, iy = int(sx), int(sy)
            span = 2 if zz > 120 else 3
            for k in range(-span, span + 1):
                yy = iy + abs(k) // 2
                xx = ix + k
                if 0 <= xx < self.w and 0 <= yy < self.h and zz < self.z[yy, xx]:
                    self.col[yy, xx] = 0.05 + 0.1 * (1.0 - min(zz / 400.0, 1.0))

    def _quantize(self, col: np.ndarray) -> np.ndarray:
        return (np.clip(col, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)

    def close(self):
        pass

    def poke_splashes(self, state):
        self.splashes = [s for s in self.splashes if state.anim - s[2] < 2.4]
        if len(self.splashes) < 3 and np.random.random() < 0.01:
            ang = np.random.uniform(-math.pi, math.pi)
            rad = np.random.uniform(20, 180)
            x = state.x + math.cos(ang) * rad
            z = state.z + math.sin(ang) * rad
            if float(self.world.shore_sd(x, z)) < -5:
                self.splashes.append((x, z, state.anim))
