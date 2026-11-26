"""Issue #167: each lake's trees and shore plants read as its own, denser, and still clear.

Per lake, on the built world, these tests check that:
- tree and shore-plant mixes differ between lakes (total-variation distance);
- the weights in `forest.pick_tree` and the low-discrepancy `index_draw` hold their shares;
- placement is deterministic per lake, and the collision set matches the pre-change build;
- tree, shore and nebula counts sit in an authored band (1.2x to 1.4x the pre-change counts);
- no tree or nebula spire sits in its landing envelope, and no shore plant sits on a route,
  in a marina clearing or in the Cedar cove;
- the leafy palette follows `sprites.LAKE_TINT`, wood stays untinted, and HD sprites differ
  per lake;
- the CPU renderer has a sprite for every placed kind.

GL checks compare the low and standard tiers: every placed kind has atlas layers, the atlas
fits the foliage budget, low has fewer variants, and the verify estimate covers the real
atlas. They skip where no standalone EGL context exists. A built world takes seconds, so
worlds and renderers are cached per test class.
"""

from __future__ import annotations

import hashlib
import math
import unittest
from collections import Counter
from functools import lru_cache
from unittest import mock

import numpy as np

from . import detail
from .forest import TREE_KINDS, index_draw, pick_tree, tree_hd
from .nebula import nebula_props
from .shoreline import _clear_route
from .sprites import Painter, sprite_hd
from .verify import MEMORY_BUDGET_MB, foliage_bytes
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
SOLID_COUNT = {"briar": 31, "cedar": 42, "flathead": 26, "crater": 28, "nebula": 54}
SOLID_SHA256 = {
    "briar": "8c53c90d9b97c9bd",
    "cedar": "190d32bb6313cdec",
    "flathead": "072c72fdbc18e6ab",
    "crater": "0bb4338780584da1",
    "nebula": "7f01f8d0c778378a",
}

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
        flathead = _mix(_world("flathead"), ("larch", "spruce"))
        self.assertAlmostEqual(flathead["larch"] / sum(flathead.values()), 0.6, delta=0.05)
        crater = _mix(_world("crater"), ("hemlock", "whitebark"))
        self.assertAlmostEqual(crater["hemlock"] / sum(crater.values()), 0.66, delta=0.05)


class DeterminismTests(unittest.TestCase):
    """A lake rebuilds to exactly the same props, so saves and renders agree."""

    def test_each_lake_rebuilds_identically(self):
        for lake in ALL_LAKES:
            with self.subTest(lake=lake):
                first = [(p.kind, p.x, p.z, p.h, p.shade) for p in _world(lake).props]
                second = [(p.kind, p.x, p.z, p.h, p.shade) for p in World(lake).props]
                self.assertEqual(first, second)


class CollisionTests(unittest.TestCase):
    """Density work leaves every solid exactly where the pre-change build put it."""

    def test_solids_match_the_pre_change_build(self):
        for lake in ALL_LAKES:
            with self.subTest(lake=lake):
                solids = np.round(np.asarray(_world(lake).solid_props, np.float64), 4)
                self.assertEqual(len(solids), SOLID_COUNT[lake])
                self.assertEqual(hashlib.sha256(solids.tobytes()).hexdigest()[:16], SOLID_SHA256[lake])


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
        np.testing.assert_allclose(after[~leafy, 8:11], before[~leafy, 8:11])
        np.testing.assert_allclose(after[leafy, 8:11],
                                   np.clip(before[leafy, 8:11] * (1.5, 1.0, 0.5), 0.0, 1.0), rtol=1e-6)

    def test_leafy_palette_orders_by_lake_gain(self):
        # Cedar's gain is warm (R/B 1.44), Briar's mild (1.11) and Flathead's cool (0.72).
        # Averaging four variants keeps seed-to-seed shading from deciding the order.
        ratio = {}
        for lake in ("cedar", "briar", "flathead"):
            red_blue = []
            for variant in range(4):
                arr = tree_hd("pine", variant, lake=lake).array()
                leafy = arr[:, 7] > 0.5
                red, _, blue = arr[leafy, 8:11].mean(axis=0)
                red_blue.append(red / blue)
            ratio[lake] = sum(red_blue) / len(red_blue)
        self.assertGreater(ratio["cedar"] / ratio["briar"], 1.1)
        self.assertGreater(ratio["briar"] / ratio["flathead"], 1.2)

    def test_hd_sprites_are_specific_to_each_lake(self):
        for kind in ("grass", "cattail"):
            with self.subTest(kind=kind):
                briar = sprite_hd(kind, 0, lake="briar").array()
                cedar = sprite_hd(kind, 0, lake="cedar").array()
                self.assertFalse(np.array_equal(briar, cedar))

    def test_tree_silhouettes_are_specific_to_each_lake(self):
        briar = tree_hd("oak", 0, lake="briar").array()
        cedar = tree_hd("oak", 0, lake="cedar").array()
        self.assertFalse(np.array_equal(briar, cedar))


class CpuSpriteTests(unittest.TestCase):
    """The CPU fallback can draw every placed tree and shore kind."""

    def test_every_placed_kind_has_a_cpu_sprite(self):
        from .software import SoftwareRenderer
        for lake in ALL_LAKES:
            with self.subTest(lake=lake):
                world = _world(lake)
                renderer = SoftwareRenderer(world, 320, 180)
                placed = {p.kind for p in world.props} & (set(TREE_KINDS) | SHORE_KINDS)
                self.assertEqual(sorted(placed - set(renderer.sprites)), [])


class AtlasTests(unittest.TestCase):
    """The painted GL flora atlas per tier; skipped where standalone EGL is unavailable."""

    @classmethod
    def setUpClass(cls):
        try:
            import moderngl
            cls.ctx = moderngl.create_standalone_context(require=330, backend="egl")
        except Exception as error:  # no EGL device or driver on this machine
            raise unittest.SkipTest(f"Standalone EGL unavailable: {error}")
        cls.renderers = {}

    @classmethod
    def tearDownClass(cls):
        for renderer in cls.renderers.values():
            renderer.close()
        cls.renderers.clear()

    def _bake(self, lake: str, tier: str):
        """The lake's GL renderer at `tier`, baked once per class and reused."""
        key = (lake, tier)
        if key not in self.renderers:
            from .glrender import LakeRenderer
            with mock.patch.object(detail, "_current", detail.TIERS[tier]):
                self.renderers[key] = LakeRenderer(_world(lake), 320, 180, context=self.ctx)
        return self.renderers[key]

    def test_placed_kinds_have_layers_and_the_atlas_fits_the_budget(self):
        budget = MEMORY_BUDGET_MB["foliage"] * 1024 * 1024
        for lake in ALL_LAKES:
            for tier in ("low", "standard"):
                with self.subTest(lake=lake, tier=tier):
                    renderer = self._bake(lake, tier)
                    kinds = {p.kind for p in _world(lake).props}
                    self.assertEqual(sorted(k for k in kinds if f"{k}0" not in renderer.layers), [])
                    self.assertLessEqual(renderer.flora_atlas.memory_bytes(include_reserve=False), budget)

    def test_low_tier_has_fewer_variants_than_standard(self):
        for lake in TREE_LAKES:
            with self.subTest(lake=lake):
                self.assertLess(len(self._bake(lake, "low").layers),
                                len(self._bake(lake, "standard").layers))

    def test_verify_estimate_covers_the_real_atlas(self):
        for lake in TREE_LAKES:
            with self.subTest(lake=lake):
                low, standard = self._bake(lake, "low"), self._bake(lake, "standard")
                for renderer in (low, standard):
                    self.assertGreaterEqual(foliage_bytes(renderer),
                                            renderer.flora_atlas.memory_bytes(include_reserve=False))
                self.assertGreater(foliage_bytes(standard), foliage_bytes(low))


if __name__ == "__main__":
    unittest.main()
