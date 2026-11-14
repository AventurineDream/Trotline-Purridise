"""Sky effect layer: baked clouds, night dome, moon face and star catalogue.

`SkyFx` is the sky slice's `fishing.fx.Fx`. At lake load it renders, on the
GPU, two seamless cloud tiles and an octahedral night-dome texture
(`shaders/skybake.frag`), and uploads a star catalogue built with NumPy. Every
frame it binds them to texture units 6-9 and hands `common.glsl`'s `sky()` and
`haze()` the per-frame values that depend only on the weather (sunlight
colour, aureole width, cloud drift), so the per-pixel work is a handful of
texture fetches instead of noise loops.

Constraints: everything is deterministic for a lake (seeded from its id),
drift and twinkle come from `state.anim` and hold still under Reduced Motion,
and the same shaders run on every tier — only texture sizes change.
"""

from __future__ import annotations

import math
import zlib

import moderngl
import numpy as np

from .fx import SKY_UNITS, Fx, reduced_motion

CLOUD_UNIT, CLOUD2_UNIT, DOME_UNIT, STAR_UNIT = SKY_UNITS
# Star cells stay near three screen pixels wide at every tier, so each star is
# a crisp analytic point found with a 2x2 cell lookup (see sky_stars_at).
STAR_CELLS = 1024
STAR_COUNT = 9000
BAND_STAR_COUNT = 6000
# Galactic planes (unit normals). The Lagoon keeps its old band's circle.
MILKY_WAY_NORMAL = (0.58, 0.38, 0.72)
NEBULA_BAND_NORMAL = (0.4153, 0.5440, -0.7290)
# Cloud drift in tile units per second for (cumulus, altocumulus, cirrus,
# edge boil). Slow enough that a minute of watching shows gentle movement.
DRIFT = (0.0011, 0.00055, 0.00022, 0.0004)


def _seed(world) -> int:
    """A stable 31-bit seed per lake id (crc32, not Python's salted hash)."""
    return zlib.crc32(str(world.id).encode()) & 0x7FFFFFFF


def octa_encode(d: np.ndarray) -> np.ndarray:
    """Upper-hemisphere unit directions (N,3) to [0,1]^2 octahedral coordinates.

    Matches `sky_octa` in common.glsl and `octa_dir` in skybake.frag.
    """
    a = np.abs(d)
    p = d[:, [0, 2]] / (a[:, 0] + np.maximum(d[:, 1], 0.0) + a[:, 2])[:, None]
    return np.stack([p[:, 0] + p[:, 1], p[:, 0] - p[:, 1]], -1) * 0.5 + 0.5


def star_catalogue(seed: int, band_normal, cells: int = STAR_CELLS, *,
                   band_count: int = BAND_STAR_COUNT, band_dimming: float = 0.7) -> np.ndarray:
    """Bake the star map: one RGBA8 texel per octahedral cell.

    Args:
        seed: Lake seed; the same seed always gives the same sky.
        band_normal: Unit normal of the galactic plane, where extra stars crowd.
        cells: Edge of the square cell grid.
        band_count: Extra stars crowded along the plane.
        band_dimming: Magnitudes added to the band stars (a fainter crowd).

    Returns:
        uint8 array (cells, cells, 4): R,G the star's position inside its cell,
        B log2 brightness ((log2(I)+7)/10, 0 = no star), A colour temperature
        (0 orange .. 1 blue-white). Brighter stars win shared cells.
    """
    rng = np.random.default_rng(seed)
    # Uniform over the hemisphere: height uniform in [0,1], azimuth uniform.
    y = rng.random(STAR_COUNT)
    az = rng.random(STAR_COUNT) * math.tau
    r = np.sqrt(1.0 - y * y)
    field = np.stack([r * np.cos(az), y, r * np.sin(az)], -1)
    # Band stars: a narrow Gaussian in galactic latitude around the plane.
    n = np.asarray(band_normal, np.float64)
    n /= np.linalg.norm(n)
    a = np.cross(n, (0.0, 1.0, 0.0))
    a /= np.linalg.norm(a)
    b = np.cross(n, a)
    lon = rng.random(band_count * 2) * math.tau
    lat = rng.normal(0.0, 0.09, band_count * 2)
    band = (np.cos(lat)[:, None] * (np.cos(lon)[:, None] * a + np.sin(lon)[:, None] * b)
            + np.sin(lat)[:, None] * n)
    band = band[band[:, 1] > 0.0][:band_count]
    dirs = np.concatenate([field, band])
    dirs /= np.linalg.norm(dirs, axis=1, keepdims=True)
    count = len(dirs)
    # Magnitudes follow N(<m) ~ 10^(0.5 m) down to 6.5; display brightness is
    # compressed (gamma 0.55) so the faintest still read as dust on an 8-bit
    # display and the brightest few dozen sit above white for the bloom.
    mag = 6.5 + np.log10(rng.random(count) + 1e-9) / 0.5
    mag[len(field):] += band_dimming
    bright = 0.075 * 10.0 ** (-0.4 * (mag - 6.5) * 0.55)
    temp = np.clip(rng.normal(0.55, 0.22, count), 0.0, 1.0)
    uv = octa_encode(dirs) * cells
    cell = np.clip(np.floor(uv).astype(np.int64), 0, cells - 1)
    frac = np.clip(uv - cell, 0.0, 0.999)
    order = np.argsort(bright)  # brightest written last wins its cell
    image = np.zeros((cells, cells, 4), np.uint8)
    code = np.clip((np.log2(bright) + 7.0) / 10.0, 1.0 / 255.0, 1.0)
    rows = np.stack([frac[:, 0] * 255.0, frac[:, 1] * 255.0, code * 255.0, temp * 255.0], -1)
    image[cell[order, 1], cell[order, 0]] = np.round(rows[order]).astype(np.uint8)
    return image


class SkyFx(Fx):
    """Sky slice: bakes clouds, dome, moon and stars; supplies sky uniforms.

    Args:
        renderer: The owning `LakeRenderer` (GL objects are released with it).
        detail: Tier; `detail.sky_texels` sets the cloud tiles (half of it per
            edge) and the night dome (half of it per edge).
    """

    def __init__(self, renderer, detail):
        super().__init__(renderer, detail)
        ctx = renderer.ctx
        world = renderer.world
        self.seed = _seed(world)
        self.tile = max(256, detail.sky_texels // 2)
        self.dome = max(256, detail.sky_texels // 2)
        self.moon_rows = 64 if detail.sky_texels <= 1024 else 128
        nebula = bool(getattr(world, "nebula", False))
        program = renderer.program("sky.vert", "skybake.frag")
        quad = ctx.buffer(np.array([[-1, -1], [3, -1], [-1, 3]], np.float32).tobytes())
        vao = ctx.vertex_array(program, [(quad, "2f", "in_xy")])
        try:
            program["bake_seed"].value = self.seed % 65521
            self.cloud2 = self._bake(program, vao, 0, (self.tile, self.tile))
            self.cloud2.use(CLOUD2_UNIT)
            program["bake_field"].value = CLOUD2_UNIT
            self.cloud = self._bake(program, vao, 1, (self.tile, self.tile))
            program["bake_moon_rows"].value = float(self.moon_rows)
            program["bake_nebula"].value = 1.0 if nebula else 0.0
            self.dome_tex = self._bake(program, vao, 2, (self.dome, self.dome + self.moon_rows),
                                       repeat=False)
        finally:
            vao.release()
            quad.release()
        # The Lagoon's band has always been a dense river of stars: keep it so.
        if nebula:
            stars = star_catalogue(self.seed, NEBULA_BAND_NORMAL, band_count=12000, band_dimming=0.2)
        else:
            stars = star_catalogue(self.seed, MILKY_WAY_NORMAL)
        self.stars = renderer.own(ctx.texture((STAR_CELLS, STAR_CELLS), 4, stars.tobytes()))
        self.stars.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self.stars.repeat_x = self.stars.repeat_y = False
        # Phase of the wind per layer: a fixed heading per lake, never the
        # clock's wind, so drift is a pure function of anim.
        heading = (self.seed % 6283) / 1000.0
        self.wind = np.array([math.cos(heading), math.sin(heading)])

    def _bake(self, program, vao, mode, size, *, repeat=True):
        """Render one bake mode into a new mipmapped RGBA8 texture of `size`."""
        ctx = self.renderer.ctx
        tex = self.renderer.own(ctx.texture(size, 4))
        fb = ctx.framebuffer([tex])
        try:
            fb.use()
            ctx.viewport = (0, 0, *size)
            ctx.disable(moderngl.DEPTH_TEST | moderngl.BLEND)
            program["bake_mode"].value = mode
            program["bake_size"].value = (float(size[0]), float(size[1]))
            vao.render()
        finally:
            fb.release()
        tex.repeat_x = tex.repeat_y = repeat
        tex.build_mipmaps()
        tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        tex.anisotropy = 4.0
        return tex

    def bind(self) -> None:
        """Bind the cloud tiles, dome and star cells to units 6-9."""
        self.cloud.use(CLOUD_UNIT)
        self.cloud2.use(CLOUD2_UNIT)
        self.dome_tex.use(DOME_UNIT)
        self.stars.use(STAR_UNIT)

    def uniforms(self, state, light, cam) -> dict:
        """Samplers plus weather-derived sky values for this frame.

        Drift offsets are reduced modulo one tile on the CPU in double
        precision, so they never jump when `anim` wraps in the shaders.
        """
        t = 0.0 if reduced_motion(state) else float(state.anim)
        w = self.wind
        side = np.array([-w[1], w[0]])
        layer1 = (w * DRIFT[0] * t) % 1.0
        layer2 = ((w * 0.8 + side * 0.6) * DRIFT[1] * t) % 1.0
        cirrus = ((w * 0.6 - side * 0.8) * DRIFT[2] * t) % 1.0
        boil = (side * DRIFT[3] * t) % 1.0
        sun = np.asarray(light["sun"], np.float64)
        elev = float(sun[1])
        # Sunlight on clouds and haze: white at noon, gold low, rose at the rim.
        noon, low, rose = np.array([1.0, 0.97, 0.91]), np.array([1.0, 0.70, 0.40]), np.array([1.0, 0.50, 0.42])
        k = float(np.clip((elev - 0.04) / 0.40, 0.0, 1.0))
        k = k * k * (3 - 2 * k)
        colour = low + (noon - low) * k
        k = float(np.clip((elev + 0.06) / 0.14, 0.0, 1.0))
        colour = rose + (colour - rose) * k * k * (3 - 2 * k)
        night = float(light["night"])
        cover = float(light["cloud_cover"])
        overcast = float(np.clip((cover - 0.82) / 0.30, 0.0, 1.0))
        overcast = overcast * overcast * (3 - 2 * overcast)
        haze = float(np.clip(light.get("mist", 0.0) * 0.7 + light["rain"] * 0.5
                             + light["gold"] * 0.6 + overcast * 0.4, 0.0, 1.0))
        # Twilight glow on cloud undersides: lit from below after the sun sets.
        under = math.exp(-((elev - 0.01) ** 2) / 0.006) * (1.0 - overcast * 0.85)
        return {
            "sky_cloud": CLOUD_UNIT, "sky_cloud2": CLOUD2_UNIT,
            "sky_dome": DOME_UNIT, "sky_stars": STAR_UNIT,
            "sky_drift": (*layer1, *layer2), "sky_drift2": (*cirrus, *boil),
            "sky_anim": t % 10000.0,
            "sky_sun_col": tuple(float(c) for c in colour),
            "sky_overcast": overcast, "sky_haze": haze, "sky_under": float(under),
            "sky_layout": (float(self.dome), float(self.moon_rows), float(STAR_CELLS), 0.0),
            "sky_night_vis": float(np.clip((night - 0.25) / 0.6, 0.0, 1.0)),
        }

    def memory_bytes(self) -> int:
        """GPU bytes: two RGBA8 tiles and the dome with mips (x4/3), star cells without."""
        tiles = 2 * self.tile * self.tile * 4
        dome = self.dome * (self.dome + self.moon_rows) * 4
        return (tiles + dome) * 4 // 3 + STAR_CELLS * STAR_CELLS * 4
