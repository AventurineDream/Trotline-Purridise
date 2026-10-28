"""Reed Passage rules (crawl speed and the Reed Anchor gate) and the Sonar Grid overlay."""

import unittest

from . import sonar
from .botidentity import grant_tool
from .sim import REEDS_CRAWL_SPEED, Hook, SetLine, State
from .world import World


def water_in(world, zone):
    """Navigable points inside one habitat circle, scanned on a 2 m grid."""
    _name, cx, cz, radius = next(entry for entry in world.zones if entry[0] == zone)
    steps = int(radius)
    for i in range(-steps, steps + 1, 2):
        for j in range(-steps, steps + 1, 2):
            x, z = cx + i, cz + j
            if world.zone_at(x, z) == zone and world.navigable(x, z):
                yield x, z


class ReedPassageRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World("briar")

    def place(self, state, x, z):
        state.x, state.z = x, z
        state.yaw = 0.0
        state.speed = 0.0
        state.anchored = False

    def test_reeds_hold_a_powered_boat_to_a_crawl_while_other_habitat_does_not(self):
        def speed_after_one_step(point):
            state = State.new(self.world, seed=61)
            self.place(state, *point)
            state.speed = 4.0
            state.throttle_setting = state.throttle = 1.0
            state.drive(0.2, 0.0, 0.0, self.world)
            return state.speed

        self.assertEqual(speed_after_one_step(next(water_in(self.world, "reeds"))), REEDS_CRAWL_SPEED)
        self.assertGreater(speed_after_one_step(next(water_in(self.world, "lilies"))), REEDS_CRAWL_SPEED * 2)

    def test_lines_set_in_reeds_need_the_reed_anchor(self):
        # A refused set leaves the held line in place, so each pose gets a fresh state.
        for x, z in water_in(self.world, "reeds"):
            state = State.new(self.world, seed=62)
            self.place(state, x, z)
            error = state.try_set(self.world, 0, "worm")
            if error and "Reed Anchor" in error:
                break
        else:
            self.fail("no reeds pose refused a line without the Reed Anchor")
        self.assertTrue(grant_tool(state, "reed_anchor"))
        self.assertIsNone(state.try_set(self.world, 0, "worm"))
        self.assertEqual(state.lines[-1].zone, "reeds")


class SonarOverlay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World("briar")

    def test_overlay_needs_the_finder_and_the_purchased_grid(self):
        reed = next(water_in(self.world, "reeds"))
        state = State.new(self.world, seed=63)
        state.x, state.z = reed
        self.assertEqual(sonar.overlay(state, self.world), [])
        state.finder = True
        self.assertEqual(sonar.overlay(state, self.world), [])
        grant_tool(state, "sonar_grid")
        cells = sonar.overlay(state, self.world)
        self.assertTrue(cells)
        self.assertTrue(all(cell.zone == "reeds" for cell in cells))
        self.assertTrue(all(self.world.navigable(cell.x, cell.z) for cell in cells))
        self.assertTrue(all(cell.band >= 0 for cell in cells))

    def test_overlay_covers_scouted_zones_with_a_line_not_just_the_boat(self):
        reed = next(water_in(self.world, "reeds"))
        far = next(water_in(self.world, "lilies"))
        state = State.new(self.world, seed=64)
        state.finder = True
        grant_tool(state, "sonar_grid")
        state.x, state.z = far
        self.assertTrue(all(cell.zone != "reeds" for cell in sonar.overlay(state, self.world)))
        state.lines = [SetLine("std", "worm", reed[0], reed[1], reed[0] + 10, reed[1], "reeds",
                               [Hook(True)])]
        cells = sonar.overlay(state, self.world)
        self.assertTrue(any(cell.zone == "reeds" for cell in cells))


if __name__ == "__main__":
    unittest.main()
