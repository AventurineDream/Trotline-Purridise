"""V1-28 fish looks: v2 anatomy for every fish, legendaries, the look-alike check, haul meshes and idles."""

from copy import deepcopy
import math
import unittest
from unittest import mock

import numpy as np

from . import fishmesh
from .book import LEGENDARY_IDS
from .content import ContentError, load_content_v2, validate_content_v2
from .data import CONTENT_V2_RAW
from .fishart import RAY_DISC, _Body, eye_geometry, fin_shapes, ring_geometry
from .fishcheck import PALETTE_OVERLAP, SILHOUETTE_IOU, compare, lake_members, lookalike_report, signature
from .fishmesh import (CARD_SIZE, FAMILY_PRESETS, clear_caches, fish_card, fish_look, haul_mesh, idle_mesh,
                       legendary_idle, legendary_ids, paint_card_layers)
from .fishshots import idle_frame

CONTENT = load_content_v2()
ALL_FISH = list(CONTENT.species) + list(CONTENT.legendaries)


def card_pixel(card, x, y):
    return card[int(y * CARD_SIZE[1]), int(x * CARD_SIZE[0])].astype(int)


class LookData(unittest.TestCase):
    def test_every_fish_and_legendary_has_an_explicit_v2_look(self):
        self.assertEqual(len(CONTENT.species), 144)
        self.assertEqual(len(CONTENT.legendaries), 12)
        for fish_id in ALL_FISH:
            look = fish_look(fish_id)
            self.assertIn("colors", look, fish_id)
            self.assertNotIn("palette", look, fish_id)
        families = {fish_look(fish_id)["family"] for fish_id in ALL_FISH}
        # The ticket's new presets are all in use, and every family has a preset.
        self.assertTrue({"sculpin", "sturgeon", "eel", "salamander", "ray", "cosmic"} <= families)
        self.assertLessEqual(families, set(FAMILY_PRESETS))

    def test_real_species_keep_their_field_marks(self):
        self.assertEqual(fish_look("brook_trout")["scale_pattern"], "haloed")
        self.assertIn("throat", fish_look("westslope_cutthroat"))
        self.assertEqual(fish_look("arctic_grayling")["dorsal_style"], "sail")
        self.assertEqual(fish_look("white_sturgeon")["tail_shape"], "heterocercal")
        self.assertIn("scutes", fish_look("white_sturgeon")["features"])
        self.assertIn("ear", fish_look("bluegill"))
        self.assertIn("ear_edge", fish_look("redear"))
        self.assertIn("long_ear", fish_look("longear")["features"])
        self.assertIn("ocellus", fish_look("bowfin")["features"])
        self.assertIn("shoulder_spot", fish_look("gizzard_shad")["features"])
        self.assertEqual(fish_look("burbot")["barbels"], 1)

    def test_legendaries_match_their_windows_and_book_pages(self):
        windows = {row["id"]: row for row in CONTENT_V2_RAW["calendar.json"]["legendary_windows"]}
        self.assertEqual(legendary_ids(), tuple(windows))
        self.assertEqual(set(legendary_ids()), set(LEGENDARY_IDS))
        for legendary_id, row in CONTENT.legendaries.items():
            self.assertEqual(row["lake"], windows[legendary_id]["lake"])
            self.assertNotIn(legendary_id, CONTENT.species)
            idle = legendary_idle(legendary_id)
            self.assertEqual(set(idle), {"sway", "rate", "bob"})
            self.assertLessEqual(idle["rate"], 1.0)

    def test_validator_rejects_bad_legendaries_and_looks(self):
        cases = []
        broken = deepcopy(CONTENT_V2_RAW)
        broken["legendaries.json"]["legendaries"][0]["look"]["palette"] = "bluegill"
        del broken["legendaries.json"]["legendaries"][0]["look"]["colors"]
        cases.append((broken, "legendaries[0](old_lantern).look", "missing required field 'colors'"))
        cases.append((broken, "legendaries[0](old_lantern).look", "unknown field 'palette'"))
        broken = deepcopy(CONTENT_V2_RAW)
        broken["legendaries.json"]["legendaries"][1]["lake"] = "nebula"
        cases.append((broken, "legendaries[1](lily_queen).lake", "expected 'briar'"))
        broken = deepcopy(CONTENT_V2_RAW)
        broken["legendaries.json"]["legendaries"][2]["idle"]["rate"] = 4.0
        cases.append((broken, "legendaries[2](spillway_monster).idle.rate", "<= 1.0"))
        broken = deepcopy(CONTENT_V2_RAW)
        broken["legendaries.json"]["legendaries"].pop()
        cases.append((broken, "legendaries.json:legendaries", "all twelve"))
        broken = deepcopy(CONTENT_V2_RAW)
        broken["legendaries.json"]["legendaries"][3]["id"] = "bluegill"
        cases.append((broken, "legendaries[3](bluegill)", "standard species ID"))
        broken = deepcopy(CONTENT_V2_RAW)
        broken["species.json"]["species"][0]["look"]["ear"] = [1.2, 0, 0]
        cases.append((broken, "species[0](bluegill).look.ear[0]", "<= 1"))
        broken = deepcopy(CONTENT_V2_RAW)
        del broken["species.json"]["species"][1]["look"]
        cases.append((broken, "species[1]", "missing required field 'look'"))
        broken = deepcopy(CONTENT_V2_RAW)
        broken["species.json"]["species"][0]["look"]["features"] = ["wings"]
        cases.append((broken, "species[0](bluegill).look.features", "unique known features"))
        broken = deepcopy(CONTENT_V2_RAW)
        broken["species.json"]["species"][2]["look"]["features"] = [{"kype": 1}]
        cases.append((broken, "species[2](crappie).look.features", "unique known features"))
        broken = deepcopy(CONTENT_V2_RAW)
        broken["species.json"]["species"][0]["look"]["sparkle"] = True
        cases.append((broken, "species[0](bluegill).look", "unknown field 'sparkle'"))
        for raw, where, message in cases:
            with self.subTest(where=where), self.assertRaises(ContentError) as caught:
                validate_content_v2(raw)
            text = str(caught.exception)
            self.assertIn(where, text)
            self.assertIn(message, text)


class LookalikeCheck(unittest.TestCase):
    def test_no_two_fish_on_a_lake_share_a_silhouette_and_a_palette(self):
        report = lookalike_report(CONTENT)
        self.assertEqual(report["failures"], [])
        self.assertEqual(set(report["lakes"]), set(CONTENT.lakes))
        for lake_id, ids in lake_members(CONTENT).items():
            self.assertEqual(report["lakes"][lake_id]["pairs"], len(ids) * (len(ids) - 1) // 2)

    def test_the_check_catches_a_duplicated_look(self):
        rows = fishmesh._species_rows()
        twin = {**rows["redear"], "look": rows["bluegill"]["look"]}
        stub = type("Stub", (), {"lakes": {"briar": {"species_ids": ["bluegill", "redear", "gar"]}},
                                 "legendaries": {}})()
        with mock.patch.dict(rows, {"redear": twin}):
            report = lookalike_report(stub)
        self.assertEqual([(f["a"], f["b"]) for f in report["failures"]], [("bluegill", "redear")])
        self.assertEqual(compare(signature("bluegill"), signature("bluegill")), (1.0, 1.0))

    def test_thresholds_separate_real_relatives(self):
        # A deep sunfish and a slim gar differ in outline; bluegill and pumpkinseed differ in colour.
        iou, _ = compare(signature("bluegill"), signature("gar"))
        self.assertLess(iou, SILHOUETTE_IOU)
        _, overlap = compare(signature("pumpkinseed"), signature("lake_trout"))
        self.assertLess(overlap, PALETTE_OVERLAP)


class Cards(unittest.TestCase):
    def tearDown(self):
        clear_caches()

    def test_v2_cards_are_deterministic_and_shiny_repaints_them(self):
        for fish_id in ("bluegill", "prism_ray", "star_whale", "caldera_fire_lizard"):
            card, silhouette = paint_card_layers(fish_id)
            again, _ = paint_card_layers(fish_id)
            np.testing.assert_array_equal(card, again)
            self.assertEqual(card.shape, (CARD_SIZE[1], CARD_SIZE[0], 3))
            self.assertGreater(silhouette.mean(), 0.05)
        self.assertGreater(int(np.abs(fish_card("bluegill").astype(int) - fish_card("bluegill", True)).sum()), 100000)
        with self.assertRaises(KeyError):
            fish_card("star_whale", True)

    def test_field_marks_reach_the_painted_card(self):
        bluegill = fish_card("bluegill")
        body = _Body(fish_look("bluegill"))
        ear = card_pixel(bluegill, *body.point(0.80 - 0.055, -0.12))
        self.assertLess(ear.max(), 50)
        bowfin = fish_card("bowfin")
        eyespot_ring = card_pixel(bowfin, _Body(fish_look("bowfin")).point(0.07, -0.35)[0] + 0.016,
                                  _Body(fish_look("bowfin")).point(0.07, -0.35)[1])
        self.assertGreater(eyespot_ring[0] - eyespot_ring[2], 80)
        puffer = fish_card("saturnfin_puffer")
        rx, ry, reach, outer, inner = ring_geometry(_Body(fish_look("saturnfin_puffer")))
        ring = card_pixel(puffer, rx + reach * 0.93, ry)
        self.assertGreater(ring[2], ring[0])  # the blue ring stands clear of the body
        ray = fish_card("prism_ray")
        self.assertLess(card_pixel(ray, RAY_DISC[0] + RAY_DISC[2] * 0.55, RAY_DISC[1] - 0.06).max(), 40)
        lizard = fish_look("caldera_fire_lizard")
        legs = fin_shapes(_Body(lizard), lizard, FAMILY_PRESETS["salamander"]["fin_height"]).fins
        foot = max((p for points in legs for p in points), key=lambda p: p[1])
        self.assertGreater(foot[1], _Body(lizard).point(0.5, 1)[1])


class HaulMeshes(unittest.TestCase):
    @classmethod
    def tearDownClass(cls):
        clear_caches()

    def test_every_fish_has_a_bounded_finite_read_only_mesh(self):
        for fish_id in ALL_FISH:
            mesh = haul_mesh(fish_id, "briar", False)
            with self.subTest(fish=fish_id):
                self.assertGreaterEqual(mesh.triangle_count, 1250)
                self.assertLessEqual(mesh.triangle_count, 1800)
                self.assertTrue(np.isfinite(mesh.vertices).all() and np.isfinite(mesh.normals).all())
                self.assertFalse(mesh.vertices.flags.writeable)
                self.assertEqual(len(mesh.colors), mesh.triangle_count)

    def test_haul_sprites_match_their_cards(self):
        from .ui import _haul_mesh_sprite

        families = {}
        for fish_id in ALL_FISH:
            families.setdefault(fish_look(fish_id)["family"], fish_id)
        for fish_id in list(families.values()) + list(CONTENT.legendaries):
            _, silhouette = paint_card_layers(fish_id)
            sprite = _haul_mesh_sprite(fish_id, "briar", False)
            height, width = sprite.shape[:2]
            # Invert the sprite projection back into card units.
            cx = (np.arange(width) + 0.5 - width / 2) / 136 / 2.6 + 0.5
            cy = 0.5 - (height / 2 - np.arange(height) - 0.5) / 136 / 1.3
            inside = ((cy >= 0) & (cy < 1))[:, None] & ((cx >= 0) & (cx < 1))[None, :]
            card = silhouette[np.clip((cy * 256).astype(int), 0, 255)][:, np.clip((cx * 512).astype(int), 0, 511)]
            card &= inside
            seen = sprite[:, :, 3] > 0
            with self.subTest(fish=fish_id):
                self.assertGreater((card & seen).sum() / (card | seen).sum(), 0.9)

    def test_mesh_paint_comes_from_the_card(self):
        mesh = haul_mesh("bluegill", "briar", False)
        shiny = haul_mesh("bluegill", "briar", True)
        self.assertFalse(np.allclose(mesh.colors, shiny.colors))
        card = fish_card("bluegill").reshape(-1, 3).astype(np.float32) / 255
        palette = {tuple(np.round(c, 4)) for c in card}
        hits = sum(tuple(np.round(c, 4)) in palette for c in mesh.colors[:500])
        self.assertGreater(hits, 480)
        ray = haul_mesh("prism_ray", "nebula", False)
        # The ray faces the camera: broad in x and y, shallow in z.
        extent = ray.vertices.max(axis=0) - ray.vertices.min(axis=0)
        self.assertGreater(extent[1], extent[2] * 3)


class LegendaryIdle(unittest.TestCase):
    def test_idle_loops_stays_slow_and_bounded_and_holds_for_reduced_motion(self):
        for legendary_id in CONTENT.legendaries:
            idle = legendary_idle(legendary_id)
            loop = 2.0 / idle["rate"]
            rest = idle_mesh(legendary_id, 0.0, reduced_motion=True)
            self.assertIs(rest, haul_mesh(legendary_id, CONTENT.legendaries[legendary_id]["lake"], False))
            self.assertIs(idle_mesh(legendary_id, 3.7, reduced_motion=True), rest)
            np.testing.assert_allclose(idle_mesh(legendary_id, loop).vertices,
                                       idle_mesh(legendary_id, 0.0).vertices, atol=1e-5)
            np.testing.assert_array_equal(idle_mesh(legendary_id, 1.3).vertices,
                                          idle_mesh(legendary_id, 1.3).vertices)
            quarter = idle_mesh(legendary_id, loop / 8)
            moved = np.abs(quarter.vertices - rest.vertices)
            self.assertLessEqual(moved.max(), idle["sway"] + idle["bob"] + 1e-5)
            self.assertGreater(moved.max(), 0.005)
            head = rest.vertices[:, 0] > np.percentile(rest.vertices[:, 0], 90)
            tail = rest.vertices[:, 0] < np.percentile(rest.vertices[:, 0], 10)
            self.assertLess(moved[head, 2].max(), moved[tail, 2].max())
        with self.assertRaises(KeyError):
            idle_mesh("bluegill", 0.0)

    def test_idle_frames_show_motion_except_under_reduced_motion(self):
        loop = 2.0 / legendary_idle("nebula_weaver")["rate"]
        first = idle_frame("nebula_weaver", 0.0, size=(192, 96))
        later = idle_frame("nebula_weaver", loop / 4, size=(192, 96))
        self.assertGreater(int(np.abs(first.astype(int) - later).sum()), 2000)
        np.testing.assert_array_equal(idle_frame("nebula_weaver", loop / 4, size=(192, 96), reduced_motion=True),
                                      idle_frame("nebula_weaver", 0.0, size=(192, 96), reduced_motion=True))
        self.assertTrue(math.isfinite(float(first.mean())))


if __name__ == "__main__":
    unittest.main()
