"""Five-water travel, flat maps, story gates and save compatibility."""

from copy import deepcopy
import gc
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import weakref

import numpy as np

from . import calendar
from .boat import BOATS
from .content import ContentError, validate_content_v2
from .data import CONTENT_V2_RAW, LAKE_DAYS, LAKE_SPECIES_IDS, ZONE_ORDER, zone_mult
from .game import Keys, Session
from .lakes import LAKES, LAKE_ZONE_NAMES, travel_caption, travel_unlocked
from .npcs import active_npcs
from .savepaths import load_game_save
from .sim import Hook, SetLine, State, species_rates
from .ui import shop_rows
from .world import World, zone_label


class LakeFrameworkChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.briar = World()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="five-waters-")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "save.json"
        self.state = State.new(self.briar, seed=723)
        self.session = Session(self.briar, self.path, self.state, False)
        self.session.ui.mode = "play"

    def test_story_completion_opens_routes_and_keeps_legacy_cedar_open(self):
        state = self.state
        self.assertTrue(travel_unlocked(state, "briar"))
        self.assertTrue(travel_unlocked(state, "cedar"))
        for lake, required in (("flathead", 2), ("crater", 3), ("nebula", 4)):
            for chapter in range(7):
                state.v2["story"] = {"chapter": chapter}
                self.assertEqual(travel_unlocked(state, lake), chapter > required)
            state.v2["story"] = {"chapter": 0, "completed_chapters": [required]}
            self.assertTrue(travel_unlocked(state, lake))
        for invalid in (None, [], {"chapter": True}, {"chapter": "6"},
                        {"chapter": 0, "completed_chapters": [True, "2"]}):
            state.v2["story"] = invalid
            self.assertFalse(travel_unlocked(state, "flathead"))
        self.assertFalse(travel_unlocked(state, "unknown"))

    def test_menu_shows_all_five_routes_and_disables_lines_or_story_locks(self):
        before, rng = deepcopy(self.state.v2), self.state.rng.s
        rows = shop_rows(self.state, 5)
        self.assertEqual([row.arg for row in rows], list(LAKES))
        self.assertEqual([row.enabled for row in rows], [False, True, False, False, False])
        self.assertIn("chapter 2", rows[2].blurb)
        self.assertEqual(self.state.v2, before)
        self.assertEqual(self.state.rng.s, rng)
        self.state.v2["story"]["chapter"] = 5
        self.assertTrue(all(row.enabled for row in shop_rows(self.state, 5)[1:]))
        self.state.lines = [SetLine("std", "worm", 0, 0, 12, 0, "open", [Hook(True)])]
        self.assertTrue(all(not row.enabled for row in shop_rows(self.state, 5)))

    def test_invalid_locked_away_and_lines_block_before_constructing_a_lake(self):
        with patch("fishing.game.World") as constructor:
            self.assertIn("chapter 2", self.session.change_lake("flathead"))
            self.assertIn("not on the chart", self.session.change_lake("unknown"))
            self.state.v2["story"]["chapter"] = 5
            self.state.lines = [SetLine("std", "worm", 0, 0, 12, 0, "open", [Hook(True)])]
            self.assertIn("lines", self.session.change_lake("flathead"))
            self.state.lines.clear()
            self.state.x = self.state.z = 0
            self.assertIn("landing", self.session.change_lake("flathead"))
            constructor.assert_not_called()
        self.assertIs(self.session.world, self.briar)

    def test_failed_destination_construction_keeps_current_state_intact(self):
        self.state.v2["story"]["chapter"] = 5
        with patch("fishing.sim.time.time", return_value=1234):
            before = self.state.to_json()
            with patch("fishing.game.World", side_effect=OSError("unavailable map")):
                with self.assertRaises(OSError):
                    self.session.change_lake("flathead")
            self.assertIs(self.session.world, self.briar)
            self.assertEqual(self.state.to_json(), before)

    def test_flat_maps_have_only_their_authored_habitats_and_safe_hulls(self):
        for lake in ("flathead", "crater", "nebula"):
            world = World(lake)
            self.assertTrue(world.placeholder)
            self.assertEqual(world.height.shape, (129, 169))
            self.assertEqual(world.props, [])
            self.assertFalse(world.anchors)
            state = State.new(world)
            self.assertEqual(state.slip_status(world), "docked")
            self.assertTrue(all(world.hull_clear(state.x, state.z, state.yaw, boat) for boat in BOATS))
            for zone, x, z, _ in world.zones:
                self.assertEqual(world.zone_at(x, z), zone)
                self.assertEqual(ZONE_ORDER[int(world.zone_ids(x, z))], zone)
                self.assertEqual(world.zone_name(zone), LAKE_ZONE_NAMES[lake][zone])
                for boat in BOATS:
                    self.assertTrue(world.hull_clear(x, z, math.pi/3, boat))
            # The complete central launch lane supports departure and return.
            for a in np.linspace(-100, 4, 40):
                x, z = world.slip.world(float(a), 0)
                self.assertTrue(all(world.hull_clear(x, z, state.yaw, boat) for boat in BOATS))
            self.assertEqual(world.zone_at(400, 0), "shore")
            self.assertFalse(world.navigable(400, 0))
            self.assertEqual(len(LAKE_SPECIES_IDS[lake]), 34)
            rates = species_rates("open", "worm", 12, "clear", 4, lake)
            self.assertTrue(all(rate == 0 for sid, rate in rates.items() if sid not in LAKE_SPECIES_IDS[lake]))

    def test_reed_passage_keeps_original_anchors_terrain_and_zone_indices(self):
        world = self.briar
        self.assertEqual(world.zones[-1], ("reeds", -338.0, -42.0, 44.0))
        self.assertEqual(world.zone_at(-338, -42), "reeds")
        self.assertEqual(zone_label("reeds"), "Reed Passage")
        for anchor in world.anchors.values():
            self.assertEqual(world.zone_at(anchor.x, anchor.z), anchor.zone_id.split(":")[1])
        self.assertEqual(world.height.shape, (992, 1240))
        for sid, expected in (("golden_shiner", 1), ("warmouth", .8),
                              ("chain_pickerel", .8), ("bluegill", .6), ("bowfin", .6), ("blue", .07)):
            self.assertEqual(zone_mult("reeds", sid), expected)

    def test_placeholders_do_not_mutate_or_load_a_previous_lake_cast(self):
        world = World("nebula")
        before = self.state.narrative.to_json()
        self.assertEqual(active_npcs(self.state, world, self.session._npc_content), ())
        self.assertEqual(self.state.narrative.to_json(), before)

    def test_loaded_map_is_collectible_after_travel(self):
        self.state.v2["story"]["chapter"] = 5
        self.assertIsNone(self.session.change_lake("flathead"))
        previous = weakref.ref(self.session.world)
        self.assertIsNone(self.session.change_lake("nebula"))
        gc.collect()
        self.assertIsNone(previous())
        self.assertEqual(self.state._world.id, "nebula")
        self.assertEqual(self.state.npcs, ())

    def test_placeholder_save_load_preserves_story_gear_forecast_and_future_data(self):
        self.state.v2["story"]["chapter"] = 5
        self.state.v2["story"]["future_story"] = {"keep": True}
        money, bait, held = self.state.money, deepcopy(self.state.bait), len(self.state.held)
        for lake in ("flathead", "crater", "nebula", "briar"):
            self.assertIsNone(self.session.change_lake(lake))
            self.session.tick(Keys(), .01)
            world, loaded, has_save = load_game_save(self.path, State, World)
            self.assertTrue(has_save)
            self.assertEqual(world.id, lake)
            self.assertEqual(loaded.lake_id, lake)
            self.assertEqual(loaded.money, money)
            self.assertEqual(loaded.bait, bait)
            self.assertEqual(len(loaded.held), held)
            self.assertEqual(loaded.v2["story"]["future_story"], {"keep": True})
            self.assertEqual(calendar.forecast_seed(loaded), 723)
            self.assertTrue(all(travel_unlocked(loaded, target) for target in LAKES))

    def test_travel_caption_in_every_direction_and_per_lake_line_labels(self):
        self.assertEqual(travel_caption("briar", "cedar"), "The jon boat rides the trailer down the county road.")
        self.assertIn("rattles north", travel_caption("cedar", "flathead"))
        self.assertIn("cat with a truck", travel_caption("flathead", "crater"))
        for source in LAKES:
            if source != "nebula":
                self.assertIn("starlight", travel_caption(source, "nebula"))
        for destination in LAKES:
            if destination != "nebula":
                self.assertIn("ordinary water", travel_caption("nebula", destination))
        self.state.bind(World("crater"))
        self.state.lines = [SetLine("std", "worm", 0, 0, 12, 0, "springs", [Hook(True)])]
        self.assertEqual(self.state.line_label(0), "Thermal springs")

    def test_registry_reports_bad_habitats_palettes_and_calendar_references(self):
        bad = deepcopy(CONTENT_V2_RAW)
        row = bad["lakes.json"]["lakes"][3]
        row["zone_ids"].append("missing")
        del row["zone_labels"]["springs"]
        row["palette"]["water"][0] = float("nan")
        row["unlock_chapter"] = True
        row["lake_days"] = ["mayfly_morning"]
        with self.assertRaises(ContentError) as caught:
            validate_content_v2(bad)
        for location in ("zone_ids", "zone_labels.springs", "palette.water", "unlock_chapter", "lake_days"):
            self.assertIn(location, str(caught.exception))

    def test_software_renders_every_new_habitat_without_a_tint_index_error(self):
        from .software import SoftwareRenderer
        for lake, zone in (("briar", "reeds"), ("crater", "springs"), ("nebula", "current")):
            world = self.briar if lake == "briar" else World(lake)
            state = State.new(world)
            _zone, state.x, state.z, _radius = next(row for row in world.zones if row[0] == zone)
            renderer = SoftwareRenderer(world, 160, 90)
            try:
                frame = renderer.render(state)
                self.assertEqual(frame.shape, (90, 160, 3))
                self.assertGreater(float(frame.std()), 8)
            finally:
                renderer.close()

    def test_empty_prop_native_maps_render_without_falling_back(self):
        try:
            import moderngl
            ctx = moderngl.create_standalone_context(require=330, backend="egl")
        except Exception as error:
            self.skipTest("Standalone EGL unavailable: " + str(error))
        from .glrender import LakeRenderer
        try:
            for lake in ("flathead", "crater", "nebula"):
                world = World(lake)
                with ctx:
                    renderer = LakeRenderer(world, 160, 90, context=ctx)
                try:
                    frame = renderer.render(State.new(world))
                    self.assertEqual(frame.shape, (90, 160, 3))
                    self.assertGreater(float(frame.std()), 8)
                finally:
                    renderer.close()
        finally:
            ctx.release()

    def test_all_ten_lake_days_and_future_weather_biases(self):
        self.assertEqual(len(LAKE_DAYS), 10)
        for lake, definition in LAKES.items():
            days = {row.id for row in LAKE_DAYS if row.lake == lake}
            self.assertEqual(days, set(definition["lake_days"]))
            self.assertEqual(len(days), 2)
        for seed in range(10):
            self.assertEqual(calendar.planned_weather(seed, "flathead", 60), "clear")
            self.assertEqual(calendar.planned_weather(seed, "crater", 4*1440), "fog")
            self.assertEqual(calendar.planned_weather(seed, "crater", 4*1440+60), "clear")
        self.assertEqual(calendar.rate_multiplier("nebula", 2*1440+840, "bluegill", "open"), 1.15)
        self.assertEqual(calendar.rate_multiplier("nebula", 2*1440+360, "bluegill", "open"), 1)
        self.assertEqual(calendar.rate_multiplier("flathead", 2*1440+360, "yellow_perch", "flats"), 1.25)
        self.assertEqual(calendar.rate_multiplier("crater", 1440, "ember_char", "deep"), 1.3)


class FiveWaterTravelChecks(unittest.TestCase):
    def test_all_twenty_directed_landing_routes_and_fresh_actors(self):
        with tempfile.TemporaryDirectory(prefix="five-water-routes-") as temporary:
            world = World()
            state = State.new(world)
            state.v2["story"]["chapter"] = 5
            session = Session(world, Path(temporary)/"save.json", state, False)
            seen = set()
            for source in LAKES:
                if session.world.id != source:
                    self.assertIsNone(session.change_lake(source))
                for destination in LAKES:
                    if destination == source:
                        continue
                    self.assertIsNone(session.change_lake(destination))
                    session.ui.mode = "play"
                    session.tick(Keys(), .01)
                    self.assertEqual(state.lake_id, destination)
                    self.assertEqual(state.slip_status(session.world), "docked")
                    self.assertTrue(all(n.anchor.lake_id == destination for n in state.npcs))
                    self.assertFalse(state.lines)
                    seen.add((source, destination))
                    self.assertIsNone(session.change_lake(source))
            self.assertEqual(len(seen), 20)


if __name__ == "__main__":
    unittest.main()
