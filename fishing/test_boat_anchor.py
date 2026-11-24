"""Issue #151: manual anchoring, drop-at-speed jerk, and preserved propulsion.

Anchoring is manual by default; ``settings.auto_anchor`` restores the old
throttle-lift convenience. Dropping anchor at speed applies a short hard
decel, and throttle/sail state survives the drop so the engine is never
idled or shut off by the anchor itself.
"""
import unittest

from .savepaths import merge_v2_defaults
from .sim import State
from .world import World


def _state() -> State:
    world = World("briar")
    state = State.new(world, seed=151)
    state.v2 = merge_v2_defaults(state, {})
    spot = world.anchors["briar:deep"].position
    state.x, state.z = spot
    state.anchored = False
    return state


def _drive(state: State, world: World, seconds: float, throttle: float = 0.0) -> None:
    for _ in range(int(seconds / 0.1)):
        state.drive(0.1, throttle, 0.0, world)


class ManualAnchorTests(unittest.TestCase):
    def test_manual_anchor_is_the_default(self):
        state = _state()
        self.assertFalse(state.v2["settings"]["auto_anchor"])
        self.assertFalse(state._auto_anchor())

    def test_throttle_never_lifts_anchor_by_default(self):
        state = _state()
        world = World("briar")
        state.set_anchored(True)
        _drive(state, world, 2.0, throttle=1.0)
        self.assertTrue(state.anchored)
        self.assertEqual(state.speed, 0.0)

    def test_auto_anchor_setting_restores_throttle_lift(self):
        state = _state()
        world = World("briar")
        state.v2["settings"]["auto_anchor"] = True
        state.set_anchored(True)
        state.drive(0.1, 1.0, 0.0, world)
        self.assertFalse(state.anchored)

    def test_sail_raise_respects_manual_anchor(self):
        state = _state()
        state.owned_boats.append("sail")
        state.boat_id = "sail"
        state.set_anchored(True)
        state.toggle_sail()
        self.assertTrue(state.anchored)
        self.assertTrue(state.sail_raised)
        state.v2["settings"]["auto_anchor"] = True
        state.set_anchored(True)
        state.sail_raised = False
        state.toggle_sail()
        self.assertFalse(state.anchored)

    def test_drop_at_speed_jerks_then_crawls_without_killing_engine(self):
        state = _state()
        world = World("briar")
        _drive(state, world, 8.0, throttle=1.0)
        self.assertGreater(state.speed, 0.8, "setup never reached speed")
        state.throttle_setting = 0.8
        state.sail_raised = True
        before = state.speed
        state.set_anchored(True)
        self.assertAlmostEqual(state.speed, before * 0.55, places=6)
        self.assertGreater(state._anchor_settle, 0.0)
        self.assertEqual(state.throttle_setting, 0.8, "lever must survive the drop")
        self.assertTrue(state.sail_raised, "sail must survive the drop")
        _drive(state, world, 6.0)
        self.assertLess(state.speed, 0.2, "anchored hull never settled")
        self.assertEqual(state.throttle, 0.0)
        self.assertEqual(state.throttle_setting, 0.8)
        self.assertTrue(state.sail_raised)

    def test_anchor_lift_resumes_saved_propulsion(self):
        state = _state()
        world = World("briar")
        _drive(state, world, 6.0, throttle=1.0)
        state.throttle_setting = 0.7
        state.set_anchored(True)
        _drive(state, world, 2.0)
        state.set_anchored(False)
        _drive(state, world, 6.0)
        self.assertGreater(state.speed, 0.4, "engine never came back after anchor up")

    def test_idle_drop_has_no_jerk(self):
        state = _state()
        state.set_anchored(True)
        self.assertEqual(state._anchor_settle, 0.0)
        self.assertEqual(state.speed, 0.0)

    def test_auto_anchor_setting_survives_save_defaults(self):
        state = _state()
        state.v2["settings"]["auto_anchor"] = True
        merged = merge_v2_defaults(state, state.v2)
        self.assertTrue(merged["settings"]["auto_anchor"])


if __name__ == "__main__":
    unittest.main()
