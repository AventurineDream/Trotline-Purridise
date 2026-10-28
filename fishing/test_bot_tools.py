"""Bot tool rules: thermocline, the Wave Chime, the Zero-G Winch and Nebula currents."""

import unittest

from . import bottools
from .botidentity import grant_tool
from .data import SPECIES
from .sim import Hook, SetLine, State, _seg_gap, species_rates
from .world import World

WEATHERS = ("clear", "fair", "drizzle", "fog", "mist", "rain", "snow", "snow_mist")


def navigable_point(world, zone, half_length=10.0):
    """A water midpoint in `zone` whose 2 * half_length line, along x, stays in water."""
    _name, cx, cz, radius = next(entry for entry in world.zones if entry[0] == zone)
    for i in range(-int(radius), int(radius) + 1, 2):
        for j in range(-int(radius), int(radius) + 1, 2):
            x, z = cx + i, cz + j
            if (world.zone_at(x, z) == zone and world.navigable(x, z)
                    and world.navigable(x - half_length, z) and world.navigable(x + half_length, z)):
                return x, z
    raise AssertionError(f"no water in {zone}")


class ThermoclineRules(unittest.TestCase):
    def test_cold_layer_stays_within_its_bounds_for_every_hour_and_weather(self):
        for lake_id in ("flathead", "crater"):
            deepest = max(hi for _lo, hi in bottools.LAKES[lake_id]["placeholder_depths"].values())
            for step in range(0, 96):
                for weather in WEATHERS:
                    with self.subTest(lake=lake_id, hour=step / 4, weather=weather):
                        depth = bottools.cold_layer_m(lake_id, step / 4, weather)
                        self.assertGreaterEqual(depth, bottools.MIN_COLD_LAYER_M)
                        self.assertLessEqual(depth, bottools.COLD_LAYER_CAP * deepest + 1e-9)

    def test_cold_layer_follows_the_authored_formula(self):
        self.assertAlmostEqual(bottools.cold_layer_m("flathead", 3.0, "fog"), 12.0 + 1.5)
        self.assertAlmostEqual(bottools.cold_layer_m("flathead", 21.0, "fair"), 15.0)
        self.assertAlmostEqual(bottools.cold_layer_m("flathead", 15.0, "clear"), 11.0)
        self.assertAlmostEqual(bottools.cold_layer_m("crater", 21.0, "fair"), 22.0)

    def test_lakes_without_a_thermocline_have_none(self):
        self.assertIsNone(bottools.cold_layer_m("briar", 12.0, "clear"))
        self.assertIsNone(bottools.cold_layer_m("cedar", 12.0, "clear"))

    def test_scanner_readout_needs_the_tool_and_a_thermocline(self):
        self.assertIsNone(bottools.scanner_text(False, "flathead", 15.0, "clear"))
        self.assertIsNone(bottools.scanner_text(True, "briar", 15.0, "clear"))
        self.assertEqual(bottools.scanner_text(True, "flathead", 15.0, "clear"), "Cold layer 11 m")


class SpeciesFactors(unittest.TestCase):
    def test_cold_species_are_full_inside_the_band_and_reduced_outside_it(self):
        tool = bottools.ToolState(cold_layer_m=12.0)
        self.assertEqual(bottools.species_factor(("cold",), 12.0, tool), 1.0)
        self.assertEqual(bottools.species_factor(("cold",), 18.0, tool), 1.0)
        self.assertEqual(bottools.species_factor(("cold",), 11.9, tool), bottools.COLD_OUTSIDE)
        self.assertEqual(bottools.species_factor(("cold",), 18.1, tool), bottools.COLD_OUTSIDE)
        self.assertEqual(bottools.species_factor(("cold",), 12.0, None), 1.0)

    def test_surface_and_current_tags_use_the_chime_and_winch_multipliers(self):
        chime = bottools.ToolState(chime=True)
        winch = bottools.ToolState(winch=True)
        self.assertEqual(bottools.species_factor(("surface",), 5.0, chime), bottools.CHIME_SURFACE_MULT)
        self.assertEqual(bottools.species_factor(("surface",), 5.0, winch), 1.0)
        self.assertEqual(bottools.species_factor(("current",), 5.0, winch), bottools.WINCH_CURRENT_MULT)
        self.assertEqual(bottools.species_factor(("current",), 5.0, chime), 1.0)

    def test_cold_species_keep_a_positive_rate_outside_the_band(self):
        cold_species = [sp for sp in SPECIES if "cold" in sp.tags and "flathead" in sp.lakes]
        self.assertTrue(cold_species)
        for sp in cold_species:
            zone, bait = sp.zones[0], sp.baits[0]
            for depth in (1.0, 8.0, 20.0, 40.0):
                plain = species_rates(zone, bait, 3.0, "fair", depth, "flathead")[sp.id]
                tooled = species_rates(zone, bait, 3.0, "fair", depth, "flathead",
                                       tool=bottools.ToolState(cold_layer_m=30.0))[sp.id]
                if plain > 0:
                    with self.subTest(species=sp.id, depth=depth):
                        self.assertGreater(tooled, 0.0)
                        self.assertLessEqual(tooled, plain + 1e-12)

    def test_lakes_without_a_thermocline_are_unchanged_by_the_cold_rule(self):
        for sp in SPECIES:
            if "cold" not in sp.tags or not sp.lakes:
                continue
            lake = sp.lakes[0]
            if lake in bottools.COLD_LAYER:
                continue
            zone, bait = sp.zones[0], sp.baits[0]
            plain = species_rates(zone, bait, 12.0, "fair", 6.0, lake)[sp.id]
            tooled = species_rates(zone, bait, 12.0, "fair", 6.0, lake,
                                   tool=bottools.ToolState(cold_layer_m=None))[sp.id]
            self.assertEqual(tooled, plain, sp.id)


class WaveChime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World("flathead")

    def setUp(self):
        self.state = State.new(self.world, seed=71)
        self.x, self.z = navigable_point(self.world, "lilies")
        self.state.x, self.state.z = self.x, self.z
        self.state.speed = 0.0
        self.line = SetLine("std", "worm", self.x - 10, self.z, self.x + 10, self.z, "lilies", [Hook(True)])
        self.state.lines = [self.line]

    def test_chime_needs_the_tool_a_slow_boat_and_a_line_within_thirty_metres(self):
        self.assertIn("not aboard", self.state.use_chime(self.world))
        grant_tool(self.state, "wave_chime")
        self.state.speed = 1.0
        self.assertIn("Slow the boat", self.state.use_chime(self.world))
        self.state.speed = 0.0
        self.state.x += 60.0
        self.assertIn("within 30 m", self.state.use_chime(self.world))
        self.state.x = self.x

    def test_chime_rings_for_sixty_game_minutes_then_rests_for_a_cooldown(self):
        grant_tool(self.state, "wave_chime")
        start = self.state.game_minutes
        self.assertIsNone(self.state.use_chime(self.world))
        self.assertEqual(self.line.chime_until, start + bottools.CHIME_LAST_MINUTES)
        self.assertIn("rests", self.state.use_chime(self.world))

        self.state.game_minutes = start + 59.0
        self.assertLess(self.state.game_minutes, self.line.chime_until)
        self.state.game_minutes = start + 60.0
        self.assertGreaterEqual(self.state.game_minutes, self.line.chime_until)

        self.state.game_minutes = start + bottools.CHIME_COOLDOWN_MINUTES
        self.assertIsNone(self.state.use_chime(self.world))
        self.assertEqual(self.line.chime_until, start + bottools.CHIME_COOLDOWN_MINUTES + 60.0)


class NebulaCurrents(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World("nebula")

    def make_line(self, state):
        x, z = navigable_point(self.world, "current")
        line = SetLine("std", "worm", x - 10, z, x + 10, z, "current", [Hook(True)])
        state.lines = [line]
        return line

    def test_drift_never_moves_a_line_more_than_sixty_metres_from_its_set_point(self):
        state = State.new(self.world, seed=72)
        line = self.make_line(state)
        origin_mid = ((line.x0 + line.x1) * 0.5, (line.z0 + line.z1) * 0.5)
        for _ in range(200):
            state.drift_lines(self.world, 600.0)
            mid = ((line.x0 + line.x1) * 0.5, (line.z0 + line.z1) * 0.5)
            reach = ((mid[0] - origin_mid[0]) ** 2 + (mid[1] - origin_mid[1]) ** 2) ** 0.5
            self.assertLessEqual(reach, bottools.DRIFT_CAP_M + 1e-6)
        self.assertIsNotNone(line.drift_origin)
        self.assertGreater(reach, 1.0, "the current should have moved the line")

    def test_drift_rate_is_half_a_metre_per_game_minute_before_the_cap(self):
        state = State.new(self.world, seed=73)
        line = self.make_line(state)
        before = (line.x0, line.z0)
        state.drift_lines(self.world, 1.0)
        step = ((line.x0 - before[0]) ** 2 + (line.z0 - before[1]) ** 2) ** 0.5
        self.assertLessEqual(step, bottools.FLOW_M_PER_MINUTE + 1e-9)

    def test_winch_holds_current_lines_in_place(self):
        state = State.new(self.world, seed=74)
        line = self.make_line(state)
        grant_tool(state, "zero_g_winch")
        before = (line.x0, line.z0, line.x1, line.z1)
        state.drift_lines(self.world, 600.0)
        self.assertEqual((line.x0, line.z0, line.x1, line.z1), before)
        self.assertIsNone(line.drift_origin)

    def test_drift_never_crowds_another_line(self):
        state = State.new(self.world, seed=75)
        line = self.make_line(state)
        neighbour = SetLine("std", "worm", line.x0, line.z0 + 17.0, line.x1, line.z1 + 17.0,
                            "current", [Hook(True)])
        state.lines = [line, neighbour]
        self.assertGreaterEqual(_seg_gap(line, neighbour), bottools.DRIFT_MIN_GAP_M)
        for _ in range(50):
            state.drift_lines(self.world, 600.0)
            self.assertGreaterEqual(_seg_gap(line, neighbour), bottools.DRIFT_MIN_GAP_M - 1e-9)

    def test_chime_and_drift_origin_survive_a_save_round_trip(self):
        line = SetLine("std", "worm", 1.0, 2.0, 3.0, 4.0, "current", [Hook(True)],
                       chime_until=120.5, drift_origin=(0.0, 1.0, 2.0, 3.0))
        again = SetLine.from_json(line.to_json())
        self.assertEqual(again.chime_until, 120.5)
        self.assertEqual(again.drift_origin, (0.0, 1.0, 2.0, 3.0))
        legacy = SetLine.from_json({k: v for k, v in line.to_json().items()
                                    if k not in ("chime_until", "drift_origin")})
        self.assertEqual(legacy.chime_until, -999.0)
        self.assertIsNone(legacy.drift_origin)


if __name__ == "__main__":
    unittest.main()
