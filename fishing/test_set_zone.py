"""Issue #152: restricted water warns before the bait menu, for five seconds.

F in a no-line zone must never open bait selection or spend bait; the same
water rules guard ``try_set`` on confirm. The tutorial's set-line hint hides
where no held line could be set.
"""
import math
import unittest
from pathlib import Path

from .botidentity import grant_tool
from .game import Session
from .sim import HeldLine, State
from .world import World


def _reeds_point(world):
    """A navigable point inside Briar's Reed Passage."""
    _name, cx, cz, radius = next(e for e in world.zones if e[0] == "reeds")
    for i in range(-int(radius), int(radius) + 1, 2):
        for j in range(-int(radius), int(radius) + 1, 2):
            x, z = cx + i, cz + j
            if world.zone_at(x, z) == "reeds" and world.navigable(x, z):
                return x, z
    raise AssertionError("no navigable reeds point")


def _pose_for_error(world, state, x, z, needle):
    """A yaw whose prospective line fails with `needle`, scanning like _pose."""
    for k in range(36):
        yaw = k * math.tau / 36.0
        state.x, state.z, state.yaw = x, z, yaw
        state.speed = 0.0
        error = state.line_zone_error(world, state.held[0].hooks)
        if error and needle in error:
            return yaw
    raise AssertionError(f"no yaw produced {needle!r} at {x},{z}")


def _open_pose(world, state, x, z):
    """A yaw where a std line sets cleanly, or None."""
    state.lines.clear()
    for k in range(36):
        yaw = k * math.tau / 36.0
        state.x, state.z, state.yaw = x, z, yaw
        state.speed = 0.0
        if state.line_zone_error(world, state.held[0].hooks) is None:
            return yaw
    return None


class RestrictedZoneWarning(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World("briar")

    def _session(self, x, z, yaw):
        state = State.new(self.world, seed=152)
        state.x, state.z, state.yaw = x, z, yaw
        state.speed = 0.0
        state.anchored = False
        session = Session(self.world, Path("/tmp/trotline-zone-warning.json"), state, False)
        session.ui.mode = "play"
        return session, state

    def test_landing_zone_warns_for_five_seconds_without_opening_menu(self):
        x, z = self.world.anchors["briar:landing"].position
        probe = State.new(self.world, seed=1)
        probe.held = [HeldLine("std")]
        yaw = _pose_for_error(self.world, probe, x, z, "no-line zone")
        session, state = self._session(x, z, yaw)
        bait_before = dict(state.bait)

        session._open_set()

        self.assertNotEqual(session.ui.mode, "setbait")
        self.assertEqual(len(state.lines), 0)
        self.assertEqual(state.bait, bait_before)
        self.assertTrue(state.toasts)
        text, seconds = state.toasts[-1]
        self.assertIn("no-line zone", text)
        self.assertEqual(seconds, 5.0)

    def test_open_water_still_opens_the_menu(self):
        x, z = self.world.anchors["briar:deep"].position
        probe = State.new(self.world, seed=1)
        probe.held = [HeldLine("std")]
        yaw = _open_pose(self.world, probe, x, z)
        if yaw is None:
            self.skipTest("no clean set pose at deep anchor")
        session, _state = self._session(x, z, yaw)

        session._open_set()

        self.assertEqual(session.ui.mode, "setbait")

    def test_reeds_refuse_without_reed_anchor_then_accept_with_it(self):
        x, z = _reeds_point(self.world)
        probe = State.new(self.world, seed=1)
        probe.held = [HeldLine("std")]
        yaw = _pose_for_error(self.world, probe, x, z, "Reed Anchor")
        session, state = self._session(x, z, yaw)

        session._open_set()
        self.assertNotEqual(session.ui.mode, "setbait")
        self.assertIn("Reed Anchor", state.toasts[-1][0])

        self.assertTrue(grant_tool(state, "reed_anchor"))
        session._open_set()
        self.assertEqual(session.ui.mode, "setbait")

    def test_reed_line_boat_sets_in_reeds_without_the_tool(self):
        x, z = _reeds_point(self.world)
        probe = State.new(self.world, seed=1)
        probe.held = [HeldLine("std")]
        yaw = _open_pose(self.world, probe, x, z)
        if yaw is None:
            self.skipTest("no clean reeds pose")
        session, state = self._session(x, z, yaw)
        state.boat_id = "reed_dugout"
        state.owned_boats.append("reed_dugout")

        session._open_set()

        self.assertEqual(session.ui.mode, "setbait")

    def test_tutorial_hint_hides_where_no_line_fits(self):
        state = State.new(self.world, seed=152)
        state.tutorial = 1
        x, z = self.world.anchors["briar:landing"].position
        state.x, state.z = x, z
        for k in range(36):
            state.yaw = k * math.tau / 36.0
            if all(state.line_zone_error(self.world, h.hooks) is not None for h in state.held):
                break
        self.assertIsNone(state.hint(self.world))

        x, z = self.world.anchors["briar:deep"].position
        state.x, state.z = x, z
        state.yaw = _open_pose(self.world, state, x, z) or 0.0
        self.assertEqual(state.hint(self.world), "Stop, then F to set a trotline")

    def test_try_set_still_rejects_restricted_water_on_confirm(self):
        x, z = self.world.anchors["briar:landing"].position
        state = State.new(self.world, seed=152)
        state.x, state.z = x, z
        state.yaw = 0.0
        state.speed = 0.0
        state.anchored = False
        bait_before = dict(state.bait)

        error = state.try_set(self.world, 0, "worm")

        self.assertIsNotNone(error)
        self.assertEqual(len(state.lines), 0)
        self.assertEqual(state.bait, bait_before)


if __name__ == "__main__":
    unittest.main()
