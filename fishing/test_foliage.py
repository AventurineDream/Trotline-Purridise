"""Issue #167: each lake's trees and shore plants read as its own, denser, and still clear.

Per lake, on the built world, these tests check that:
- tree and shore-plant mixes differ between lakes (total-variation distance);
- the weights in `forest.pick_tree` and the low-discrepancy `index_draw` hold their shares;
- placement is deterministic per lake, and the collision set matches the pre-change build;
- tree, shore and nebula counts sit in an authored band (1.2x to 1.4x the pre-change counts);
- no tree or nebula spire sits in its landing envelope, and no shore plant sits on a route,
  in a marina clearing or in the Cedar cove;
- the leafy palette follows `sprites.LAKE_TINT` on the GL atlas and on the CPU canopies and
  shore plants, while wood, bark and stone stay untinted, and HD sprites and tree silhouettes
  differ per lake;
- leaves fall from the trees Briar and Cedar place, and from Flathead's birches;
- the CPU renderer has a sprite for every placed kind.

GL checks cover every tier and lake: every placed kind has atlas layers, the painted atlas fits
the foliage budget, variants never fall as the tier rises, the layer count and bytes match the
GPU textures, low has fewer variants than standard, and the verify estimate equals the real
painted bytes. They skip where no standalone
EGL context exists. A built world takes seconds, so worlds are cached per module; each atlas is
freed after its check, since the ultra tier's atlas alone is hundreds of MiB.
"""

from __future__ import annotations

import json
import math
import unittest
from collections import Counter
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import numpy as np

from . import detail, florafx
from .actors import MAX_ACTORS
from .data import paint_rgb
from .forest import TREE_KINDS, index_draw, pick_tree, tree, tree_hd
from .nebula import nebula_props
from .particlefx import LEAF_KINDS
from .shoreline import _clear_route
from .sprites import LAKE_TINT, Painter, bake, sprite_hd
from .verify import foliage_bytes
from .world import Prop, World

TREE_LAKES = ("briar", "cedar", "flathead", "crater")
ALL_LAKES = (*TREE_LAKES, "nebula")
SHORE_KINDS = frozenset(("cattail", "grass", "flowers", "shrub", "driftwood", "shore_stone",
                         "palmetto", "heron", "duck"))
NEBULA_SCENERY = ("spire", "lightreed", "starlily")

# Pre-change counts at origin/main 413bbcf. Crater's tree count includes its 12 deadpine snags,
# which are tree kinds too. The authored band for each count is 1.2x to 1.4x.
BASE_TREES = {"briar": 752, "cedar": 2423, "flathead": 560, "crater": 432}
BASE_SHORE = {"briar": 304, "cedar": 327, "flathead": 386, "crater": 332}
BASE_NEBULA = {"spire": 110, "lightreed": 70, "starlily": 29}

# The collision set is pinned: density work must not move a single solid (rocks, stumps, knees,
# deadpine snags, kelp and meteors), because solids are walls the boat and fish collide with.
# The fixture holds the pre-change (x, z, radius) rows in metres. They are compared within a
# tolerance, not by hashing their bytes, because NumPy's trig can differ in the last bits between
# CPUs (it dispatches SIMD kernels per machine), which flips a hash of rounded floats on CI.
SOLIDS_FIXTURE = Path(__file__).with_name("fixtures") / "foliage_solids.json"
SOLID_TOLERANCE_M = 1e-3

# Slip-local (a, s) in metres: trees and spires are kept out of lo < a < hi with |s| < half.
LANDING_ENVELOPE = {
    "briar": (-4.0, 30.0, 20.0),
    "cedar": (-8.0, 35.0, 22.0),
    "flathead": (-60.0, 75.0, 85.0),
    "crater": (-65.0, 80.0, 85.0),
    "nebula": (-60.0, 75.0, 85.0),
}


@lru_cache(maxsize=None)
def _world(lake: str) -> World:
    """The lake's built world, cached for this module because a build takes seconds.

    Args:
        lake: A lake id such as "briar".

    Returns:
        The `World` built from that lake's content.
    """
    return World(lake)


def _count(world: World, kinds) -> int:
    """How many placed props have a kind in `kinds`."""
    return sum(1 for p in world.props if p.kind in kinds)


def _mix(world: World, kinds) -> Counter:
    """Histogram of placed props whose kind is in `kinds`."""
    return Counter(p.kind for p in world.props if p.kind in kinds)


def _tv(a: Counter, b: Counter) -> float:
    """Total-variation distance between two histograms: 0 identical, 1 disjoint.

    Args:
        a: Histogram of kind counts for one lake.
        b: Histogram of kind counts for another lake.

    Returns:
        A distance in [0, 1]; each histogram is normalised before comparison.
    """
    na, nb = sum(a.values()), sum(b.values())
    return 0.5 * sum(abs(a[k] / na - b[k] / nb) for k in set(a) | set(b))


class LakeIdentityTests(unittest.TestCase):
    """Each lake's species mix and shore mix differ from every other lake's."""

    def test_tree_mixes_differ_pairwise(self):
        for i, a in enumerate(TREE_LAKES):
            for b in TREE_LAKES[i + 1:]:
                with self.subTest(a=a, b=b):
                    distance = _tv(_mix(_world(a), TREE_KINDS), _mix(_world(b), TREE_KINDS))
                    self.assertGreaterEqual(distance, 0.4)

    def test_shore_mixes_differ_pairwise(self):
        for i, a in enumerate(TREE_LAKES):
            for b in TREE_LAKES[i + 1:]:
                with self.subTest(a=a, b=b):
                    distance = _tv(_mix(_world(a), SHORE_KINDS), _mix(_world(b), SHORE_KINDS))
                    self.assertGreaterEqual(distance, 0.25)


class MixWeightTests(unittest.TestCase):
    """The draw-to-kind mapping honours the authored weights."""

    def test_pick_tree_splits_the_unit_interval_by_weight(self):
        # Briar's north row is pine 0.5, oak 0.25, birch 0.25: cumulative edges 0.5, 0.75, 1.0.
        self.assertEqual(pick_tree("briar", "north", 0.0), "pine")
        self.assertEqual(pick_tree("briar", "north", 0.49), "pine")
        self.assertEqual(pick_tree("briar", "north", 0.6), "oak")
        self.assertEqual(pick_tree("briar", "north", 0.8), "birch")
        self.assertEqual(pick_tree("briar", "north", 0.999), "birch")

    def test_index_draw_is_bounded_and_even(self):
        draws = [index_draw(i) for i in range(720)]
        self.assertTrue(all(0.0 <= d < 1.0 for d in draws))
        self.assertAlmostEqual(sum(d < 0.6 for d in draws) / 720, 0.6, delta=0.01)

    def test_realised_flathead_and_crater_mixes_follow_weights(self):
        for lake, weights in (("flathead", {"larch": 0.45, "spruce": 0.30, "birch": 0.25}),
                              ("crater", {"hemlock": 0.50, "whitebark": 0.25, "pine": 0.25})):
            with self.subTest(lake=lake):
                counts = _mix(_world(lake), tuple(weights))
                total = sum(counts.values())
                for kind, weight in weights.items():
                    self.assertAlmostEqual(counts[kind] / total, weight, delta=0.05)


class DeterminismTests(unittest.TestCase):
    """A lake rebuilds to exactly the same props, so saves and renders agree."""

    def test_each_lake_rebuilds_identically(self):
        for lake in ALL_LAKES:
            with self.subTest(lake=lake):
                first = [(p.kind, p.x, p.z, p.h, p.shade) for p in _world(lake).props]
                second = [(p.kind, p.x, p.z, p.h, p.shade) for p in World(lake).props]
                self.assertEqual(first, second)


class CollisionTests(unittest.TestCase):
    """Density work leaves every solid where the pre-change build put it, to the millimetre."""

    def test_solids_match_the_pre_change_build(self):
        expected = json.loads(SOLIDS_FIXTURE.read_text(encoding="utf-8"))["solids"]
        for lake in ALL_LAKES:
            with self.subTest(lake=lake):
                solids = np.asarray(_world(lake).solid_props, np.float64)
                pinned = np.asarray(expected[lake], np.float64)
                self.assertEqual(solids.shape, pinned.shape)
                np.testing.assert_allclose(solids, pinned, rtol=0.0, atol=SOLID_TOLERANCE_M)


class DensityTests(unittest.TestCase):
    """Counts sit in the authored band: denser than before, but within the caps."""

    def test_trees_within_authored_band(self):
        for lake in TREE_LAKES:
            with self.subTest(lake=lake):
                count = _count(_world(lake), TREE_KINDS)
                self.assertGreaterEqual(count, 1.2 * BASE_TREES[lake])
                self.assertLessEqual(count, 1.4 * BASE_TREES[lake])

    def test_shore_details_within_authored_band(self):
        for lake in TREE_LAKES:
            with self.subTest(lake=lake):
                count = _count(_world(lake), SHORE_KINDS)
                self.assertGreaterEqual(count, 1.2 * BASE_SHORE[lake])
                self.assertLessEqual(count, 1.4 * BASE_SHORE[lake])

    def test_nebula_scenery_within_authored_band(self):
        counts = Counter(p.kind for p in _world("nebula").props)
        for kind, base in BASE_NEBULA.items():
            with self.subTest(kind=kind):
                self.assertGreaterEqual(counts[kind], 1.2 * base)
                self.assertLessEqual(counts[kind], 1.4 * base)


class ClearanceTests(unittest.TestCase):
    """Landings, routes, the marina and the Cedar cove stay open."""

    def test_trees_and_spires_stay_out_of_landing_envelopes(self):
        for lake, (lo, hi, half) in LANDING_ENVELOPE.items():
            with self.subTest(lake=lake):
                world = _world(lake)
                kinds = NEBULA_SCENERY[:1] if lake == "nebula" else TREE_KINDS
                inside = []
                for p in world.props:
                    if p.kind not in kinds:
                        continue
                    a, s = (float(v) for v in world.slip.local(p.x, p.z))
                    if lo < a < hi and abs(s) < half:
                        inside.append((p.kind, round(p.x, 1), round(p.z, 1)))
                self.assertEqual(inside, [])

    def test_extra_spires_clear_the_landing_for_many_seeds(self):
        """The nebula's denser spires keep the landing clear for every seed, not just one."""
        world = _world("nebula")
        lo, hi, half = LANDING_ENVELOPE["nebula"]
        seed = int(world.environment["seed"])
        for offset in range(32):
            with self.subTest(seed=seed + offset):
                with mock.patch.dict(world.environment, {"seed": seed + offset}):
                    spires = [p for p in nebula_props(world, Prop) if p.kind == "spire"]
                inside = []
                for p in spires:
                    a, s = (float(v) for v in world.slip.local(p.x, p.z))
                    if lo < a < hi and abs(s) < half:
                        inside.append((round(p.x, 1), round(p.z, 1)))
                self.assertEqual(inside, [])

    def test_trees_stay_out_of_the_marina_clearing(self):
        for lake in TREE_LAKES:
            with self.subTest(lake=lake):
                world = _world(lake)
                trees = [p for p in world.props if p.kind in TREE_KINDS]
                self.assertEqual([p for p in trees if world._in_marina_clearing(p.x, p.z)], [])

    def test_shore_plants_keep_routes_marina_and_cove_clear(self):
        for lake in TREE_LAKES:
            with self.subTest(lake=lake):
                world = _world(lake)
                shore = [p for p in world.props if p.kind in SHORE_KINDS]
                self.assertTrue(shore)
                self.assertEqual([p for p in shore if not _clear_route(world, p.x, p.z)], [])
                self.assertEqual([p for p in shore if world._in_marina_clearing(p.x, p.z)], [])
                if lake == "cedar":
                    cove = [p for p in shore if math.hypot(p.x - 181.25, p.z + 858.36) < 35]
                    self.assertEqual(cove, [])


def _geometry(rows: np.ndarray) -> np.ndarray:
    """Primitive rows without their colour columns (body RGB 8-10, tip RGB 28-30).

    Shape and placement only, so a comparison is not decided by the lake's palette.
    """
    return np.delete(rows, (8, 9, 10, 28, 29, 30), axis=1)


class PaletteTests(unittest.TestCase):
    """Lake palettes tint leaves only, and each lake's sprites are its own."""

    def test_tint_changes_leaves_and_not_wood(self):
        p = Painter(64, 64, 7, grain="leaf")
        p.blob(20, 20, 6, 4, (90, 140, 60), leafy=1.0, z=4.0)
        p.blob(44, 20, 6, 4, (90, 140, 60), leafy=0.0, z=4.0)
        before = p.array().copy()
        p.tint((1.5, 1.0, 0.5))
        after = p.array()
        leafy = before[:, 7] > 0.5
        self.assertTrue(leafy.any() and (~leafy).any())
        # The body colour (8-10) and the tip colour (28-30) both take the gain, on leafy rows only.
        for cols in (slice(8, 11), slice(28, 31)):
            np.testing.assert_allclose(after[~leafy, cols], before[~leafy, cols])
            np.testing.assert_allclose(after[leafy, cols],
                                       np.clip(before[leafy, cols] * (1.5, 1.0, 0.5), 0.0, 1.0), rtol=1e-6)

    def test_leafy_palette_orders_by_lake_gain(self):
        # Mean R/B of the pine canopy over four variants, so seed shading does not decide the
        # order. The gains' own R/B are 1.44 (Cedar), 1.11 (Briar), 0.90 (Crater), 0.72 (Flathead).
        ratio = {}
        for lake in ("cedar", "briar", "crater", "flathead"):
            red_blue = []
            for variant in range(4):
                arr = tree_hd("pine", variant, lake=lake).array()
                leafy = arr[:, 7] > 0.5
                red, _, blue = arr[leafy, 8:11].mean(axis=0)
                red_blue.append(red / blue)
            ratio[lake] = sum(red_blue) / len(red_blue)
        for warmer, cooler in (("cedar", "briar"), ("briar", "crater"), ("crater", "flathead")):
            with self.subTest(warmer=warmer, cooler=cooler):
                self.assertGreater(ratio[warmer] / ratio[cooler], 1.15)

    def test_hd_sprites_are_specific_to_each_lake(self):
        for kind in ("grass", "cattail"):
            with self.subTest(kind=kind):
                briar = sprite_hd(kind, 0, lake="briar").array()
                cedar = sprite_hd(kind, 0, lake="cedar").array()
                self.assertFalse(np.array_equal(_geometry(briar), _geometry(cedar)))

    def test_tree_silhouettes_are_specific_to_each_lake(self):
        for i, a in enumerate(TREE_LAKES):
            for b in TREE_LAKES[i + 1:]:
                with self.subTest(a=a, b=b):
                    first = tree_hd("oak", 0, lake=a).array()
                    second = tree_hd("oak", 0, lake=b).array()
                    self.assertFalse(np.array_equal(_geometry(first), _geometry(second)))


class CpuSpriteTests(unittest.TestCase):
    """The CPU fallback draws every placed tree and shore kind, tinting their leafy parts per lake."""

    def test_every_placed_kind_has_a_cpu_sprite(self):
        from .software import SoftwareRenderer
        for lake in ALL_LAKES:
            with self.subTest(lake=lake):
                world = _world(lake)
                renderer = SoftwareRenderer(world, 320, 180)
                placed = {p.kind for p in world.props} & (set(TREE_KINDS) | SHORE_KINDS)
                self.assertEqual(sorted(placed - set(renderer.sprites)), [])

    def test_cpu_canopy_carries_each_lake_palette(self):
        from .software import SoftwareRenderer
        plain = bake(paint_rgb("buoy", "orange"))
        for lake in TREE_LAKES:
            world = _world(lake)
            renderer = SoftwareRenderer(world, 320, 180)
            kinds = {p.kind for p in world.props} & (set(TREE_KINDS) - {"deadpine"})
            for kind in sorted(kinds):
                with self.subTest(lake=lake, kind=kind):
                    reference = plain[kind] if kind in plain else tree(kind, 0)
                    canopy = renderer.sprites[kind]
                    changed = (canopy[..., :3] != reference[..., :3]).any(axis=-1)
                    self.assertTrue(changed.any())
                    for channel in (0, 2):
                        ratio = (canopy[changed, channel].astype(float).sum()
                                 / reference[changed, channel].astype(float).sum())
                        self.assertAlmostEqual(ratio, LAKE_TINT[lake][channel], delta=0.02)

    def test_cpu_trunks_and_wood_stay_untinted(self):
        plain = bake(paint_rgb("buoy", "orange"))
        wood = {"pine": np.s_[100:110, 22:35], "oak": np.s_[76:86, 28:46],
                "cypress": np.s_[110:125, 22:26]}
        for lake in TREE_LAKES:
            tinted = bake(paint_rgb("buoy", "orange"), lake=lake)
            for kind, region in wood.items():
                with self.subTest(lake=lake, kind=kind):
                    np.testing.assert_array_equal(tinted[kind][region], plain[kind][region])
            with self.subTest(lake=lake, kind="deadpine"):
                np.testing.assert_array_equal(tree("deadpine", 0, lake=lake), tree("deadpine", 0))
            for kind in TREE_KINDS:
                with self.subTest(lake=lake, kind=kind):
                    band = np.s_[230:250, 74:86]  # below every crown, so only trunk pixels
                    np.testing.assert_array_equal(tree(kind, 0, lake=lake)[band], tree(kind, 0)[band])

    def test_cpu_shore_plants_take_the_palette_on_leafy_parts_only(self):
        from .software import SoftwareRenderer
        plain = bake(paint_rgb("buoy", "orange"))
        plants = ("reed", "cattail", "grass", "flowers", "shrub", "palmetto")
        # Dry wood that the leafy builders paint over their green parts: reed sheaths,
        # cattail seed heads and shrub stems must keep their colours.
        wood = {"reed": [(92, 64, 36)],
                "cattail": [(89, 60, 35), (135, 97, 55), (125, 116, 72)],
                "shrub": [(89, 75, 48)]}
        for lake in TREE_LAKES:
            world = _world(lake)
            renderer = SoftwareRenderer(world, 320, 180)
            placed = {p.kind for p in world.props} & set(plants)
            self.assertTrue(placed, lake)
            for kind in ("rock", "stump", "knee", "driftwood", "shore_stone"):
                with self.subTest(lake=lake, kind=kind):
                    np.testing.assert_array_equal(renderer.sprites[kind], plain[kind])
            for kind in sorted(placed):
                with self.subTest(lake=lake, kind=kind):
                    reference, sprite = plain[kind], renderer.sprites[kind]
                    changed = (sprite[..., :3] != reference[..., :3]).any(axis=-1)
                    self.assertTrue(changed.any())
                    for channel in range(3):
                        ratio = (sprite[changed, channel].astype(float).sum()
                                 / reference[changed, channel].astype(float).sum())
                        self.assertAlmostEqual(ratio, LAKE_TINT[lake][channel], delta=0.02)
                    for colour in wood.get(kind, ()):
                        dry = (reference[..., :3] == colour).all(axis=-1) & (reference[..., 3] > 0)
                        self.assertTrue(dry.any())
                        np.testing.assert_array_equal(sprite[dry], reference[dry])


def _gpu_layer_bytes(tex) -> int:
    """Bytes one layer of a GL texture holds, mip chain included, from GL's own attributes.

    Args:
        tex: A moderngl texture with `width`, `height`, `components` and a `dtype` of 'f1'
            (one byte per channel) or 'f4'.

    Returns:
        The sum over the full chain of floor(log2(longest side)) + 1 levels, each at least
        1x1, times the bytes per texel.
    """
    width, height = tex.width, tex.height
    levels = int(math.floor(math.log2(max(width, height)))) + 1
    texels = sum(max(1, width >> level) * max(1, height >> level) for level in range(levels))
    return texels * tex.components * {"f1": 1, "f4": 4}[tex.dtype]


class _StubRenderer:
    """The four attributes `FloraAtlas` reads from a renderer, with no scene behind them."""

    def __init__(self, ctx, tier, world):
        self.ctx = ctx
        self.detail = tier
        self.world = world

    def own(self, obj):
        """Ownership is not tracked here: each check frees its own atlas."""
        return obj


def _briar_slots() -> tuple[int, int, int]:
    """Briar's real (tree, shore, fixed) layer slots, read from its built world."""
    return florafx.layer_slots({prop.kind for prop in _world("briar").props})


def _budget_layers(scale: int) -> int:
    """Painted layers the foliage budget holds at atlas `scale`.

    Args:
        scale: Atlas scale (texels per base texel), as `Detail.atlas_scale` gives it.

    Returns:
        Whole layers that fit `FOLIAGE_BUDGET_MB`, counted the way `FloraAtlas` counts them.
    """
    width, height = florafx.ATLAS_W * scale, florafx.ATLAS_H * scale
    layer_bytes = florafx._layer_bytes(width, height, florafx._levels(width, height))
    return detail.FOLIAGE_BUDGET_MB * detail.MIB // layer_bytes


class FoliageFitTests(unittest.TestCase):
    """The variant trade-off under the foliage budget, computed without GL."""

    def test_full_targets_are_kept_when_the_budget_allows(self):
        self.assertEqual(florafx.fit_variants(4, 10, 4, tree_target=6, shore_target=3,
                                              budget_layers=66), (6, 3))

    def test_briar_ultra_keeps_full_targets_at_scale_three(self):
        # Read from the real world, so a species added to Briar changes the answer here.
        ultra = detail.TIERS["ultra"]
        shore_target = min(florafx.SHORE_VARIANTS, ultra.foliage_variants)
        fit = florafx.fit_variants(*_briar_slots(), tree_target=ultra.foliage_variants,
                                   shore_target=shore_target,
                                   budget_layers=_budget_layers(ultra.atlas_scale))
        self.assertEqual(fit, (ultra.foliage_variants, shore_target))

    def test_scale_four_would_cut_briar_below_high(self):
        # Why ultra paints at scale 3: at scale 4 Briar's real layers keep fewer tree variants
        # than high's target.
        ultra = detail.TIERS["ultra"]
        shore_target = min(florafx.SHORE_VARIANTS, ultra.foliage_variants)
        trees, _ = florafx.fit_variants(*_briar_slots(), tree_target=ultra.foliage_variants,
                                        shore_target=shore_target, budget_layers=_budget_layers(4))
        self.assertLess(trees, detail.TIERS["high"].foliage_variants)

    def test_chosen_pair_always_fits_when_one_each_fits(self):
        for budget in range(18, 80):
            trees, shores = florafx.fit_variants(4, 10, 4, tree_target=8, shore_target=3,
                                                 budget_layers=budget)
            with self.subTest(budget=budget):
                self.assertLessEqual(4 * trees + 10 * shores + 4, budget)

    def test_chosen_pair_keeps_the_best_smaller_share_at_every_budget(self):
        # Exhaustive over the pairs that fit: no other fitting pair keeps a larger smaller share.
        for budget in range(14, 80):
            with self.subTest(budget=budget):
                trees, shores = florafx.fit_variants(4, 6, 4, tree_target=8, shore_target=3,
                                                     budget_layers=budget)
                self.assertLessEqual(4 * trees + 6 * shores + 4, budget)
                best = max(min(t / 8, s / 3) for t in range(1, 9) for s in range(1, 4)
                           if 4 * t + 6 * s + 4 <= budget)
                self.assertAlmostEqual(min(trees / 8, shores / 3), best, places=12)

    def test_falls_back_to_one_each_when_nothing_fits(self):
        self.assertEqual(florafx.fit_variants(4, 10, 4, tree_target=8, shore_target=3,
                                              budget_layers=17), (1, 1))

    def test_layer_slots_split_by_what_they_scale_with(self):
        # The gold larch twin scales with the trees; buoys and plain props never vary.
        self.assertEqual(florafx.layer_slots({"oak", "larch", "spruce", "grass", "heron"}), (4, 1, 3))
        self.assertEqual(florafx.layer_slots(set()), (0, 0, 2))


class LeafDropTests(unittest.TestCase):
    """Leaves fall from the species each lake places, so the drops match the trees in view."""

    def test_briar_and_cedar_shed_from_every_tree_they_place(self):
        for lake in ("briar", "cedar"):
            with self.subTest(lake=lake):
                placed = {p.kind for p in _world(lake).props} & set(TREE_KINDS)
                self.assertEqual(set(LEAF_KINDS[lake]), placed)

    def test_flathead_sheds_from_its_birches_and_crater_sheds_none(self):
        self.assertEqual(LEAF_KINDS["flathead"], ("birch",))
        self.assertGreater(_count(_world("flathead"), ("birch",)), 0)
        self.assertNotIn("crater", LEAF_KINDS)


class AtlasTests(unittest.TestCase):
    """The painted GL flora atlas for every lake and tier; skipped where standalone EGL is unavailable."""

    @classmethod
    def setUpClass(cls):
        try:
            import moderngl
            cls.ctx = moderngl.create_standalone_context(require=330, backend="egl")
        except Exception as error:  # no EGL device or driver on this machine
            raise unittest.SkipTest(f"Standalone EGL unavailable: {error}")

    def _flora(self, lake: str, tier: str):
        """A freshly painted atlas for `lake` at `tier`; the caller frees it with `_free`.

        Built on `_StubRenderer` rather than a full `LakeRenderer`: the atlas is the only GL
        object these checks read, and a full scene per tier would hold several ultra atlases.
        """
        stub = _StubRenderer(self.ctx, detail.TIERS[tier], _world(lake))
        return florafx.FloraAtlas(stub, paint_rgb("buoy", "orange"), MAX_ACTORS)

    @staticmethod
    def _free(flora):
        for tex in (flora.colour, flora.light, flora.cover):
            tex.release()

    def test_placed_kinds_have_layers_and_the_atlas_fits_the_budget(self):
        """Each lake and tier paints its target variants inside the budget.

        Variants never fall as the tier rises, for trees or shore plants.
        """
        budget = detail.FOLIAGE_BUDGET_MB * 1024 * 1024
        counts = {}  # lake -> tier -> (tree_variants, shore_variants), for the ordering check
        for lake in ALL_LAKES:
            counts[lake] = {}
            for tier in detail.ORDER:
                with self.subTest(lake=lake, tier=tier):
                    flora = self._flora(lake, tier)
                    try:
                        counts[lake][tier] = (flora.tree_variants, flora.shore_variants)
                        # A species that takes layers from the budget lowers these counts, so
                        # this fails until the budget is decided again.
                        tree_target = detail.TIERS[tier].foliage_variants
                        self.assertEqual(counts[lake][tier],
                                         (tree_target, min(florafx.SHORE_VARIANTS, tree_target)))
                        placed = {p.kind for p in _world(lake).props}
                        self.assertEqual(sorted(k for k in placed if f"{k}0" not in flora.layers), [])
                        trees, shores, fixed = florafx.layer_slots(placed)
                        self.assertEqual(flora.reserve0,
                                         trees * flora.tree_variants + shores * flora.shore_variants + fixed)
                        self.assertLessEqual(flora.memory_bytes(include_reserve=False), budget)
                    finally:
                        self._free(flora)
        # A higher tier never paints fewer variants, for trees or shore plants, on any lake.
        for lake in ALL_LAKES:
            for axis, name in ((0, "tree"), (1, "shore")):
                with self.subTest(lake=lake, variants=name):
                    per_tier = [counts[lake][tier][axis] for tier in detail.ORDER]
                    self.assertEqual(per_tier, sorted(per_tier))

    def test_atlas_bytes_match_the_gpu_textures(self):
        for lake, tier in (("briar", "standard"), ("briar", "ultra")):
            with self.subTest(lake=lake, tier=tier):
                flora = self._flora(lake, tier)
                try:
                    for tex in (flora.colour, flora.light):
                        self.assertEqual((tex.width, tex.height, tex.layers, tex.components,
                                          tex.dtype), (flora.w, flora.h, flora.count, 4, "f1"))
                    self.assertEqual(flora.levels,
                                     int(math.floor(math.log2(max(flora.w, flora.h)))) + 1)
                    self.assertEqual(flora.layer_bytes, 2 * _gpu_layer_bytes(flora.colour))
                    self.assertEqual((flora.cover.width, flora.cover.height),
                                     (flora.levels, flora.count))
                    self.assertEqual(flora.cover.width * flora.cover.height * 4,
                                     flora.cover_rows.nbytes)
                    self.assertEqual(flora.memory_bytes(include_reserve=False),
                                     flora.reserve0 * flora.layer_bytes + flora.cover_rows.nbytes)
                finally:
                    self._free(flora)

    def test_low_tier_has_fewer_variants_than_standard(self):
        for lake in TREE_LAKES:
            with self.subTest(lake=lake):
                low = self._flora(lake, "low")
                standard = self._flora(lake, "standard")
                try:
                    self.assertLess(low.tree_variants, standard.tree_variants)
                finally:
                    self._free(low)
                    self._free(standard)

    def test_verify_estimate_matches_the_painted_gpu_bytes(self):
        for lake in TREE_LAKES:
            for tier in ("low", "standard", "ultra"):
                with self.subTest(lake=lake, tier=tier):
                    flora = self._flora(lake, tier)
                    try:
                        painted = flora.reserve0 * 2 * _gpu_layer_bytes(flora.colour)
                        cover = flora.cover.width * flora.cover.height * 4
                        self.assertEqual(foliage_bytes(SimpleNamespace(flora_atlas=flora)),
                                         painted + cover)
                    finally:
                        self._free(flora)


if __name__ == "__main__":
    unittest.main()
