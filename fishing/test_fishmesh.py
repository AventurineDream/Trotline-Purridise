"""Parametric fish anatomy, watercolor card, and cache regressions."""

from copy import deepcopy
import unittest

from .content import ContentError, load_content_v2, validate_content_v2
from .data import CONTENT_V2_RAW
from .fishmesh import (
    CARD_CACHE_ENTRIES,
    CARD_SIZE,
    THUMBNAIL_SIZE,
    FishCardPainter,
    card_cache_limit_bytes,
    cache_bytes,
    clear_caches,
    fish_card,
    fish_card_contact_sheet,
    fish_look,
    fish_thumbnail,
    haul_mesh,
    _card_cached,
    _thumbnail_cached,
)


class FishMeshChecks(unittest.TestCase):
    def tearDown(self):
        clear_caches()

    def test_every_existing_species_has_an_anatomical_look(self):
        species = load_content_v2().species
        self.assertEqual(len(species), 36)
        self.assertTrue(all(isinstance(row.get("look"), dict) for row in species.values()))
        self.assertGreaterEqual(fish_look("channel")["barbels"], 4)
        self.assertGreater(fish_look("alligator_gar")["snout"], 0.5)
        self.assertLess(fish_look("bluegill")["length_depth_ratio"], 3.0)
        self.assertIn("sunfish", fish_look("bluegill")["family"])

    def test_look_schema_rejects_unknown_families_and_out_of_range_ratios(self):
        broken = deepcopy(CONTENT_V2_RAW)
        look = broken["species.json"]["species"][0]["look"]
        look["family"] = "made_up"
        look["length_depth_ratio"] = 9.0

        with self.assertRaises(ContentError) as caught:
            validate_content_v2(broken)

        self.assertIn("species.json:species[0](bluegill).look.family", str(caught.exception))
        self.assertIn("species.json:species[0](bluegill).look.length_depth_ratio", str(caught.exception))

    def test_haul_mesh_is_a_bounded_read_only_triangle_mesh_and_shiny_changes_paint(self):
        normal = haul_mesh("bluegill", "briar", False)
        shiny = haul_mesh("bluegill", "briar", True)

        self.assertGreaterEqual(normal.triangle_count, 1450)
        self.assertLessEqual(normal.triangle_count, 1650)
        self.assertEqual(normal.triangles.shape, (normal.triangle_count, 3))
        self.assertEqual(normal.colors.shape, (normal.triangle_count, 3))
        self.assertFalse(normal.vertices.flags.writeable)
        self.assertTrue((normal.normals == normal.normals).all())
        self.assertFalse((normal.colors == shiny.colors).all())
        self.assertIs(normal, haul_mesh("bluegill", "briar", False))

    def test_watercolor_cards_and_book_thumbnails_are_stable_and_distinct(self):
        card = fish_card("channel")
        shiny = fish_card("channel", True)
        thumbnail = fish_thumbnail("channel")

        self.assertEqual(card.shape, (CARD_SIZE[1], CARD_SIZE[0], 3))
        self.assertEqual(shiny.shape, card.shape)
        self.assertEqual(thumbnail.shape, (THUMBNAIL_SIZE[1], THUMBNAIL_SIZE[0], 3))
        self.assertGreater(int(abs(card.astype("int16") - shiny.astype("int16")).sum()), 100000)
        self.assertIs(card, fish_card("channel"))
        self.assertIs(thumbnail, fish_thumbnail("channel"))
        self.assertFalse(card.flags.writeable)

    def test_signature_anatomy_survives_the_field_guide_card(self):
        channel = fish_card("channel")
        whisker_area = channel[105:151, 455:490]
        dark_whisker_pixels = ((whisker_area[:, :, 0] < 90) &
                               (whisker_area[:, :, 1] < 90) &
                               (whisker_area[:, :, 2] < 90)).sum()
        self.assertGreater(dark_whisker_pixels, 50)

        gar = fish_card("alligator_gar")
        snout_tip = gar[120:137, 470:500]
        self.assertLess(int(snout_tip.mean()), 200)

    def test_gl_paint_pass_compiles_and_preserves_card_orientation_when_available(self):
        try:
            import moderngl
        except ImportError:
            self.skipTest("ModernGL is not installed in this environment")
        try:
            context = moderngl.create_standalone_context(require=330, backend="egl")
        except Exception as exc:
            self.skipTest(f"Standalone EGL is unavailable: {exc}")

        painter = None
        try:
            painter = FishCardPainter(context)
            painted = painter.render("bluegill")
            source = fish_card("bluegill")
            direct = abs(painted.astype("int16") - source.astype("int16")).sum()
            flipped = abs(painted.astype("int16") - source[::-1].astype("int16")).sum()
            self.assertEqual(painted.shape, (CARD_SIZE[1], CARD_SIZE[0], 3))
            self.assertLess(direct, flipped)
        finally:
            if painter is not None:
                painter.close()
            context.release()

    def test_48_entry_card_and_thumbnail_caches_stay_under_25_mb(self):
        species_ids = list(load_content_v2().species)[:CARD_CACHE_ENTRIES // 2]
        variants = [(species_id, shiny) for species_id in species_ids for shiny in (False, True)]
        for species_id, shiny in variants:
            fish_card(species_id, shiny)
            fish_thumbnail(species_id, shiny)

        self.assertEqual(_card_cached.cache_info().currsize, CARD_CACHE_ENTRIES)
        self.assertEqual(_thumbnail_cached.cache_info().currsize, CARD_CACHE_ENTRIES)
        self.assertLess(card_cache_limit_bytes(), 25_000_000)
        self.assertLessEqual(cache_bytes(), 25_000_000)

    def test_contact_sheet_contains_normal_and_shiny_cards_for_all_36_species(self):
        sheet = fish_card_contact_sheet()

        self.assertEqual(sheet.shape, (8 * 80, 9 * THUMBNAIL_SIZE[0], 3))
        self.assertGreater(int(sheet.std()), 10)


if __name__ == "__main__":
    unittest.main()
