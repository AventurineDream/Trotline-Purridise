"""Bulk-advance memo (#140): memoized, evicting and memo-free soaks land alike.

`State._advance_hours` shares one `sim._BulkMemo` across its whole-hour spans: each hook
point's ground (zone, depth) and each baited hook's bite total, keyed by every input
`species_rates` reads. The memo may only save work. These checks replay one seeded offline
soak three ways: with the memo, with a memo so small its maps keep starting over, and with no
memo at all (the path live minutes take). Each run must leave the same full save, the same
lines, hooks and catches to the last float, and the same toasts, book events and quest events.
The soaks hold a baited hook that never bites, so its remembered total draws hour after hour,
and Nebula current lines whose hook points move, then settle at the drift cap. A direct check
gives every input that changes within one advance its own remembered total, and another steps
those lines beside the drift rule without its settled-line shortcut, span by span.
"""

from contextlib import ExitStack
from copy import deepcopy
from dataclasses import replace
import math
import unittest
from unittest.mock import patch

from . import bottools, sim
from .data import hour_of_day
from .sim import Hook, SetLine, State
from .world import World

START = 1_000.0  # the stamp every soak here starts from, epoch seconds
# Real seconds away; offline, each replays one game minute. Briar's 216 game hours and 37
# minutes pass Mayfly Morning, Firefly Night and a week seam; the 37 run unmemoized.
BRIAR_AWAY = 9 * 24 * 60 + 37
# Nebula's 96 game hours and 23 minutes: the current lines drift for most of four days, then
# sit settled at the drift cap for the rest, so the memo runs see both kinds of span.
NEBULA_AWAY = 4 * 24 * 60 + 23
SETTLE_HOURS = 120  # hourly drift spans the direct check steps; both lines settle near 82
SMALL = 16  # MAX_ENTRIES small enough that both soaks empty both maps over and over
# 23:00 on a plain Nebula weekday, noon that day, and 23:00 on Meteor Shower night.
PLAIN_NIGHT = 4 * 1440 + 17 * 60
PLAIN_NOON = 4 * 1440 + 6 * 60
METEOR_NIGHT = 3 * 1440 + 17 * 60


def memo_free():
    """Bulk advances inside this patch run with no memo, the way live minutes run.

    `State._advance_hours` makes its memo through the module name `_BulkMemo`; a None memo
    sends every ground and rate question straight to the world and `species_rates`.
    """
    return patch.object(sim, "_BulkMemo", lambda: None)


def small_memo():
    """Bulk memos inside this patch empty a map whenever it holds SMALL answers."""
    return patch.object(sim._BulkMemo, "MAX_ENTRIES", SMALL)


def replay(world, build, seconds, *memo):
    """Catch a fresh `build()` up `seconds` real seconds under the `memo` patches.

    Args:
        world: The lake `build` sets lines on; its ground reads are counted.
        build: Makes the seeded state to soak; called once per replay.
        seconds: Real seconds away.
        memo: Patches choosing the memo, from `memo_free` or `small_memo`; none for the
            game's own.

    Returns:
        What the soak left: the full save, the lines with their hooks and catches as exact
        floats (the save rounds coordinates), toasts, book events and the quest events sent.
        Then how many ground reads reached the world and rate reads reached `species_rates`.
    """
    state = build()
    events = []
    state._quest_event_handler = lambda _state, event: events.append(deepcopy(event))
    with ExitStack() as stack:
        for patcher in memo:
            stack.enter_context(patcher)
        ground = stack.enter_context(patch.object(world, "zone_at", wraps=world.zone_at))
        rates = stack.enter_context(patch.object(sim, "species_rates", wraps=sim.species_rates))
        state.catch_up(now=state.stamp + seconds)
    outcome = {"save": state.to_json(), "lines": deepcopy(state.lines),
               "toasts": list(state.toasts), "book_events": deepcopy(state.book_events),
               "quest_events": events}
    return outcome, (ground.call_count, rates.call_count)


def ask(state, memo, *, zone, bait, minute, weather, depth, chime):
    """`state._hook_rates` for one baited hook at game minute `minute`, as `_one_span` asks.

    Returns:
        (species rates or None for a remembered total, total bites per game hour).
    """
    state.game_minutes = minute
    hour = hour_of_day(minute)
    tool = bottools.ToolState(bottools.cold_layer_m(state.lake_id, hour, weather), chime,
                              state.owns_tool("zero_g_winch"), "silent" in state.boat.traits)
    return state._hook_rates(zone, bait, hour, weather, depth, tool, memo)


def drift_without_shortcut(state, world, minutes):
    """`State.drift_lines` as it was before its settled-line shortcut (#140): every step of
    every current line takes the wet and spacing checks. The reference for the shortcut."""
    if minutes <= 0 or state.owns_tool("zero_g_winch"):
        return
    for line in state.lines:
        if line.zone != "current":
            continue
        if line.drift_origin is None:
            line.drift_origin = (line.x0, line.z0, line.x1, line.z1)
        ox0, oz0, ox1, oz1 = line.drift_origin
        mid_x, mid_z = (line.x0 + line.x1) * 0.5, (line.z0 + line.z1) * 0.5
        flow_x, flow_z = bottools.flow_at(mid_x, mid_z)
        off_x = mid_x - (ox0 + ox1) * 0.5 + flow_x * minutes
        off_z = mid_z - (oz0 + oz1) * 0.5 + flow_z * minutes
        reach = math.hypot(off_x, off_z)
        if reach > bottools.DRIFT_CAP_M:
            off_x *= bottools.DRIFT_CAP_M / reach
            off_z *= bottools.DRIFT_CAP_M / reach
        moved = replace(line, x0=ox0 + off_x, z0=oz0 + off_z, x1=ox1 + off_x, z1=oz1 + off_z)
        ends_wet = all(world.navigable(px, pz) for px, pz in
                       ((moved.x0, moved.z0), (moved.x1, moved.z1)))
        if ends_wet and not any(other is not line
                                and sim._seg_gap(moved, other) < bottools.DRIFT_MIN_GAP_M
                                for other in state.lines):
            line.x0, line.z0, line.x1, line.z1 = moved.x0, moved.z0, moved.x1, moved.z1


def ends(state):
    """Every line's endpoints and drift origin, as exact bits (`float.hex`, so -0.0 != 0.0)."""
    return [tuple(value.hex() for value in (line.x0, line.z0, line.x1, line.z1))
            + (line.drift_origin and tuple(value.hex() for value in line.drift_origin),)
            for line in state.lines]


class BulkMemoChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.briar = World()
        cls.nebula = World("nebula")

    @staticmethod
    def soaker(world, lines):
        """A new game on `world` with `lines` set and no toasts, last saved at START."""
        state = State.new(world, seed=140)
        state.lines = lines
        state.toasts.clear()
        state.stamp = START
        return state

    def briar_soak(self):
        """Two well-baited Briar lines and a deep line on stardust, which barely bites there.

        The chime rang on the deep line just before closing, so its first hour asks with
        the chime and the same hour a day later without it.
        """
        def line(k, spot, baits, hooks):
            x, z = self.briar.anchors[f"briar:{spot}"].position
            return SetLine("std", baits, x - 30, z, x + 30, z, self.briar.zone_at(x, z),
                           [Hook(True) for _ in range(hooks)], line_id=f"memo-{k}")

        state = self.soaker(self.briar, [line(0, "flats", ["worm", "shad", "liver"], 12),
                                         line(1, "lilies", ["liver", "worm"], 12),
                                         line(2, "deep", ["stardust"], 4)])
        state.lines[2].chime_until = state.game_minutes + bottools.CHIME_LAST_MINUTES
        return state

    def nebula_soak(self):
        """Two lines in Nebula's current, the second on grub, which barely bites there, and
        one in open water, which no current moves."""
        def line(k, spot, baits):
            x, z = self.nebula.anchors[f"nebula:{spot}"].position
            return SetLine("std", baits, x - 10, z, x + 10, z, self.nebula.zone_at(x, z),
                           [Hook(True) for _ in range(6)], line_id=f"memo-{k}")

        return self.soaker(self.nebula, [line(0, "current", ["stardust", "moonmilk_stardust"]),
                                         line(1, "fast_current", ["grub"]),
                                         line(2, "far_open", ["grub", "worm"])])

    def assert_same_replay(self, world, build, seconds):
        """Replay `build` memoized, small-memoized and memo-free; all must land alike.

        Returns:
            The memo-free outcome, for the scenario's own preconditions.
        """
        free, free_reads = replay(world, build, seconds, memo_free())
        memo, memo_reads = replay(world, build, seconds)
        small, small_reads = replay(world, build, seconds, small_memo())
        for name, outcome in (("memo", memo), ("small memo", small)):
            for key in free:
                with self.subTest(run=name, part=key):
                    self.assertEqual(outcome[key], free[key])
        # Preconditions, so the equality means something: the memo answered questions the
        # memo-free run sent on to the world and `species_rates`, and the small memo,
        # starting over, sent some of them on again.
        for read, label in enumerate(("ground", "rates")):
            with self.subTest(reads=label):
                self.assertLess(memo_reads[read], free_reads[read])
                self.assertLess(memo_reads[read], small_reads[read])
        self.assertGreater(free["save"]["hooked_total"], 0)
        return free

    def test_nine_days_of_briar_soak_land_alike_with_and_without_the_memo(self):
        free = self.assert_same_replay(self.briar, self.briar_soak, BRIAR_AWAY)
        # A stardust hook still baited and empty never bit, so it drew every hour of the
        # soak; with the memo, from a remembered total whenever its key came round again.
        self.assertTrue(any(hook.baited and hook.catch is None for hook in free["lines"][2].hooks))

    def test_nebula_current_lines_drift_and_land_alike_with_and_without_the_memo(self):
        set_at = [(line.x0, line.z0, line.x1, line.z1) for line in self.nebula_soak().lines]
        free = self.assert_same_replay(self.nebula, self.nebula_soak, NEBULA_AWAY)
        # The current carried both current lines off their set points, then held them settled
        # at the cap, so their hooks asked at new points (the memo runs moved them
        # identically); the open line held still.
        drifted = [(line.x0, line.z0, line.x1, line.z1) for line in free["lines"]]
        self.assertNotEqual(drifted[0], set_at[0])
        self.assertNotEqual(drifted[1], set_at[1])
        self.assertEqual(drifted[2], set_at[2])
        self.assertEqual([line.drift_origin for line in free["lines"]],
                         [set_at[0], set_at[1], None])
        self.assertTrue(any(hook.baited and hook.catch is None for hook in free["lines"][1].hooks))

    def test_settled_current_lines_skip_only_drift_checks_that_cannot_move_them(self):
        # Step the Nebula soak's lines hour by hour, once through `drift_lines` and once
        # through the rule without its shortcut. Every span must leave the same bits. A span
        # that moved a line must still probe the water; one where every line stood settled
        # must probe neither the water nor the spacing.
        state, reference = self.nebula_soak(), self.nebula_soak()
        moving = settled = 0
        for hour in range(SETTLE_HOURS):
            before = ends(state)
            with patch.object(self.nebula, "navigable", wraps=self.nebula.navigable) as wet, \
                    patch.object(sim, "_seg_gap", wraps=sim._seg_gap) as gap:
                state.drift_lines(self.nebula, 60.0)
            drift_without_shortcut(reference, self.nebula, 60.0)
            with self.subTest(hour=hour):
                self.assertEqual(ends(state), ends(reference))
                if ends(state)[:2] == before[:2]:
                    settled += 1
                    self.assertEqual((wet.call_count, gap.call_count), (0, 0))
                else:
                    moving += 1
                    self.assertGreater(wet.call_count, 0)
        # Both kinds of span happened, and the soak's two current lines ended settled at
        # the cap, well away from where they were set.
        self.assertGreater(moving, 0)
        self.assertGreater(settled, 0)
        for line in state.lines[:2]:
            ox0, oz0, ox1, oz1 = line.drift_origin
            reach = math.hypot((line.x0 + line.x1 - ox0 - ox1) * 0.5,
                               (line.z0 + line.z1 - oz0 - oz1) * 0.5)
            self.assertAlmostEqual(reach, bottools.DRIFT_CAP_M, places=6)

    def test_each_input_that_changes_within_an_advance_keys_its_own_total(self):
        # Two asks sharing one memo, apart in a single input, must each come back as a
        # memo-free ask does. A key without that input would hand the second ask the first's
        # total.
        state = State.new(self.nebula, seed=140)
        base = {"zone": "current", "bait": "stardust", "minute": PLAIN_NIGHT,
                "weather": "clear", "depth": 37.0, "chime": False}
        changes = {"zone": {"zone": "open"}, "bait": {"bait": "grub"},
                   "hour": {"minute": PLAIN_NOON}, "weather": {"weather": "aurora"},
                   "depth": {"depth": 20.0}, "Lake Day": {"minute": METEOR_NIGHT},
                   "chime": {"chime": True}}
        for name, change in changes.items():
            with self.subTest(input=name):
                changed = {**base, **change}
                first, fresh = ask(state, None, **base), ask(state, None, **changed)
                self.assertNotEqual(fresh[1], first[1], "this input should move the total")
                memo = sim._BulkMemo()
                self.assertEqual(ask(state, memo, **base), first)
                self.assertEqual(ask(state, memo, **changed), fresh)
                # Asked again, each comes back from the memo as the same float.
                self.assertEqual(ask(state, memo, **base)[1], first[1])
                self.assertEqual(ask(state, memo, **changed)[1], fresh[1])


if __name__ == "__main__":
    unittest.main()
