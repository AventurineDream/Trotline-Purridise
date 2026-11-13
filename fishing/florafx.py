"""Foliage atlas bake and the flora effect layer (texture units 16-17).

`FloraAtlas` builds every billboard layer one lake needs (trees, shore plants,
lagoon flora, buoys, cat impostor slots) at `Detail.atlas_scale` into two
texture arrays of one size: colour (unit 0, the renderer's `atlas`) and light
(unit 16: normal x/y, translucency or glow, ambient occlusion). Tree and
plant recipes (`forest.tree_hd`, `sprites.sprite_hd`) are rasterised on the
GPU by `PaintBaker`; both arrays are mipmapped on the GPU, and `flora_cover`
(unit 17) holds, per layer and mip level, the alpha scale that keeps each
level's alpha-tested coverage equal to the full-size sprite's, so far tree
lines neither thin out nor bloat.

`FloraFx` binds those, sends the per-frame wind/time uniforms (held still
under Reduced Motion) and draws soft contact shading where trunks meet the
ground. All motion is pure shading: no vertex moves, no alpha animates.

Constraints: baked once per lake load, only for the kinds that lake places
(budget 1.0 s standard, 2.5 s ultra). Bake-only GL objects and CPU arrays are
released as soon as the atlas is uploaded. Runtime writers (buoy paint, cat
impostors) go through `write_sprite`, which re-mips at the next draw.
"""

from __future__ import annotations

import math
import time
from pathlib import Path

import moderngl
import numpy as np

from . import forest, sprites
from .fx import FLORA_UNITS, Fx, reduced_motion
from .weather import wind_at

ATLAS_W, ATLAS_H = forest.W, forest.H
# Alpha-test threshold every mip is normalised against (foliage.frag uses it too).
CUTOFF = 0.5
# Shore/lagoon sprites need fewer variants than trees to stop repeating.
SHORE_VARIANTS = 3
# Props drawn as plain upscaled sprites with a generic pillow normal.
PLAIN = ("heron", "duck")
GL_SAMPLE_ALPHA_TO_COVERAGE = 0x809E
GL_SAMPLE_ALPHA_TO_ONE = 0x809F


def _hash01(x: float, z: float) -> float:
    """Stable 0-1 hash of a world position (picks a prop's variant)."""
    h = math.sin(x * 12.9898 + z * 78.233) * 43758.5453
    return h - math.floor(h)


def _levels(w: int, h: int) -> int:
    return int(math.floor(math.log2(max(w, h)))) + 1


def coverage_scales(alpha: np.ndarray, levels: int, cutoff: float = CUTOFF) -> np.ndarray:
    """Per-mip alpha multipliers that keep alpha-tested coverage constant.

    Emulates the GPU's 2x2 box mip chain on the alpha channel and, for each
    level, finds the scale whose thresholded coverage matches level 0
    (Castaño, "Computing alpha mipmaps"). Levels with no coverage keep 1.

    Args:
        alpha: (H, W) float alpha of level 0 in [0, 1].
        levels: Mip levels to report.

    Returns:
        (levels,) float32 scales, clamped to [0.5, 4].
    """
    scales = np.ones(levels, np.float32)
    a = alpha.astype(np.float32)
    target = float((a >= cutoff).mean())
    if target <= 0.0:
        return scales
    for level in range(1, levels):
        h, w = a.shape
        h2, w2 = max(1, h // 2), max(1, w // 2)
        # Strided sums are several times faster than reshape().mean() here.
        if h >= 2:
            a = (a[0:h2 * 2:2] + a[1:h2 * 2:2]) * np.float32(0.5)
        if w >= 2:
            a = (a[:, 0:w2 * 2:2] + a[:, 1:w2 * 2:2]) * np.float32(0.5)
        flat = a.ravel()
        keep = int(round(target * flat.size))
        if keep <= 0:
            continue
        keep = min(keep, flat.size)
        # The keep-th largest alpha must land exactly on the cutoff.
        kth = float(np.partition(flat, flat.size - keep)[flat.size - keep])
        if kth > 1e-3:
            scales[level] = min(4.0, max(0.5, cutoff / kth))
    return scales


def _encode(rgba: np.ndarray, light: np.ndarray):
    """Float layers to bottom-up uint8 bytes for the colour and light arrays.

    Used for the plain (upscaled) sprites; painted ones get the same encoding
    from `flora_finish.frag`. Both arrays are stored premultiplied by
    coverage, so linear filtering and the GPU's box mips average only covered
    texels (no dark fringe at any distance, no need to fill the empty
    border). `foliage.frag` divides by the sampled alpha. Works in place: the
    float layers are spent afterwards.
    """
    a = rgba[..., 3:4]
    rgba[..., :3] *= a
    light[..., :2] *= 0.5
    light[..., :2] += 0.5
    light *= a
    rgba *= 255.0
    rgba += 0.5
    light *= 255.0
    light += 0.5
    return rgba[::-1].astype(np.uint8).tobytes(), light[::-1].astype(np.uint8).tobytes()


class PaintBaker:
    """Rasterises `sprites.Painter` recipes into atlas layers on the GPU.

    Per sprite: one instanced draw of its primitives with a depth test on
    height (colour, normal, height of the highest surface), one with MAX
    blending (coverage), a small NumPy pass for the soft canopy fields, then
    a finishing pass that writes the premultiplied colour and light layers.
    All GL objects here are bake-only; call `release()` when done.

    Args:
        ctx: The renderer's ModernGL context.
        width, height: Atlas layer size in texels.
    """

    def __init__(self, ctx, width: int, height: int):
        self.ctx, self.w, self.h = ctx, int(width), int(height)
        self._objects = []
        shaders = Path(__file__).with_name("shaders")

        def src(name):
            return "#version 330\n" + (shaders / name).read_text()

        own = self._own
        self.paint = own(ctx.program(vertex_shader=src("flora_paint.vert"), fragment_shader=src("flora_paint.frag")))
        self.finisher = own(ctx.program(vertex_shader=src("flora_finish.vert"),
                                        fragment_shader=src("flora_finish.frag")))
        size = (self.w, self.h)
        self.t_col = own(ctx.texture(size, 4, dtype="f2"))
        self.t_nrm = own(ctx.texture(size, 4, dtype="f2"))
        self.t_z = own(ctx.texture(size, 1, dtype="f4"))
        self.t_cov = own(ctx.texture(size, 1, dtype="f2"))
        self.o_col = own(ctx.texture(size, 4))
        self.o_light = own(ctx.texture(size, 4))
        for tex in (self.t_col, self.t_nrm, self.t_z, self.t_cov, self.o_col, self.o_light):
            tex.filter = (moderngl.NEAREST, moderngl.NEAREST)
        self.fb_paint = own(ctx.framebuffer([self.t_col, self.t_nrm, self.t_z], own(ctx.depth_renderbuffer(size))))
        self.fb_cov = own(ctx.framebuffer([self.t_cov]))
        self.fb_out = own(ctx.framebuffer([self.o_col, self.o_light]))
        corners = np.array([[0, 0], [1, 0], [1, 1], [0, 0], [1, 1], [0, 1]], np.float32)
        self.corner_buf = own(ctx.buffer(corners.tobytes()))
        self.inst = own(ctx.buffer(reserve=sprites.ROW * 4 * 512, dynamic=True))
        self.vao = own(ctx.vertex_array(self.paint, [
            (self.corner_buf, "2f", "in_corner"),
            (self.inst, "4f 4f 4f 4f 4f 4f 4f 4f /i", "in_box", "in_kind", "in_col", "in_p0", "in_p1",
             "in_p2", "in_mat", "in_tip")]))
        self.tri = own(ctx.vertex_array(self.finisher, []))
        self.reducer = own(ctx.program(vertex_shader=src("flora_finish.vert"),
                                       fragment_shader=src("flora_reduce.frag")))
        self.reduce_tri = own(ctx.vertex_array(self.reducer, []))
        self.reducer["t_cov"], self.reducer["t_z"] = 2, 4
        self.t_low = own(ctx.texture(size, 4, dtype="f4"))
        self.fb_low = own(ctx.framebuffer([self.t_low]))
        self.finisher["t_col"], self.finisher["t_nrm"], self.finisher["t_cov"], self.finisher["t_soft"] = 0, 1, 2, 3

    def _own(self, obj):
        self._objects.append(obj)
        return obj

    def bake(self, recipe, *, golds=(False,)):
        """Rasterise one recipe; returns one (cover_row, colour, light) per `golds` entry.

        `golds` lists the finishing variants to emit from one paint: the larch
        passes (False, True) to get its autumn twin with an identical
        silhouette. Colour and light are layer bytes, bottom row first.
        """
        ctx = self.ctx
        rows = recipe.array()
        base = (recipe.base_w, recipe.base_h)
        scale = (self.w / recipe.base_w, self.h / recipe.base_h)
        if rows.nbytes > self.inst.size:
            self.inst.orphan(rows.nbytes)
        if len(rows):
            self.inst.write(rows.tobytes())
        self.paint["base"], self.paint["scale"] = base, scale
        self.paint["grain_seed"] = recipe.grain_seed
        ctx.disable(moderngl.BLEND)
        ctx.enable(moderngl.DEPTH_TEST)
        ctx.depth_func = "<"
        self.fb_paint.use()
        self.fb_paint.clear(0.0, 0.0, 0.0, 0.0, depth=1.0)
        self.paint["cov_pass"] = 0
        if len(rows):
            self.vao.render(instances=len(rows))
        ctx.disable(moderngl.DEPTH_TEST)
        ctx.enable(moderngl.BLEND)
        ctx.blend_equation = moderngl.MAX
        ctx.blend_func = moderngl.ONE, moderngl.ONE
        self.fb_cov.use()
        self.fb_cov.clear(0.0, 0.0, 0.0, 0.0)
        self.paint["cov_pass"] = 1
        if len(rows):
            self.vao.render(instances=len(rows))
        ctx.blend_equation = moderngl.FUNC_ADD
        ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
        ctx.disable(moderngl.BLEND)
        # Block means on the GPU, so only a design-unit grid comes back.
        ky, kx = max(1, int(scale[1])), max(1, int(scale[0]))
        lh, lw = self.h // ky, self.w // kx
        self.t_cov.use(2)
        self.t_z.use(4)
        r = self.reducer
        r["block"], r["low"], r["layer_h"] = (kx, ky), (lw, lh), self.h
        self.fb_low.use()
        self.fb_low.viewport = (0, 0, lw, lh)
        self.reduce_tri.render(moderngl.TRIANGLES, vertices=3)
        self.fb_low.viewport = (0, 0, self.w, self.h)
        low = np.frombuffer(self.fb_low.read(viewport=(0, 0, lw, lh), components=2, dtype="f4"),
                            np.float32).reshape(lh, lw, 2)[::-1]
        opts = recipe.options
        soft = sprites.soft_fields(low[..., 0].copy(), low[..., 1].copy(), scale[0] / kx, scale[1] / ky,
                                   core=opts["core"], cavity=opts["cavity"])
        t_soft = ctx.texture((soft.shape[1], soft.shape[0]), 3, soft.tobytes(), dtype="f4")
        t_soft.filter = (moderngl.LINEAR, moderngl.LINEAR)
        t_soft.repeat_x = t_soft.repeat_y = False
        try:
            self.t_col.use(0)
            self.t_nrm.use(1)
            self.t_cov.use(2)
            t_soft.use(3)
            f = self.finisher
            f["base"], f["scale"] = base, scale
            f["contact"], f["thin_floor"], f["edge_glow"] = opts["contact"], opts["thin_floor"], opts["edge_glow"]
            out = []
            for gold in golds:
                f["gold"] = float(gold)
                self.fb_out.use()
                self.tri.render(moderngl.TRIANGLES, vertices=3)
                colour = self.o_col.read()
                alpha = np.frombuffer(colour, np.uint8)[3::4].reshape(self.h, self.w)
                out.append((coverage_scales(alpha / np.float32(255.0), _levels(self.w, self.h)),
                            colour, self.o_light.read()))
        finally:
            t_soft.release()
        return out

    def release(self) -> None:
        """Free every bake-only GL object."""
        for obj in reversed(self._objects):
            obj.release()
        self._objects.clear()


class FloraAtlas:
    """The lake's billboard layers: colour, light and coverage textures.

    Args:
        renderer: The `LakeRenderer` (its `ctx`, `own`, `world`, `detail`).
        buoy_rgb: Buoy paint, 0-1 floats.
        reserve: Blank layers kept for runtime sprites (cat impostors).

    Attributes:
        layers: Layer index by name: "<kind><variant>" for every painted
            variant, and the bare kind for its variant 0.
        colour, light: The two `TextureArray`s; `cover` the coverage table.
        reserve0: First reserved layer.
        bake_seconds: Wall time the bake took (for the load-time report).
    """

    def __init__(self, renderer, buoy_rgb, reserve: int):
        t0 = time.perf_counter()
        ctx = renderer.ctx
        detail = renderer.detail
        world = renderer.world
        self.scale = max(1, int(detail.atlas_scale))
        self.tree_variants = max(1, int(detail.foliage_variants))
        self.shore_variants = min(SHORE_VARIANTS, self.tree_variants)
        self.w, self.h = ATLAS_W * self.scale, ATLAS_H * self.scale
        self.levels = _levels(self.w, self.h)
        self.lake = world.id
        placed = {prop.kind for prop in world.props}
        plan = []  # (name, kind, variant)
        self.counts = {}
        for kind in forest.TREE_KINDS:
            if kind in placed:
                for v in range(self.tree_variants):
                    plan.append((f"{kind}{v}", kind, v))
                self.counts[kind] = self.tree_variants
                if kind == "larch":
                    for v in range(self.tree_variants):
                        plan.append((f"larchgold{v}", "larchgold", v))
                    self.counts["larchgold"] = self.tree_variants
        for kind in sorted(placed):
            if kind in sprites.HD_SPRITES:
                for v in range(self.shore_variants):
                    plan.append((f"{kind}{v}", kind, v))
                self.counts[kind] = self.shore_variants
            elif kind in PLAIN:
                plan.append((f"{kind}0", kind, 0))
                self.counts[kind] = 1
        for name in ("buoy", "buoy_flag"):
            plan.append((f"{name}0", name, 0))
            self.counts[name] = 1
        self.layers = {}
        for index, (name, kind, variant) in enumerate(plan):
            self.layers[name] = index
            if variant == 0:
                self.layers[kind] = index
        self.reserve0 = len(plan)
        self.count = len(plan) + reserve
        self.colour = renderer.own(ctx.texture_array((self.w, self.h, self.count), 4))
        self.light = renderer.own(ctx.texture_array((self.w, self.h, self.count), 4))
        self.cover_rows = np.ones((self.count, self.levels), np.float32)
        self.cover = renderer.own(ctx.texture((self.levels, self.count), 1, dtype="f4"))
        self.cover.filter = (moderngl.LINEAR, moderngl.NEAREST)
        self.cover.repeat_x = self.cover.repeat_y = False
        small = sprites.bake(tuple(c for c in buoy_rgb))
        baker = PaintBaker(ctx, self.w, self.h)
        try:
            for index, (name, kind, variant) in enumerate(plan):
                if kind == "larchgold":
                    continue  # baked with its larch twin below
                if kind in forest.TREE_KINDS:
                    recipe = forest.tree_hd(kind, variant, lake=self.lake)
                elif kind in sprites.HD_SPRITES:
                    recipe = sprites.sprite_hd(kind, variant)
                else:
                    self._store_plain(index, small[kind])
                    continue
                if kind == "larch":
                    plain, gold = baker.bake(recipe, golds=(False, True))
                    self._upload(self.layers[f"larchgold{variant}"], *gold)
                else:
                    (plain,) = baker.bake(recipe)
                self._upload(index, *plain)
        finally:
            baker.release()
        blank = bytes(self.w * self.h * 4)
        for index in range(self.reserve0, self.count):
            self.colour.write(blank, viewport=(0, 0, index, self.w, self.h, 1))
            self.light.write(blank, viewport=(0, 0, index, self.w, self.h, 1))
        for tex in (self.colour, self.light):
            tex.build_mipmaps()
            tex.filter = (moderngl.LINEAR_MIPMAP_LINEAR, moderngl.LINEAR)
            tex.repeat_x = tex.repeat_y = False
            tex.anisotropy = min(8.0, float(ctx.max_anisotropy or 1.0))
        self.cover.write(self.cover_rows.tobytes())
        self._dirty = False
        self.bake_seconds = time.perf_counter() - t0

    @property
    def layer_bytes(self) -> int:
        """GPU bytes of one layer in both arrays, mipmaps included (4/3)."""
        return self.w * self.h * 4 * 2 * 4 // 3

    def memory_bytes(self, *, include_reserve: bool) -> int:
        """GPU bytes of the painted layers (and the reserve if asked) plus the coverage table."""
        layers = self.count if include_reserve else self.reserve0
        return layers * self.layer_bytes + self.cover_rows.nbytes

    def variant(self, kind: str, x: float, z: float) -> int:
        """The painted variant a prop of `kind` at (x, z) shows; stable per position."""
        count = self.counts.get(kind, 1)
        return min(count - 1, int(_hash01(x, z) * count))

    def _upload(self, index: int, cover_row: np.ndarray, col: bytes, lit: bytes) -> None:
        self.cover_rows[index] = cover_row
        self.colour.write(col, viewport=(0, 0, index, self.w, self.h, 1))
        self.light.write(lit, viewport=(0, 0, index, self.w, self.h, 1))

    def _store_plain(self, index: int, src: np.ndarray) -> None:
        big = sprites.upscale(src, self.w, self.h)
        rgba = big.astype(np.float32) / 255.0
        light = sprites.auto_light(big, sx=self.w / src.shape[1], sy=self.h / src.shape[0])
        cover = coverage_scales(rgba[..., 3], self.levels)
        self._upload(index, cover, *_encode(rgba, light))

    def write_sprite(self, index: int, src: np.ndarray) -> None:
        """Replace one layer with a small RGBA sprite (buoy paint, cat impostor).

        The sprite is scaled up with nearest texels (crisp, not blurred) and
        given a generic pillow normal. Mipmaps and coverage refresh at the
        next `refresh()`, so several writes in one frame cost one rebuild.
        """
        self._store_plain(index, src)
        self._dirty = True

    def refresh(self) -> None:
        """Rebuild mipmaps and the coverage table after `write_sprite` calls."""
        if self._dirty:
            self.colour.build_mipmaps()
            self.light.build_mipmaps()
            self.cover.write(self.cover_rows.tobytes())
            self._dirty = False


class FloraFx(Fx):
    """Per-frame foliage light inputs and trunk contact shading.

    Uses `renderer.flora_atlas` (built at the atlas site in `_build`). Binds
    the light array to unit 16 and the coverage table to unit 17.
    """

    def __init__(self, renderer, detail):
        super().__init__(renderer, detail)
        self.atlas = renderer.flora_atlas
        ctx = renderer.ctx
        self.program = renderer.program("flora_contact.vert", "flora_contact.frag")
        rows = self._contacts(renderer)
        self.count = len(rows)
        corners = np.array([[-1, -1], [1, -1], [1, 1], [-1, -1], [1, 1], [-1, 1]], np.float32)
        self.corner_buf = renderer.own(ctx.buffer(corners.tobytes()))
        self.instance_buf = renderer.own(ctx.buffer(rows.tobytes() or bytes(28)))
        self.vao = renderer.own(ctx.vertex_array(self.program, [
            (self.corner_buf, "2f", "in_corner"),
            (self.instance_buf, "3f 3f 1f /i", "in_base", "in_normal", "in_radius")]))
        self.a2c = float(getattr(renderer, "samples", 1) > 1)

    @staticmethod
    def _contacts(renderer) -> np.ndarray:
        """One ground disc per standing tree: base point, terrain normal, radius (m)."""
        world = renderer.world
        trees = [p for p in world.props if p.kind in forest.TREE_KINDS and p.kind != "deadpine"]
        if not trees:
            return np.zeros((0, 7), np.float32)
        x = np.array([p.x for p in trees], np.float64)
        z = np.array([p.z for p in trees], np.float64)
        h = np.array([p.h for p in trees], np.float64)
        y = world.sample_height(x, z)
        e = 1.5
        dx = (world.sample_height(x + e, z) - world.sample_height(x - e, z)) / (2 * e)
        dz = (world.sample_height(x, z + e) - world.sample_height(x, z - e)) / (2 * e)
        n = np.stack([-dx, np.ones_like(dx), -dz], -1)
        n /= np.linalg.norm(n, axis=-1, keepdims=True)
        rows = np.zeros((len(trees), 7), np.float32)
        rows[:, 0], rows[:, 1], rows[:, 2] = x, y, z
        rows[:, 3:6] = n
        rows[:, 6] = np.clip(h * 0.16, 1.4, 4.0)
        # Discs whose centre is under water would only shade the lake bed.
        keep = np.asarray(world.shore_sd(x, z)) > 0.5
        return rows[keep]

    def bind(self) -> None:
        self.atlas.light.use(FLORA_UNITS[0])
        self.atlas.cover.use(FLORA_UNITS[1])

    def uniforms(self, state, light, cam) -> dict:
        still = reduced_motion(state)
        _heading, speed = wind_at(state.game_minutes + state.minute_acc, state)
        return dict(flora_light=FLORA_UNITS[0], flora_cover=FLORA_UNITS[1],
                    flora_time=0.0 if still else float(state.anim) % 3600.0,
                    flora_wind=float(min(1.6, max(0.2, speed / 6.0))),
                    flora_a2c=self.a2c, flora_levels=float(self.atlas.levels))

    def draw(self, state, light, cam, *, mirror: float, stage: str) -> None:
        if stage != "scene" or mirror < 0 or not self.count:
            return
        ctx = self.renderer.ctx
        fb = self.renderer.draw_fb
        self.renderer._uniforms(self.program, state, cam, light, mirror, fb.size)
        ctx.enable(moderngl.BLEND)
        ctx.blend_func = moderngl.DST_COLOR, moderngl.ZERO
        fb.depth_mask = False
        try:
            self.vao.render(instances=self.count)
        finally:
            fb.depth_mask = True
            ctx.blend_func = moderngl.SRC_ALPHA, moderngl.ONE_MINUS_SRC_ALPHA
            ctx.disable(moderngl.BLEND)

    def memory_bytes(self) -> int:
        """Painted atlas layers (colour + light + mips), coverage table and contact discs.

        The cat impostor reserve is reported by `LakeRenderer.actor_memory`.
        """
        return (self.atlas.memory_bytes(include_reserve=False) + self.instance_buf.size
                + self.corner_buf.size)
