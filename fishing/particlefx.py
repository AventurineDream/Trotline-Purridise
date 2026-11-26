"""Living air: stateless GPU particles for the lake (sun motes, fireflies, mist
wisps, rain and snow in depth, falling leaves and needles, cinder ash, Nebula
star dust and lane motes, crystal sparkles, and insects over the reeds).

How it fits: one `fishing.fx.Fx` layer registered in `glrender.FX_LAYERS`.
Every system is a static instance buffer of random seeds (or seeds anchored to
the lake: banks, trees, reeds, current lanes, crystals) built once at lake
load. `particle.vert` turns seed + time + weather uniforms into a camera-facing
quad, so nothing is simulated on the CPU, no buffer is written per frame and no
GL object is created after load. Weather/time only choose which systems draw
and how strongly.

Key constraints: deterministic for a given state (time is `state.anim`, held
at a fixed still under Reduced Motion); depth test on and depth writes off, so
the scene depth never changes; premultiplied blending with emitters above 1.0
for bloom under HDR; only emitters that would plausibly reflect (fireflies,
star dust, lane motes, crystal sparkles) draw into the planar reflection.
"""

from __future__ import annotations

import math
import zlib

import moderngl
import numpy as np

from .data import hour_of_day
from .fx import Fx, PARTICLE_UNITS, reduced_motion
from .weather import weather_visuals

# System ids; particle.vert switches on the same numbers.
MOTES, FIREFLY, WISP, RAIN, SNOW, LEAF, ASH, DUST, LANE, SPARKLE, INSECT, SPRING, NEEDLE, POLLEN = range(14)
# Systems that reuse another system's seeds instead of owning a buffer: by
# day the firefly anchors along the bank carry pollen.
SHARED_SEEDS = {POLLEN: FIREFLY}
# Systems that draw into the planar reflection (emitters near the water).
REFLECTED = frozenset((FIREFLY, DUST, LANE, SPARKLE))
# How each system is drawn: point sprites (one vertex), streak lines (two) or
# quads (four); specks cost one vertex shader run instead of four.
POINT, LINE, QUAD = 0, 1, 2
PRIMITIVE = {RAIN: LINE, NEEDLE: LINE, WISP: QUAD, SPRING: QUAD, LEAF: QUAD}
_GL_MODE = {POINT: (moderngl.POINTS, 1), LINE: (moderngl.LINES, 2), QUAD: (moderngl.TRIANGLE_STRIP, 4)}
# Instances per system at the standard tier (detail.particles == 256).
# Weather boxes keep their density on every tier and grow their box instead,
# so higher tiers see rain and snow deeper into the distance. Anchored systems
# (banks, trees, reeds, lanes, crystals) keep the standard count above it, so
# the look matches across tiers, and thin out on the low tier only.
STANDARD_COUNTS = {
    MOTES: 3000, FIREFLY: 6000, WISP: 220, RAIN: 9000, SNOW: 7000, LEAF: 1200,
    ASH: 2600, DUST: 6000, LANE: 4000, SPARKLE: 6000, INSECT: 900, SPRING: 70,
    NEEDLE: 8000,
}
# Half-edge in metres of each camera-centred weather box at the standard tier.
BOX_RADIUS = {MOTES: 26.0, WISP: 130.0, RAIN: 34.0, SNOW: 30.0, ASH: 42.0, DUST: 45.0}
# Fireflies per metre of shoreline.
FIREFLIES_PER_M = 1.4
WISP_TEXELS = 256
# The fixed instant every system holds under Reduced Motion (seconds of anim).
STILL_TIME = 0.0
# A light, steady breeze in m/s that particles drift on. Fixed per lake: the
# drift is velocity x anim, so a live wind would jump particles when it changed.
DRIFT = {"briar": (0.18, 0.07), "cedar": (0.45, 0.20), "flathead": (0.30, -0.18),
         "crater": (0.08, 0.05), "nebula": (0.05, 0.10)}
# Each lake sheds leaves from the species that stand on it, so drops match the trees in view.
LEAF_KINDS = {"briar": ("oak", "birch", "pine"), "cedar": ("cottonwood", "willow", "cypress")}
REED_KINDS = ("reed", "cattail")


def _scale(detail) -> float:
    """Tier multiplier for instance counts: 1 at standard, ~0.44 low, ~1.9 ultra."""
    return (max(16, int(detail.particles)) / 256.0) ** 0.6


def _wisp_texture(texels: int, rng) -> np.ndarray:
    """A tileable, horizontally stretched noise field for mist wisps, uint8 (h, w).

    Filtering white noise by an anisotropic 1/f falloff in Fourier space keeps
    it seamless and gives long low streaks rather than round smoke blobs.
    """
    noise = rng.standard_normal((texels, texels))
    fy = np.fft.fftfreq(texels)[:, None]
    fx = np.fft.fftfreq(texels)[None, :]
    radius = np.sqrt((fx * 3.2) ** 2 + (fy * 0.9) ** 2) + 1.0 / texels
    field = np.real(np.fft.ifft2(np.fft.fft2(noise) / radius ** 1.6))
    field = (field - field.mean()) / (field.std() * 2.6) + 0.5
    return (np.clip(field, 0.0, 1.0) * 255).astype(np.uint8)


class ParticleFx(Fx):
    """Weather, time and place driven particle systems for one lake.

    Args:
        renderer: The owning `LakeRenderer` (GL objects go through `own`).
        detail: The `fishing.detail.Detail` tier; `detail.particles` thousand
            seeds is the ceiling for all systems together.

    Side effects: compiles `particle.vert/.frag`, uploads one static instance
    buffer per system that this lake uses and one small mipmapped noise
    texture on `PARTICLE_UNITS[0]`.
    """

    def __init__(self, renderer, detail):
        super().__init__(renderer, detail)
        ctx = renderer.ctx
        world = renderer.world
        self.world = world
        self.program = renderer.program("particle.vert", "particle.frag")
        self._members = renderer._program_members[self.program]
        rng = np.random.default_rng(zlib.crc32(("particles:" + world.id).encode()))
        scale = _scale(detail)
        self.box = {kind: radius * math.sqrt(scale) for kind, radius in BOX_RADIUS.items()}
        self.lake = "nebula" if world.nebula else "crater" if world.caldera else (
            "flathead" if world.generated else ("cedar" if world.id == "cedar" else "briar"))
        drift = DRIFT[self.lake]
        self._drift = (float(drift[0]), float(drift[1]))
        self._bytes = 0
        self.systems = {}
        for kind, rows in self._seeds(rng, scale).items():
            if rows is None or len(rows) == 0:
                continue
            rows = np.ascontiguousarray(rows, np.float32)
            buf = renderer.own(ctx.buffer(rows.tobytes()))
            vao = renderer.own(ctx.vertex_array(
                self.program, [(buf, "4f 4f /i", "in_a", "in_b")]))
            self.systems[kind] = (vao, len(rows))
            self._bytes += rows.nbytes
        budget = int(detail.particles) * 1000
        total = sum(count for _vao, count in self.systems.values())
        if total > budget:
            raise RuntimeError(f"particle seeds {total} exceed the tier's {budget}")
        # Kinds drawn from another system's buffer (not counted twice above).
        self.shared = frozenset(kind for kind, owner in SHARED_SEEDS.items() if owner in self.systems)
        for kind in self.shared:
            self.systems[kind] = self.systems[SHARED_SEEDS[kind]]
        image = _wisp_texture(WISP_TEXELS, rng)
        self.wisp = renderer.own(ctx.texture((WISP_TEXELS, WISP_TEXELS), 1, image.tobytes()))
        self.wisp.build_mipmaps()
        self.wisp.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
        self.wisp.repeat_x = self.wisp.repeat_y = True
        self._bytes += WISP_TEXELS * WISP_TEXELS * 4 // 3
        self._active = []
        self._after_rain_key = None
        self._after_rain = 0.0

    # --- lake-load baking -------------------------------------------------

    def _seeds(self, rng, scale) -> dict:
        """Per-system (n, 8) float32 rows: `in_a` then `in_b` for each instance."""
        lake = self.lake
        count = {kind: max(1, int(round(n * (scale if kind in BOX_RADIUS else min(1.0, scale)))))
                 for kind, n in STANDARD_COUNTS.items()}

        def box(kind):
            return rng.random((count[kind], 8), dtype=np.float32)

        out = {RAIN: box(RAIN), MOTES: box(MOTES) if lake != "nebula" else None}
        if lake == "flathead":
            out[SNOW] = box(SNOW)
            out[NEEDLE] = self._tree_drops(rng, count[NEEDLE], ("larch",), 0.35, 0.95)
        if lake in ("briar", "cedar"):
            out[FIREFLY] = self._bank(rng, count[FIREFLY])
            out[LEAF] = self._tree_drops(rng, count[LEAF], LEAF_KINDS[lake], 0.55, 0.9)
        if lake != "nebula":
            out[WISP] = box(WISP)
            out[INSECT] = self._reeds(rng, count[INSECT])
        if lake == "crater":
            out[ASH] = box(ASH)
            out[SPRING] = self._springs(rng, count[SPRING])
        if lake == "nebula":
            out[DUST] = box(DUST)
            out[LANE] = self._lanes(rng, count[LANE])
            out[SPARKLE] = self._crystals(rng, count[SPARKLE])
        return out

    def _band(self, rng, lo, hi, samples=400_000):
        """Random lake points whose shore distance lies in (lo, hi) metres.

        Returns:
            (rows, area): rows of (x, z, sd) and the band's area in m², estimated
            from the share of uniform samples over the lake bounds that hit it.
        """
        x0, z0, x1, z1 = self.world.bounds
        xs = rng.uniform(x0, x1, samples).astype(np.float32)
        zs = rng.uniform(z0, z1, samples).astype(np.float32)
        sd = np.asarray(self.world.shore_sd(xs, zs), np.float32)
        keep = (sd > lo) & (sd < hi)
        area = float(keep.sum()) / samples * (x1 - x0) * (z1 - z0)
        return np.stack([xs[keep], zs[keep], sd[keep]], 1), area

    def _ground(self, xs, zs):
        """Ground height (m) at points, with water at 0."""
        return np.maximum(np.asarray(self.world.sample_height(xs, zs), np.float32), 0.0)

    def _bank(self, rng, n):
        """Fireflies hang along the wooded bank, from the shallows into the trees.

        Density follows shoreline length (`FIREFLIES_PER_M`), so a long lake
        like Cedar is no sparser per metre than Briar, up to the tier's cap `n`.
        """
        lo, hi = -3.0, 30.0
        pts, area = self._band(rng, lo, hi)
        n = int(min(n, len(pts), max(200, area / (hi - lo) * FIREFLIES_PER_M)))
        if n <= 0:
            return None
        pts = pts[:n]
        xs, zs, sd = pts[:, 0], pts[:, 1], pts[:, 2]
        r = rng.random((len(pts), 6), dtype=np.float32)
        ground = self._ground(xs, zs)
        # Low over the grass and shallows, a few up into the understorey.
        ys = ground + 0.35 + r[:, 0] ** 2 * np.where(sd > 0, 3.6, 1.4)
        return np.stack([xs, ys, zs, r[:, 1], r[:, 2], r[:, 3], r[:, 4], r[:, 5]], 1)

    def _tree_drops(self, rng, n, kinds, lo, hi):
        """Leaves/needles start inside crowns of trees near the water and fall.

        `in_b.x` carries the ground (or water) height they settle on.
        """
        world = self.world
        trees = [p for p in world.props if p.kind in kinds]
        if not trees:
            return None
        tx = np.array([p.x for p in trees], np.float32)
        tz = np.array([p.z for p in trees], np.float32)
        th = np.array([p.h for p in trees], np.float32) * 1.35
        sd = np.asarray(world.shore_sd(tx, tz), np.float32)
        near = sd < 40.0
        if not near.any():
            return None
        tx, tz, th = tx[near], tz[near], th[near]
        pick = rng.integers(0, len(tx), n)
        r = rng.random((n, 7), dtype=np.float32)
        ang = r[:, 0] * math.tau
        rad = np.sqrt(r[:, 1]) * th[pick] * 0.16
        xs = tx[pick] + np.cos(ang) * rad
        zs = tz[pick] + np.sin(ang) * rad
        base = self._ground(tx[pick], tz[pick])
        ys = base + th[pick] * (lo + (hi - lo) * r[:, 2])
        return np.stack([xs, ys, zs, r[:, 3], base, r[:, 4], r[:, 5], r[:, 6]], 1)

    def _reeds(self, rng, n):
        """Small skimming swarms over each reed bed and cattail stand."""
        reeds = [p for p in self.world.props if p.kind in REED_KINDS]
        if not reeds:
            return None
        rx = np.array([p.x for p in reeds], np.float32)
        rz = np.array([p.z for p in reeds], np.float32)
        pick = rng.integers(0, len(reeds), n)
        r = rng.random((n, 7), dtype=np.float32)
        # Swarms sit just off the stand, over open water.
        xs = rx[pick] + (r[:, 0] - 0.5) * 3.0
        zs = rz[pick] + (r[:, 1] - 0.5) * 3.0
        ys = self._ground(xs, zs)
        return np.stack([xs, ys, zs, r[:, 2], r[:, 3], r[:, 4], r[:, 5], r[:, 6]], 1)

    def _springs(self, rng, n):
        """Steam sheets over Crater's warm springs and its two thermal vents."""
        world = self.world
        rows = [(x, z, r * 0.75) for zone, x, z, r in world.zones if zone == "springs"]
        rows += [(x, z, 9.0) for x, z in (world.environment or {}).get("thermal", ())]
        if not rows:
            return None
        rows = np.asarray(rows, np.float32)
        pick = rng.integers(0, len(rows), n * 3)
        r = rng.random((n * 3, 8), dtype=np.float32)
        ang = r[:, 0] * math.tau
        rad = np.sqrt(r[:, 1]) * rows[pick, 2]
        xs = rows[pick, 0] + np.cos(ang) * rad
        zs = rows[pick, 1] + np.sin(ang) * rad
        wet = np.asarray(world.shore_sd(xs, zs), np.float32) < -4.0
        xs, zs, r = xs[wet][:n], zs[wet][:n], r[wet][:n]
        if len(xs) == 0:
            return None
        return np.stack([xs, np.zeros_like(xs), zs, r[:, 2], r[:, 3], r[:, 4], r[:, 5], r[:, 6]], 1)

    def _lanes(self, rng, n):
        """Light motes seeded inside the Nebula's current lanes."""
        from .nebula import lane_circles
        circles = lane_circles(self.world)
        if len(circles) == 0:
            return None
        pick = rng.integers(0, len(circles), n * 2)
        r = rng.random((n * 2, 8), dtype=np.float32)
        ang = r[:, 0] * math.tau
        rad = np.sqrt(r[:, 1]) * circles[pick, 2] * 0.8
        xs = circles[pick, 0] + np.cos(ang) * rad
        zs = circles[pick, 1] + np.sin(ang) * rad
        wet = np.asarray(self.world.shore_sd(xs, zs), np.float32) < -3.0
        xs, zs, r = xs[wet][:n], zs[wet][:n], r[wet][:n]
        return np.stack([xs, np.zeros_like(xs), zs, r[:, 2], r[:, 3], r[:, 4], r[:, 5], r[:, 6]], 1)

    def _crystals(self, rng, n):
        """Sparkles hovering around the Nebula's crystal spires; `in_b.x` is spire height."""
        spires = [p for p in self.world.props if p.kind == "spire"]
        if not spires:
            return None
        sx = np.array([p.x for p in spires], np.float32)
        sz = np.array([p.z for p in spires], np.float32)
        sh = np.array([p.h for p in spires], np.float32)
        pick = rng.integers(0, len(spires), n)
        r = rng.random((n, 6), dtype=np.float32)
        ys = self._ground(sx[pick], sz[pick])
        return np.stack([sx[pick], ys, sz[pick], r[:, 0], sh[pick], r[:, 1], r[:, 2], r[:, 3]], 1)

    # --- per frame ---------------------------------------------------------

    def _after_rain_level(self, state, minutes: float) -> float:
        """How recently it rained (0..1), from the schedule over the past 3 h.

        Cached per game minute; the schedule is a pure function of the clock.
        """
        key = int(minutes)
        if key != self._after_rain_key:
            level = 0.0
            for step in range(1, 10):
                past = minutes - step * 20.0
                if past <= 0:
                    break
                wet = weather_visuals(past, state)["rain"]
                level = max(level, wet * (1.0 - step / 12.0))
            self._after_rain_key, self._after_rain = key, level
        return self._after_rain

    def _strengths(self, state, light) -> dict:
        """0..1 strength of each system this frame, from time, weather and place."""
        night = float(light["night"])
        gold = float(light["gold"])
        rain = float(light["rain"])
        mist = float(light.get("mist", 0.0))
        snow = float(light.get("snow", 0.0))
        shade = float(light.get("cloud_shade", 0.0))
        day = 1.0 - night
        minutes = state.game_minutes + state.minute_acc
        hour = hour_of_day(minutes)
        dawn = math.exp(-((hour - 6.4) / 1.0) ** 2)
        after = self._after_rain_level(state, minutes)
        dry = (1.0 - rain) * (1.0 - snow)
        s = {}
        s[MOTES] = day * dry * min(1.0, 0.35 + 0.75 * gold + 0.6 * after) * (1.0 - 0.6 * shade)
        s[POLLEN] = s[MOTES]
        s[RAIN] = rain
        s[SNOW] = snow
        firefly_day = False
        if self.lake in ("briar", "cedar"):
            from .calendar import lake_day
            special = lake_day(self.world.id, state.game_minutes)
            firefly_day = bool(special and getattr(special, "fireflies", False))
        dusk = min(1.0, max(0.0, (night - 0.3) / 0.35))
        s[FIREFLY] = dusk * (1.0 - rain) * (1.0 - 0.5 * mist) * (1.0 if firefly_day else 0.7)
        s[WISP] = min(1.0, mist * 1.1 + 0.85 * dawn * dry * (1.0 - night) + 0.45 * gold + 0.2 * rain)
        s[SPRING] = min(1.0, 0.55 + 0.3 * night + 0.25 * dawn + 0.2 * mist) * (1.0 - 0.4 * rain)
        s[LEAF] = 1.0 - 0.5 * snow
        s[NEEDLE] = 0.0
        if self.lake == "flathead":
            from .lakegen import larch_gold
            s[NEEDLE] = (1.0 if larch_gold(state) else 0.0) * (1.0 - 0.6 * snow)
        s[ASH] = 0.6 + 0.4 * (1.0 - rain)
        evening = min(1.0, gold * 1.3 + math.exp(-((night - 0.45) / 0.22) ** 2))
        s[INSECT] = evening * dry * (1.0 - mist)
        s[DUST] = 0.45 + 0.55 * night
        s[LANE] = 0.5 + 0.5 * night
        s[SPARKLE] = 0.4 + 0.6 * night
        return s

    def uniforms(self, state, light, cam) -> dict:
        """Frame time (frozen under Reduced Motion), drift and the wisp texture unit."""
        still = reduced_motion(state)
        t = STILL_TIME if still else float(state.anim) % 10000.0
        strengths = self._strengths(state, light)
        self._active = [(kind, strengths.get(kind, 0.0)) for kind in self.systems
                        if strengths.get(kind, 0.0) > 0.003]
        return {"p_time": t, "p_drift": self._drift, "p_wisp": PARTICLE_UNITS[0]}

    def bind(self) -> None:
        """Bind the wisp noise texture to its unit."""
        self.wisp.use(PARTICLE_UNITS[0])

    def draw(self, state, light, cam, *, mirror: float, stage: str) -> None:
        """Draw active systems: emitters in the reflection, everything in "over".

        The main pass draws at "over" (after the water) so the water plane
        cannot paint over particles that hang above it. Depth writes are off
        for the whole draw and restored afterwards.
        """
        if mirror < 0:
            if stage != "scene":
                return
            systems = [(k, s) for k, s in self._active if k in REFLECTED]
            fb = self.renderer.reflect_fb
        else:
            if stage != "over":
                return
            systems = self._active
            fb = self.renderer.draw_fb
        if not systems:
            return
        renderer = self.renderer
        ctx = renderer.ctx
        program = self.program
        renderer._uniforms(program, state, cam, light, mirror, fb.size)
        ctx.enable(moderngl.BLEND | moderngl.PROGRAM_POINT_SIZE)
        ctx.blend_func = moderngl.ONE, moderngl.ONE_MINUS_SRC_ALPHA
        fb.depth_mask = False
        try:
            for kind, strength in systems:
                vao, count = self.systems[kind]
                # Weak systems draw fewer instances; the shader fades the
                # boundary rank so density changes are smooth, never popping.
                drawn = min(count, int(math.ceil(count * min(1.0, strength) * 1.08)))
                if drawn <= 0:
                    continue
                prim = PRIMITIVE.get(kind, POINT)
                mode, vertices = _GL_MODE[prim]
                program["p_kind"].value = kind
                program["p_prim"].value = prim
                program["p_count"].value = float(count)
                program["p_density"].value = float(min(1.0, strength))
                if "p_strength" in self._members:
                    program["p_strength"].value = float(strength)
                if "p_box" in self._members:
                    program["p_box"].value = float(self.box.get(kind, 0.0))
                vao.render(mode, vertices=vertices, instances=drawn)
        finally:
            fb.depth_mask = True
            ctx.disable(moderngl.BLEND | moderngl.PROGRAM_POINT_SIZE)

    def memory_bytes(self) -> int:
        """Instance buffers plus the mipmapped wisp texture, in bytes."""
        return self._bytes
