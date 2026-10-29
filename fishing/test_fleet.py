"""V1-21 fleet: 24 boats, power types, traits, chapter-gated shop tiers and pacing."""

import unittest
from unittest.mock import patch

import numpy as np

from . import bottools, fleet, kitchen
from .boat import BOATS
from .boatmesh import HULL_GLOW, glow_hull
from .data import MOTORS, SPECIES, WELLS
from .sim import SNOW_MIST_CHOP, State
from .software import SoftwareRenderer
from .ui import shop_rows
from .world import World

# 02 §15.3 income-band midpoints in dollars per game day, keyed by unlock stage.
INCOME_MIDPOINT = {0: 90.0, 2: 225.0, 3: 400.0, 4: 600.0, 5: 900.0}
# The four boats from before V1.0, exactly as they shipped.
LEGACY_NUMBERS = {
    "jon": (2.86, -0.8, 0.7, 0.47, 1.22, 0, 5, 12, 1.8, 1.0, 1.0, 1.3, 0.0, 0.0),
    "sail": (2.63, -1.03, 0.86, 0.72, 1.3, 650, 5, 6, 0.45, 0.57, 0.72, 0.65, 0.0, 4.6),
    "pontoon": (3.37, -1.2, 1.2, 0.44, 1.65, 1450, 6, 36, 2.6, 0.83, 0.52, 0.72, 40, 0.0),
    "rowboat": (1.64, -1.41, 0.68, 0.22, 1.12, 325, 5, 0, 0.0, 1.0, 0.88, 0.78, 0.0, 0.0),
}
NUMBER_FIELDS = ("bow", "stern", "half_beam", "draft", "eye_height", "price", "lines", "tank",
                 "fuel_burn", "speed_factor", "turn_factor", "acceleration", "well_bonus", "sail_speed")


def water(world, zone):
    _name, cx, cz, radius = next(entry for entry in world.zones if entry[0] == zone)
    for i in range(-int(radius), int(radius) + 1, 2):
        for j in range(-int(radius), int(radius) + 1, 2):
            if world.zone_at(cx + i, cz + j) == zone and world.navigable(cx + i, cz + j):
                return cx + i, cz + j
    raise AssertionError(f"no water in {zone}")


def story(state, finished):
    state.v2["story"]["chapter"] = finished + 1
    state.v2["story"]["completed_chapters"] = list(range(1, finished + 1))


class FleetData(unittest.TestCase):
    def test_twenty_four_boats_follow_the_table(self):
        self.assertEqual(len(BOATS), 24)
        raft = BOATS["log_raft"]
        self.assertEqual((raft.tier, raft.price, raft.lines, raft.power, raft.top_speed),
                         (1, 300, 3, "paddle", 1.2))
        self.assertEqual(raft.traits, ("shallow", "silent", "hammock"))
        self.assertEqual(BOATS["celestial_flagship"].sold_at, ("nebula",))
        self.assertEqual(BOATS["small_sloop"].sail_speed, round(4.6 * 1.2, 2))
        self.assertEqual({model.tier for model in BOATS.values()}, set(range(1, 9)))

    def test_existing_four_keep_their_numbers_and_get_new_names(self):
        for boat_id, numbers in LEGACY_NUMBERS.items():
            with self.subTest(boat=boat_id):
                model = BOATS[boat_id]
                self.assertEqual(tuple(getattr(model, field) for field in NUMBER_FIELDS), numbers)
                self.assertTrue(model.handcrafted)
        self.assertEqual([BOATS[b].name for b in fleet.LEGACY_BOATS],
                         ["Aluminum Jon Boat", "Cat-Rigged Daysailer", "Classic Pontoon", "Reinforced Rowboat"])
        self.assertIn("hammock", BOATS["pontoon"].traits)
        self.assertEqual(BOATS["pontoon"].lines, 6)

    def test_new_boats_have_their_own_footprint_at_the_tables_length(self):
        feet = {"log_raft": 10, "birch_skiff": 12, "reed_dugout": 11, "dory": 14, "flat_skiff": 14,
                "river_runner": 14, "duck_jon": 14, "marsh_runner": 16, "deepv_skiff": 17,
                "coastal_craft": 18, "mahogany_runabout": 17, "fiberglass_cruiser": 20, "lake_taxi": 19,
                "small_sloop": 18, "tug_skiff": 18, "party_barge": 24, "houseboat": 32,
                "steam_barge": 22, "nebula_cruiser": 20, "celestial_flagship": 30}
        self.assertEqual(set(feet), {m.id for m in BOATS.values() if not m.handcrafted})
        deepest = max(BOATS[b].draft for b in fleet.LEGACY_BOATS)
        for boat_id, length_ft in feet.items():
            with self.subTest(boat=boat_id):
                model = BOATS[boat_id]
                self.assertAlmostEqual(model.length, length_ft * 0.3048, delta=0.02)
                self.assertGreater(model.bow, 0.0)
                self.assertLess(model.stern, 0.0)
                # Catchability witnesses are measured at the deepest existing draft.
                self.assertLessEqual(model.draft, deepest)


class PowerAndWells(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World("briar")

    def state_on(self, boat_id, motor=0):
        state = State.new(self.world, seed=81)
        state.boat_id = boat_id
        state.motor = motor
        state.fuel = state.boat.tank
        return state

    def test_top_speeds_follow_each_power_type(self):
        for motor in range(len(MOTORS)):
            with self.subTest(motor=motor):
                jon = MOTORS[motor]["speed"]
                self.assertAlmostEqual(self.state_on("jon", motor).max_speed(), jon)
                self.assertAlmostEqual(self.state_on("duck_jon", motor).max_speed(), jon)
                self.assertAlmostEqual(self.state_on("river_runner", motor).max_speed(),
                                       jon * BOATS["river_runner"].speed_factor)
                # Paddles, consoles, inboards and starlight ignore tiller upgrades.
                self.assertAlmostEqual(self.state_on("log_raft", motor).max_speed(), 1.2)
                self.assertAlmostEqual(self.state_on("marsh_runner", motor).max_speed(), 6.5)
                self.assertAlmostEqual(self.state_on("mahogany_runabout", motor).max_speed(), 9.5)
                self.assertAlmostEqual(self.state_on("nebula_cruiser", motor).max_speed(), 10.0)
                self.assertAlmostEqual(self.state_on("small_sloop", motor).max_speed(), 1.8)
        self.assertAlmostEqual(self.state_on("river_runner").max_speed(), 3.15 + 0.3, places=3)

    def test_unfuelled_boats_move_without_fuel_and_fuelled_ones_burn_it(self):
        for boat_id, burns in (("log_raft", False), ("dory", False), ("steam_barge", False),
                               ("jon", True), ("marsh_runner", True), ("tug_skiff", True)):
            with self.subTest(boat=boat_id):
                state = self.state_on(boat_id)
                state.x, state.z = water(self.world, "deep")
                state.anchored = False
                before = state.fuel
                for _ in range(20):
                    state.drive(0.1, 1.0, 0.0, self.world)
                self.assertGreater(state.speed, 0.1)
                if burns:
                    self.assertLess(state.fuel, before)
                else:
                    self.assertEqual((before, state.fuel), (0, 0))

    def test_well_upgrades_apply_to_tiers_two_to_seven_only(self):
        for tier in range(len(WELLS)):
            self.assertEqual(BOATS["log_raft"].well_cap(tier), 30.0)
            self.assertEqual(BOATS["steam_barge"].well_cap(tier), 240.0)
            self.assertEqual(BOATS["dory"].well_cap(tier), 60.0 + WELLS[tier] - WELLS[0])
            self.assertEqual(BOATS["jon"].well_cap(tier), WELLS[tier])
            self.assertEqual(BOATS["pontoon"].well_cap(tier), WELLS[tier] + 40)


class ShopTiers(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.briar = World("briar")
        cls.nebula = World("nebula")

    def buyable(self, state, lake_id):
        return {model.id for model in BOATS.values() if fleet.shop_error(state, lake_id, model.id) is None}

    def test_shop_unlocks_new_tiers_after_the_right_chapter(self):
        expected_tiers = {0: {1, 2}, 1: {1, 2}, 2: {1, 2, 3, 4}, 3: {1, 2, 3, 4, 5, 6},
                          4: set(range(1, 8)), 5: set(range(1, 9))}
        for finished, tiers in expected_tiers.items():
            with self.subTest(chapters_finished=finished):
                state = State.new(self.briar, seed=82)
                story(state, finished)
                wanted = {m.id for m in BOATS.values() if m.id in fleet.LEGACY_BOATS
                          or (m.tier in tiers and not m.sold_at)}
                self.assertEqual(self.buyable(state, "briar"), wanted)
                at_nebula = {m.id for m in BOATS.values() if m.id in fleet.LEGACY_BOATS or m.tier in tiers}
                self.assertEqual(self.buyable(state, "nebula"), at_nebula)

    def test_shop_rows_list_older_boats_first_and_explain_locks(self):
        state = State.new(self.briar, seed=83)
        rows = [row for row in shop_rows(state, 4) if row.kind == "boat"]
        self.assertEqual([row.arg for row in rows[:4]], list(fleet.LEGACY_BOATS))
        self.assertEqual(len(rows), 24)
        by_id = {row.arg: row for row in rows}
        self.assertFalse(by_id["jon"].enabled)  # aboard
        self.assertTrue(by_id["rowboat"].enabled)
        self.assertTrue(by_id["log_raft"].enabled)
        self.assertFalse(by_id["river_runner"].enabled)
        self.assertEqual(by_id["river_runner"].right, "After ch. 2")
        story(state, 5)
        by_id = {row.arg: row for row in shop_rows(state, 4) if row.kind == "boat"}
        self.assertFalse(by_id["nebula_cruiser"].enabled)
        self.assertEqual(by_id["nebula_cruiser"].right, "Other landing")
        self.assertIn("Cosmic Drift Station", by_id["nebula_cruiser"].blurb)

    def test_buying_respects_the_gates_and_keeps_owned_boats_switchable(self):
        state = State.new(self.briar, seed=84)
        state._park(self.briar)
        state.money = 20000
        self.assertIn("chapter 2", state.buy_boat("river_runner", self.briar))
        self.assertEqual(state.money, 20000)
        self.assertIsNone(state.buy_boat("log_raft", self.briar))
        story(state, 5)
        self.assertIn("Cosmic Drift Station", state.buy_boat("steam_barge", self.briar))
        state.owned_boats.append("steam_barge")
        state._park(self.briar)
        self.assertIsNone(state.buy_boat("steam_barge", self.briar))
        self.assertEqual(state.boat_id, "steam_barge")

    def test_each_tiers_cheapest_new_boat_costs_three_to_six_days_of_income(self):
        for tier, chapter in fleet.UNLOCK_AFTER_CHAPTER.items():
            cheapest = min(m.price for m in BOATS.values() if m.tier == tier and m.id not in fleet.LEGACY_BOATS)
            days = cheapest / INCOME_MIDPOINT[chapter]
            with self.subTest(tier=tier, days=round(days, 2)):
                self.assertGreaterEqual(days, 3.0)
                self.assertLessEqual(days, 6.0)


class Traits(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.briar = World("briar")
        cls.flathead = World("flathead")

    def afloat(self, world, boat_id, zone="lilies", at=None):
        state = State.new(world, seed=85)
        state.boat_id = boat_id
        state.owned_boats.append(boat_id)
        state.fuel = state.boat.tank
        state.x, state.z = at if at is not None else water(world, zone)
        state.speed = state.throttle = state.throttle_setting = 0.0
        state.anchored = False
        return state

    def test_shallow_boats_reach_water_the_jon_cannot(self):
        x0, z0, x1, z1 = self.briar.bounds
        xs, zs = np.meshgrid(np.linspace(x0, x1, 400), np.linspace(z0, z1, 400))
        depth, sd = self.briar.depth(xs, zs), self.briar.shore_sd(xs, zs)
        skinny = (sd <= -2.2) & (depth >= 0.40) & (depth < 0.55)
        self.assertTrue(skinny.any())
        px, pz = xs[skinny], zs[skinny]
        for model in BOATS.values():
            if "shallow" in model.traits:
                with self.subTest(boat=model.id):
                    self.assertTrue(np.all(self.briar.navigable_mask(px, pz, model.draft)))
        self.assertFalse(np.any(self.briar.navigable_mask(px, pz, BOATS["jon"].draft)))

    def test_silent_hulls_lift_shy_species(self):
        shy = next(sp for sp in SPECIES if "shy" in sp.tags)
        self.assertEqual(bottools.species_factor(shy.tags, 3.0, bottools.ToolState(silent=True)),
                         bottools.SILENT_SHY_MULT * bottools.species_factor(shy.tags, 3.0, bottools.ToolState()))
        self.assertEqual(bottools.species_factor(("cold",), 3.0, bottools.ToolState(silent=True)), 1.0)

    def test_galley_boats_cook_at_anchor_away_from_the_landing(self):
        cruiser = self.afloat(self.briar, "fiberglass_cruiser")
        jon = self.afloat(self.briar, "jon")
        cruiser.anchored = jon.anchored = True
        self.assertTrue(kitchen.can_cook(cruiser, self.briar))
        self.assertFalse(kitchen.can_cook(jon, self.briar))

    def test_hammock_boats_nap_at_idle_and_others_need_an_anchor_or_dock(self):
        self.assertIsNone(self.afloat(self.briar, "log_raft").catnap(self.briar))
        jon = self.afloat(self.briar, "jon")
        self.assertIn("Anchor", jon.catnap(self.briar))
        jon.anchored = True
        self.assertIsNone(jon.catnap(self.briar))
        moving = self.afloat(self.briar, "log_raft")
        moving.speed = 1.0
        self.assertIn("Anchor", moving.catnap(self.briar))

    def test_trophy_rail_gates_shiny_mounts(self):
        jon = self.afloat(self.briar, "jon")
        self.assertIn("trophy rail", jon.mount_shiny_trophy("bluegill"))
        skiff = self.afloat(self.briar, "deepv_skiff")
        self.assertIn("Catch a shiny", skiff.mount_shiny_trophy("bluegill"))

    def test_wind_steady_hulls_ignore_the_snow_mist_gust(self):
        moved = {}
        for boat_id in ("jon", "dory"):
            state = self.afloat(self.flathead, boat_id, zone="deep")
            start = (state.x, state.z)
            with patch("fishing.sim.weather_at", return_value="snow_mist"):
                for step in range(40):
                    state.anim = step * 0.1
                    state.drive(0.1, 0.0, 0.0, self.flathead)
            moved[boat_id] = float(np.hypot(state.x - start[0], state.z - start[1]))
        self.assertGreater(moved["jon"], 0.0)
        self.assertEqual(moved["dory"], 0.0)

    def test_ice_hulls_keep_full_speed_in_flathead_snow_mist(self):
        with patch("fishing.sim.weather_at", return_value="snow_mist"):
            plain = self.afloat(self.flathead, "deepv_skiff", zone="deep")
            iced = self.afloat(self.flathead, "coastal_craft", zone="deep")
            self.assertAlmostEqual(plain.max_speed(), 7.5 * SNOW_MIST_CHOP)
            self.assertAlmostEqual(iced.max_speed(), 7.0)
            briar = self.afloat(self.briar, "deepv_skiff", zone="deep")
            self.assertAlmostEqual(briar.max_speed(), 7.5)

    def test_glow_hulls_emit_at_night_and_others_do_not(self):
        renderer = SoftwareRenderer.__new__(SoftwareRenderer)
        for boat_id, glows in (("mahogany_runabout", True), ("steam_barge", True),
                               ("jon", False), ("pontoon", False)):
            with self.subTest(boat=boat_id):
                state = self.afloat(self.briar, boat_id)
                faces = renderer._boat_faces(state)
                self.assertTrue(faces)
                if glows:
                    self.assertNotIn(None, {face.emissive for face in faces})
                    self.assertIn(HULL_GLOW, {face.emissive for face in faces})
                else:
                    self.assertNotIn(HULL_GLOW, {face.emissive for face in faces})
                    self.assertIs(glow_hull(state, faces), faces)

    def test_reed_dugout_sets_lines_in_reeds_without_the_anchor(self):
        # Find a pose whose line lands in reeds: a birch skiff without the anchor is refused there.
        _name, cx, cz, radius = next(e for e in self.briar.zones if e[0] == "reeds")
        for i in range(-int(radius), int(radius) + 1, 2):
            for j in range(-int(radius), int(radius) + 1, 2):
                at = (cx + i, cz + j)
                if self.briar.zone_at(*at) != "reeds" or not self.briar.navigable(*at):
                    continue
                birch = self.afloat(self.briar, "birch_skiff", at=at)
                refusal = birch.try_set(self.briar, 0, "worm")
                if refusal and "Reed Anchor" in refusal:
                    dugout = self.afloat(self.briar, "reed_dugout", at=at)
                    self.assertIsNone(dugout.try_set(self.briar, 0, "worm"))
                    self.assertEqual(dugout.lines[-1].zone, "reeds")
                    return
        self.fail("no reeds pose refused a birch skiff's line")


if __name__ == "__main__":
    unittest.main()
