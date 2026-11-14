"""Water effect layer: the baked wave, rain-ring and foam textures behind water.frag.

`WaterFx` bakes three resources on the GPU when a lake loads and hands the
water shader its per-frame uniforms:

- unit 10, `wave_tex`: a seamless, looping slope/height volume (a 2D texture
  array, one layer per frame) summed from a small directional wave spectrum.
  Channels are (dh/du, dh/dv, height, slope^2): the mipmapped slope^2 lets the
  shader recover the slope variance that filtering hides, so distant water
  turns rough (soft vertical reflection smears, a broad sun path) instead of
  glassy or shimmering.
- unit 11, `rain_tex`: looping frames of expanding raindrop rings (slope,
  slope^2 and an impact sparkle), sampled at two offsets for heavier rain.
- unit 12, `water_noise`: tileable RGBA8 noise: gust patches, foam lace,
  bed variation and a caustic net.

It also generates mipmaps for the renderer's planar reflection after the
reflection pass, so roughness can blur reflections cheaply, and binds the
reflection depth so still nights can reflect full-resolution stars.

Constraints: sizes come from the `Detail` tier (wave_texels^2 x wave_frames);
the spectrum uses a fixed seed and integer wave vectors and integer cycles per
loop, so tiles and loops are seamless and frames deterministic. Loop phases
and drift offsets are reduced modulo one on the CPU in double precision, so
the shader never sees large times. Reduced Motion holds every phase at zero.
Baking reuses one scratch framebuffer and frees it; nothing is created per
frame.
"""

from __future__ import annotations

import math
import time

import moderngl
import numpy as np

from .fx import WATER_UNITS, Fx, reduced_motion

WAVE_UNIT, RAIN_UNIT, NOISE_UNIT = WATER_UNITS
REFLECTION_DEPTH_UNIT = 5  # the renderer's unit for the planar reflection's depth

# Near and far wave tiles, metres. The ratio is irrational-looking and the far
# tile is turned, so neither the tile nor the loop lines up anywhere.
NEAR_TILE_M = 3.1
FAR_TILE_M = 11.7
NEAR_ANGLE = 0.0
FAR_ANGLE = 0.63
RAIN_TILE_M = 2.4
GUST_TILE_M = 170.0
# Loop length of the near tile in seconds. Deep-water dispersion makes a tile
# s times larger run sqrt(s) times slower, which keeps both scales physical.
NEAR_LOOP_S = 1.45
RAIN_LOOP_S = 1.1
# Drift of each tile, metres per second, along the prevailing wind.
NEAR_DRIFT_MPS = 0.07
FAR_DRIFT_MPS = 0.16
GUST_DRIFT_MPS = 1.1
# Prevailing wind heading (radians, as `weather.wind_at`). The tiles are not
# turned with the hourly wind: rotating world-anchored waves would visibly
# slide distant water.
PREVAILING_HEADING = 0.85
SPECTRUM_SEED = 20261112
# RMS surface slope of each lake on an ordinary breeze, and how strongly the
# wind gusts move across it in patches (Cedar and Flathead are the breezy ones).
# Kept low on purpose: the mirror is each lake's best feature; the waves add
# character and glitter without shattering the reflected shore.
LAKE_SLOPE = {"briar": 0.011, "cedar": 0.019, "flathead": 0.018, "crater": 0.008, "nebula": 0.011}
# The Lagoon is glassy: its stars reflect with only a gentle shimmer.
NEBULA_GLASS = 0.55
LAKE_GUST = {"briar": 0.5, "cedar": 0.6, "flathead": 0.65, "crater": 0.45, "nebula": 0.4}
# Sun and moon glitter radiance per unit of sun_i/moon_i; > 1 blooms.
SUN_GLINT = 0.0065
MOON_GLINT = 0.006


def spectrum(texels: int, frames: int, seed: int = SPECTRUM_SEED) -> tuple[np.ndarray, np.ndarray, float]:
    """The baked wave spectrum: integer wave vectors on the unit tile.

    Args:
        texels: Edge of one baked frame; the finest wave keeps ~8 texels.
        frames: Frames in the loop; no wave advances more than 1/8 cycle per
            frame, so linear blending between frames never pulses visibly.
        seed: Fixed seed so every run bakes the same water.

    Returns:
        (waves, cycles, height_scale): `waves` rows are (kx, ky, slope
        amplitude, start phase) with kx, ky in cycles per tile; `cycles` are
        whole cycles per loop; amplitudes are normalised so the RMS slope
        magnitude is 1 and `height_scale` makes the RMS height 1.
    """
    rng = np.random.default_rng(seed)
    count = 40 if texels <= 128 else 56 if texels <= 256 else 72
    kmax = max(6.0, texels / 8.0)
    rows, seen = [], set()
    wind = 0.0  # tile space; the tile itself is turned toward the wind
    while len(rows) < count:
        k = math.exp(rng.uniform(math.log(1.0), math.log(kmax)))
        # Short waves spread more widely than long ones, so the fine ripple
        # never combs into parallel hatching.
        spread = 0.45 + 0.55 * math.log(k) / math.log(kmax)
        if rng.random() < 0.15:
            angle = rng.uniform(0.0, math.tau)  # a little crossing chop
        else:
            angle = wind + rng.normal(0.0, spread)
        kx, ky = round(k * math.cos(angle)), round(k * math.sin(angle))
        if (kx, ky) == (0, 0) or (kx, ky) in seen or (-kx, -ky) in seen:
            continue
        seen.add((kx, ky))
        mag = math.hypot(kx, ky)
        # Slope amplitude falls gently with wavenumber: broad swells carry the
        # light, fine ripples add texture without turning to noise.
        slope = mag ** -0.5 * (0.75 + 0.5 * rng.random())
        cycles = min(max(1, round(math.sqrt(mag))), max(1, frames // 8))
        rows.append((kx, ky, slope, rng.uniform(0.0, math.tau), cycles))
    table = np.asarray(rows, np.float64)
    mags = np.hypot(table[:, 0], table[:, 1])
    # Each wave contributes amplitude^2/2 to the mean squared slope magnitude.
    table[:, 2] /= math.sqrt(float(np.sum(table[:, 2] ** 2) / 2.0))
    # Height amplitude a satisfies slope = a * tau * |k|.
    heights = table[:, 2] / (math.tau * mags)
    height_scale = 1.0 / math.sqrt(float(np.sum(heights ** 2) / 2.0))
    waves = np.stack([table[:, 0], table[:, 1], heights, table[:, 3]], 1).astype(np.float32)
    return waves, table[:, 4].astype(np.float32), height_scale


def _loop(seconds: float, period: float, frames: int) -> tuple[int, int, float]:
    """Frame pair and blend for time `seconds` in a loop of `period` seconds."""
    phase = (seconds / period) % 1.0 * frames
    first = int(phase) % frames
    return first, (first + 1) % frames, phase - int(phase)


def _drift(seconds: float, speed: float, tile: float, angle: float = 0.0) -> tuple[float, float]:
    """Offset in tile axes, modulo one, of a tile drifting at `speed` m/s.

    `angle` turns the drift away from the tile's +u axis (its wind axis).
    """
    distance = seconds * speed / tile
    return ((distance * math.cos(angle)) % 1.0, (distance * math.sin(angle)) % 1.0)


class WaterFx(Fx):
    """Baked water surface textures and the water shader's per-frame uniforms.

    Args:
        renderer: The owning `LakeRenderer` (see `fishing.fx.Fx`).
        detail: Tier that sizes the bake: `wave_texels`^2 x `wave_frames` for
            the wave volume, the same for rain rings, and 2x `wave_texels` for
            the noise texture.

    Side effects:
        Creates three textures through `renderer.own` and briefly a scratch
        framebuffer and pixel buffer, released before returning.
    """

    def __init__(self, renderer, detail):
        super().__init__(renderer, detail)
        start = time.perf_counter()
        ctx = renderer.ctx
        world = renderer.world
        self.texels = int(detail.wave_texels)
        self.frames = int(detail.wave_frames)
        self.rain_texels = max(128, self.texels // 2)
        self.rain_frames = max(16, min(32, self.frames))
        self.noise_texels = self.texels * 2
        self.lake = getattr(world, "id", "briar")
        self.reflection = renderer.reflect_tex
        self._reflection_depth = getattr(renderer.reflect_fb, "depth_attachment", None)
        if not isinstance(self._reflection_depth, moderngl.Texture):
            self._reflection_depth = None
        # Reflection mipmaps are regenerated each frame; count them once.
        rw, rh = self.reflection.size
        self._reflection_mip_bytes = int(rw * rh * (8 if renderer.hdr else 3) / 3)
        program = renderer.program("sky.vert", "water_bake.frag")
        quad = ctx.buffer(np.array([[-1, -1], [3, -1], [-1, 3]], np.float32).tobytes())
        vao = ctx.vertex_array(program, [(quad, "2f", "in_xy")])
        try:
            self.wave_tex = self._bake_array(program, vao, 0, self.texels, self.frames)
            self.rain_tex = self._bake_array(program, vao, 1, self.rain_texels, self.rain_frames)
            self.noise_tex = self._bake_noise(program, vao)
        finally:
            vao.release()
            quad.release()
        self.bake_seconds = time.perf_counter() - start

    def _bake_array(self, program, vao, mode: int, size: int, frames: int):
        """Render `frames` loop phases into a mipmapped RGBA16F texture array."""
        ctx = self.renderer.ctx
        target = self.renderer.own(ctx.texture_array((size, size, frames), 4, dtype="f2"))
        scratch = ctx.texture((size, size), 4, dtype="f2")
        fb = ctx.framebuffer([scratch])
        pixels = ctx.buffer(reserve=size * size * 8)
        try:
            program["bake_mode"] = mode
            if mode == 0:
                waves, cycles, height_scale = spectrum(size, frames)
                block = np.zeros((96, 4), np.float32)
                block[:len(waves)] = waves
                cyc = np.zeros(96, np.float32)
                cyc[:len(cycles)] = cycles
                program["bake_waves"].write(block.tobytes())
                program["bake_cycles"].write(cyc.tobytes())
                program["bake_count"] = len(waves)
                program["bake_height"] = float(height_scale)
            fb.use()
            ctx.viewport = (0, 0, size, size)
            ctx.disable(moderngl.DEPTH_TEST | moderngl.BLEND)
            for layer in range(frames):
                program["bake_phase"] = layer / frames
                vao.render()
                fb.read_into(pixels, components=4, dtype="f2")
                target.write(pixels, viewport=(0, 0, layer, size, size, 1))
        finally:
            pixels.release()
            fb.release()
            scratch.release()
        target.build_mipmaps()
        target.repeat_x = target.repeat_y = True
        target.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        if not self.renderer.software_gl:
            target.anisotropy = 8.0
        return target

    def _bake_noise(self, program, vao):
        """Render the tileable gust/foam/bed/caustic noise straight into its texture."""
        ctx = self.renderer.ctx
        size = self.noise_texels
        target = self.renderer.own(ctx.texture((size, size), 4))
        fb = ctx.framebuffer([target])
        try:
            program["bake_mode"] = 2
            fb.use()
            ctx.viewport = (0, 0, size, size)
            vao.render()
        finally:
            fb.release()
        target.build_mipmaps()
        target.repeat_x = target.repeat_y = True
        if not self.renderer.software_gl:
            target.anisotropy = 8.0
        return target

    def bind(self) -> None:
        """Bind the wave volume, rain rings and noise to units 10-12."""
        self.wave_tex.use(WAVE_UNIT)
        self.rain_tex.use(RAIN_UNIT)
        self.noise_tex.use(NOISE_UNIT)

    def draw(self, state, light, cam, *, mirror: float, stage: str) -> None:
        """Prepare the finished reflection for the water pass.

        Runs at the main pass's "scene" stage, after every layer has drawn
        into the reflection: rebuilds the reflection's mipmaps (roughness
        blurs by mip level) and binds its depth so the water can tell open
        sky from scenery on any lake.
        """
        if mirror < 0 or stage != "scene":
            return
        self.reflection.build_mipmaps()
        if self._reflection_depth is not None:
            self._reflection_depth.use(REFLECTION_DEPTH_UNIT)

    def uniforms(self, state, light, cam) -> dict:
        """Loop phases, drifts and weather-driven strengths for water.frag.

        Returns:
            Sampler units, frame pairs and blends for both wave scales and
            the rain, drift offsets in tiles (reduced modulo one), the RMS
            slope, gust patches, sun/moon glitter strength and the
            reflected-star strength. Every animated value is frozen at time
            zero under Reduced Motion.
        """
        t = 0.0 if reduced_motion(state) else float(state.anim)
        heading = PREVAILING_HEADING
        near_loop = NEAR_LOOP_S
        far_loop = NEAR_LOOP_S * math.sqrt(FAR_TILE_M / NEAR_TILE_M)
        n0, n1, nf = _loop(t, near_loop, self.frames)
        f0, f1, ff = _loop(t, far_loop, self.frames)
        r0, r1, rf = _loop(t, RAIN_LOOP_S, self.rain_frames)
        q0, q1, qf = _loop(t + RAIN_LOOP_S * 0.37, RAIN_LOOP_S * 1.21, self.rain_frames)
        near = _drift(t, NEAR_DRIFT_MPS, NEAR_TILE_M)
        far = _drift(t, FAR_DRIFT_MPS, FAR_TILE_M, -FAR_ANGLE * 0.6)
        gust = _drift(t, GUST_DRIFT_MPS, GUST_TILE_M)
        rain = float(light["rain"])
        cloud = float(light["cloud_cover"])
        night = float(light["night"])
        still = self._still(state, light)
        # Today's ripple strength, as the CPU renderer reads it: the weather's
        # ripple (rain roughens), the Caldera's still nights and the Lagoon's
        # glassiness. 0.9 is a fair day.
        ripple = float(light.get("ripple", 0.9 + rain * 0.85)) / 0.9
        slope = LAKE_SLOPE.get(self.lake, 0.03) * ripple * (1.0 - still * 0.95)
        if self.lake == "nebula":
            slope *= NEBULA_GLASS
        clear = 1.0 - min(1.0, max(0.0, (cloud - 0.55) / 0.45))
        clear *= (1.0 - rain) * (1.0 - float(light.get("mist", 0.0)) * 0.6)
        gold = float(light["gold"])
        sun_glint = float(light["sun_i"]) * clear * (1.0 + 1.6 * gold) * SUN_GLINT
        moon_glint = float(light["moon_i"]) * night * clear * MOON_GLINT
        calm = min(1.0, max(0.0, 1.0 - (slope - 0.012) / 0.03))
        stars = night * clear * calm * 0.75
        return {
            "wave_tex": WAVE_UNIT, "rain_tex": RAIN_UNIT, "water_noise": NOISE_UNIT,
            "wave_layers": (float(n0), float(n1), float(f0), float(f1)),
            "wave_mix": (float(nf), float(ff)),
            "wave_drift": (*near, *far),
            "wave_axes": (*self._axis(heading + NEAR_ANGLE), *self._axis(heading + FAR_ANGLE)),
            "wave_scale": (1.0 / NEAR_TILE_M, 1.0 / FAR_TILE_M, 1.0 / RAIN_TILE_M, 1.0 / GUST_TILE_M),
            "wave_slope": float(slope),
            "water_gust": (*gust, LAKE_GUST.get(self.lake, 0.4), 0.0),
            "rain_layers": (float(r0), float(r1), float(q0), float(q1)),
            "rain_mix": (float(rf), float(qf)),
            "water_glint": (float(sun_glint), float(moon_glint)),
            "water_star": float(stars),
            "water_t": float(t % 3600.0),
        }

    @staticmethod
    def _axis(heading: float) -> tuple[float, float]:
        """World xz direction of a tile's +u (wind) axis for a heading in radians."""
        return (float(math.sin(heading)), float(math.cos(heading)))

    def _still(self, state, light) -> float:
        """The Caldera's mirror nights and the Lagoon's Settle In stillness (0..1)."""
        from .caldera import reflection_strength
        return float(reflection_strength(state, light))

    def memory_bytes(self) -> int:
        """GPU bytes held: three mipmapped bakes plus the reflection's mip chain."""
        wave = self.texels * self.texels * self.frames * 8
        rain = self.rain_texels * self.rain_texels * self.rain_frames * 8
        noise = self.noise_texels * self.noise_texels * 4
        return int((wave + rain + noise) * 4 / 3) + self._reflection_mip_bytes
