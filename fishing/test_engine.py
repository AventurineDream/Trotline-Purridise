"""Issue #153: manual engine ignition on V, and idle fuel burn.

A fuelled boat's engine starts on (old saves keep working) and toggles with
V or the pause menu. Engine off makes no thrust and burns nothing; engine on
idles at a fixed fraction of the full-throttle burn, except while docked.
"""
import math
import unittest
from pathlib import Path

from .comfort import fuel_factor
from .game import Keys, Session
from .sim import IDLE_FUEL_FRACTION, State
from .world import World


def _state(world: World, x: float, z: float, *, engine=True) -> State:
    state = State.new(world, seed=153)
    state.x, state.z = x, z
    state.speed = 0.0
    state.anchored = False
    state.engine_on = engine
    state.fuel = state.boat.tank
    return state


class EngineIgnition(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World("briar")
        cls.deep = cls.world.anchors["briar:deep"].position

    def test_v_toggles_engine_and_unfuelled_boats_refuse(self):
        state = _state(self.world, *self.deep)
        session = Session(self.world, Path("/tmp/trotline-engine.json"), state, False)
        session.ui.mode = "play"
        self.assertTrue(state.engine_on)

        session.tick(Keys(pressed={"v"}), 0.05)
        self.assertFalse(state.engine_on)
        self.assertEqual(state.toasts[-1][0], "Engine off.")

        state.boat_id = "log_raft"
        state.owned_boats.append("log_raft")
        state.engine_on = True
        session.tick(Keys(pressed={"v"}), 0.05)
        self.assertTrue(state.engine_on)
        self.assertIn("no engine", state.toasts[-1][0])

    def test_engine_off_makes_no_thrust_and_burns_nothing(self):
        state = _state(self.world, *self.deep, engine=False)
        state.throttle_setting = 1.0
        before = state.fuel
        for _ in range(40):
            state.drive(0.1, 1.0, 0.0, self.world)
        self.assertLess(abs(state.speed), 0.05)
        self.assertEqual(state.fuel, before)
        self.assertEqual(state.throttle_setting, 1.0, "the lever must survive engine off")

    def test_idle_burn_is_deterministic_and_engine_off_burns_nothing(self):
        state = _state(self.world, *self.deep)
        state.throttle_setting = state.throttle = 0.0
        before = state.fuel
        seconds = 60.0
        for _ in range(int(seconds / 0.1)):
            state.drive(0.1, 0.0, 0.0, self.world)
        expected = (state.boat.fuel_burn * IDLE_FUEL_FRACTION
                    * fuel_factor(state) * seconds / 60.0)
        self.assertAlmostEqual(before - state.fuel, expected, places=6)

        state.engine_on = False
        frozen = state.fuel
        for _ in range(100):
            state.drive(0.1, 0.0, 0.0, self.world)
        self.assertEqual(state.fuel, frozen)

    def test_throttle_burn_still_happens_when_engine_on(self):
        state = _state(self.world, *self.deep)
        before = state.fuel
        for _ in range(30):
            state.drive(0.1, 1.0, 0.0, self.world)
        self.assertLess(state.fuel, before)
        self.assertGreater(state.speed, 0.3)

    def test_empty_tank_stays_empty_while_idling(self):
        state = _state(self.world, *self.deep)
        state.fuel = 0.0
        state.throttle_setting = state.throttle = 0.0
        for _ in range(20):
            state.drive(0.1, 0.0, 0.0, self.world)
        self.assertEqual(state.fuel, 0.0)

    def test_engine_state_survives_save_and_reload(self):
        state = _state(self.world, *self.deep, engine=False)
        path = Path("/tmp/trotline-engine-save.json")
        session = Session(self.world, path, state, False)
        session.save()
        loaded = State.load(path, self.world)
        self.assertFalse(loaded.engine_on)

    def test_sail_still_drives_with_engine_off(self):
        state = _state(self.world, *self.deep, engine=False)
        state.owned_boats.append("sail")
        state.boat_id = "sail"
        state.fuel = state.boat.tank
        heading, _speed = __import__("fishing.weather", fromlist=["wind_at"]).wind_at(
            state.game_minutes, state)
        state.yaw = heading + math.pi / 2
        state.sail_raised = True
        for _ in range(60):
            state.drive(0.1, 0.0, 0.0, self.world)
        self.assertGreater(state.speed, 0.5)
        self.assertEqual(state.fuel, state.boat.tank, "sailing must burn no fuel")

    def test_pause_menu_offers_engine_toggle_only_for_fuelled_boats(self):
        from .ui import pause_options
        state = _state(self.world, *self.deep)
        self.assertIn("Turn the engine off", pause_options(state))
        state.engine_on = False
        self.assertIn("Turn the engine on", pause_options(state))
        state.boat_id = "log_raft"
        state.owned_boats.append("log_raft")
        self.assertTrue(all("engine" not in item.lower() for item in pause_options(state)))


if __name__ == "__main__":
    unittest.main()
