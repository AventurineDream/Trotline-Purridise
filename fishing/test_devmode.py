"""Regression tests for opt-in Devmode routing and its in-memory reset guard.

These tests use a real headless Session but never open a window. Devmode itself does not save;
one Continue test seeds a disposable temporary save to compare its bytes.
"""

from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from .data import SPECIES
from .devmode import DevMode
from .game import Keys, Session
from .sim import Catch, Hook, SetLine, State
from .world import World


class DevModeTests(unittest.TestCase):
    """Exercise toggle interception, flag-off inertness, and reset confirmation."""

    def setUp(self):
        """Build a seeded headless session against a temporary, unused save path."""
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.save_path = Path(self.tempdir.name) / "unused-save.json"
        self.world = World("briar")

    def session(self, *, dev):
        """Return a deterministic session that cannot write without an explicit save call."""
        return Session(self.world, self.save_path, State.new(self.world, seed=17),
                       has_save=False, dev=dev)

    def test_grave_opens_panel_and_panel_navigation_is_consumed(self):
        """Grave opens Devmode from title, and panel arrows never navigate the title menu."""
        session = self.session(dev=True)
        title_index = session.ui.title_i
        session.tick(Keys(pressed={"grave"}), 0.0)
        self.assertTrue(session.dev_mode.open)
        session.tick(Keys(pressed={"down"}, held={"down"}), 0.0)
        self.assertEqual(session.ui.title_i, title_index)
        self.assertEqual(session.dev_mode.selected, 1)
        session.tick(Keys(pressed={"esc"}), 0.0)
        self.assertFalse(session.dev_mode.open)
        self.assertEqual(session.ui.title_i, title_index)

    def test_grave_toggle_uses_physical_key_before_action_remapping(self):
        """The unbound physical grave key still opens Devmode after session input normalization."""
        from types import SimpleNamespace

        session = self.session(dev=True)
        keys = SimpleNamespace(
            keyboard_pressed={"grave"}, keyboard_held={"grave"},
            gamepad_pressed=set(), gamepad_held=set(),
            pressed={"grave"}, held={"grave"}, quit=False, focused=True,
            device="keyboard",
        )
        session.tick(keys, 0.0)
        self.assertTrue(session.dev_mode.open)
        session.dev_mode.open = False
        session.state.money = 46.0
        session.dev_mode.handle({"grave"}, {"return"})
        self.assertTrue(session.dev_mode.open)
        self.assertEqual(session.state.money, 46.0)
        self.assertEqual(session.dev_mode.selected, 0)

    def test_devmode_cheats_do_not_write_save_file(self):
        """Cheats and an explicit save request stay in memory during a Devmode run."""
        session = self.session(dev=True)
        session.dev_mode.execute(0)
        session.save()
        self.assertEqual(session.state.money, 1046.0)
        self.assertFalse(self.save_path.exists())

    def test_dev_flag_off_leaves_grave_inert(self):
        """Without --dev the grave key changes neither screen nor core game state."""
        session = self.session(dev=False)
        before = (session.ui.mode, session.ui.title_i, session.state.money,
                  dict(session.state.bait), session.state.game_minutes, session.state.rng.s)
        session.tick(Keys(pressed={"grave"}), 0.0)
        after = (session.ui.mode, session.ui.title_i, session.state.money,
                 dict(session.state.bait), session.state.game_minutes, session.state.rng.s)
        self.assertIsNone(session.dev_mode)
        self.assertEqual(after, before)

    def test_persistent_devmode_marker_includes_perf_readout(self):
        """The opt-in badge carries smoothed frame timing and honest memory values."""
        from types import SimpleNamespace

        session = self.session(dev=True)
        session.dev_mode.perf = (60.0, 9.8, 312.0, 420.0)
        rendered, panels = [], []
        ui = SimpleNamespace(
            _size=lambda frame, kind: 12,
            _panel=lambda *args: panels.append(args),
            _text=lambda frame, text, *args: rendered.append(text),
        )
        import numpy as np

        session.dev_mode.draw(np.zeros((675, 1200, 3), np.uint8), ui)
        _frame, x, _y, width, _height, _alpha = panels[0]
        self.assertEqual(x, (1200 - width) // 2)
        self.assertTrue(any("DEV  60 fps  9.8 ms  312+420 MB" in text for text in rendered))
        self.assertIsNone(self.session(dev=False).dev_mode)

    def test_open_panel_never_shares_space_with_the_perf_badge(self):
        """The badge stays above the open panel, or yields to it on short frames."""
        from types import SimpleNamespace

        import numpy as np

        session = self.session(dev=True)
        session.dev_mode.open = True
        for height, width, badge_shown in ((675, 1200, True), (360, 640, False)):
            panels = []
            ui = SimpleNamespace(
                _size=lambda frame, kind: 12,
                cell=lambda size: (size // 2, size),
                _panel=lambda *args, sink=panels: sink.append(args),
                _text=lambda *args: None,
            )
            session.dev_mode.draw(np.zeros((height, width, 3), np.uint8), ui)
            self.assertEqual(len(panels), 2 if badge_shown else 1)
            if badge_shown:
                (_f, _x, badge_y, _w, badge_h, _a), (_f2, _x2, panel_y, *_rest) = panels
                self.assertLessEqual(badge_y + badge_h, panel_y)

    def test_reset_cancel_preserves_state_and_confirm_starts_memory_only_session(self):
        """Cancel keeps the same state; confirmation resets it without writing a save."""
        session = self.session(dev=True)
        dev = session.dev_mode
        original = session.state
        original_money = original.money
        dev.execute(8)
        self.assertTrue(dev.confirming_reset)
        self.assertFalse(dev.confirm_reset(False))
        self.assertIs(session.state, original)
        self.assertEqual(session.state.money, original_money)

        dev.execute(8)
        self.assertTrue(dev.confirm_reset(True))
        self.assertIsNot(session.state, original)
        self.assertEqual(session.state.money, 46.0)
        self.assertFalse(self.save_path.exists())
    def test_reset_confirmation_closes_panel_and_prioritizes_select(self):
        """A confirmation press wins over simultaneous menu navigation and closes the overlay."""
        session = self.session(dev=True)
        dev = session.dev_mode
        original = session.state
        dev.open = True
        dev.execute(8)
        dev.reset_choice = 0

        consumed = dev.handle(set(), {"return", "down"})

        self.assertTrue(consumed)
        self.assertFalse(dev.confirming_reset)
        self.assertFalse(dev.open)
        self.assertIsNot(session.state, original)
        self.assertEqual(session.state.money, 46.0)
        self.assertFalse(self.save_path.exists())

    def test_grave_toggle_works_from_direct_keys_without_physical_metadata(self):
        """Headless Keys callers can toggle using their aggregate pressed-key set."""
        dev = DevMode(self.session(dev=False))
        self.assertTrue(dev.handle({"grave"}, set()))
        self.assertTrue(dev.open)
        self.assertTrue(dev.handle({"grave"}, set()))
        self.assertFalse(dev.open)


    def test_money_refill_and_starter_kit_respect_box_capacity(self):
        session = self.session(dev=True)
        dev = session.dev_mode
        state = session.state
        before = state.money
        dev.execute(0)
        self.assertEqual(state.money, before + 1000)
        state.bait = {"worm": state.box_cap() - 1}
        dev.execute(1)
        self.assertEqual(state.bait_count(), state.box_cap())
        dev.execute(2)
        self.assertEqual(state.bait_count(), state.box_cap())
        self.assertEqual(state.money, before + 2000)

    def test_hour_advances_once_and_fill_without_lines_reports_status(self):
        session = self.session(dev=True)
        dev = session.dev_mode
        before = session.state.game_minutes
        dev.execute(3)
        self.assertEqual(session.state.game_minutes, before + 60)
        self.assertTrue(dev.skip_world_tick)
        dev.execute(5)
        self.assertEqual(dev.message, "Set a line first.")

    def test_selected_standard_fish_is_deterministic_and_updates_journal(self):
        session = self.session(dev=True)
        state, dev = session.state, session.dev_mode
        line = SetLine("std", "worm", 0, 0, 10, 0, "flats",
                       [Hook(True), Hook(True)])
        state.lines.append(line)
        before_rng = state.rng.s

        dev.execute(4)

        catch = line.hooks[0].catch
        self.assertIsNotNone(catch)
        self.assertEqual(catch.species, SPECIES[0].id)
        self.assertEqual(catch.hour, 6.0)
        self.assertFalse(catch.legendary)
        self.assertFalse(line.hooks[0].baited)
        self.assertEqual(state.journal[catch.species]["count"], 1)
        self.assertEqual(state.hooked_total, 1)
        self.assertEqual(state.rng.s, before_rng)

    def test_fill_first_line_preserves_catches_and_avoids_global_duplicates(self):
        session = self.session(dev=True)
        state, dev = session.state, session.dev_mode
        first_catch = Catch(SPECIES[0].id, 0.4, 1.0, 0.0,
                            "flats", "worm", 6.0)
        other_line_catch = Catch(SPECIES[1].id, 0.5, 1.0, 0.0,
                                 "flats", "worm", 6.0)
        first = SetLine("std", "worm", 0, 0, 10, 0, "flats",
                        [Hook(False, first_catch), Hook(True), Hook(True), Hook(True)])
        other = SetLine("std", "worm", 10, 0, 20, 0, "flats",
                        [Hook(False, other_line_catch)])
        state.lines = [first, other]
        before_rng = state.rng.s

        dev.execute(5)

        catches = [hook.catch for line in state.lines for hook in line.hooks
                   if hook.catch is not None]
        species_ids = [catch.species for catch in catches]
        self.assertIs(first.hooks[0].catch, first_catch)
        self.assertIs(other.hooks[0].catch, other_line_catch)
        self.assertEqual(len(species_ids), 5)
        self.assertEqual(len(species_ids), len(set(species_ids)))
        self.assertEqual(state.hooked_total, 3)
        self.assertEqual(state.rng.s, before_rng)
        self.assertEqual(dev.message, "Placed 3 fish on the first line.")


    def test_change_lake_selector_includes_locked_routes_and_reset_refreshes_npcs(self):
        session = self.session(dev=True)
        dev = session.dev_mode
        from .lakes import LAKES, travel_unlocked
        self.assertEqual(dev.available_lakes(), list(LAKES))
        target = next(lake for lake in LAKES if not travel_unlocked(session.state, lake))
        dev.lake_index = dev.available_lakes().index(target)
        dev.execute(6)
        self.assertTrue(travel_unlocked(session.state, target))
        self.assertEqual(session.state.lake_id, target)
        dev.execute(8)
        self.assertTrue(dev.confirm_reset(True))
        self.assertTrue(session.state.npcs)


    def test_unsafe_lake_change_does_not_unlock_or_move(self):
        session = self.session(dev=True)
        state, dev = session.state, session.dev_mode
        target = next(lake_id for lake_id in dev.available_lakes()
                      if lake_id not in {"briar", "cedar"})
        dev.lake_index = dev.available_lakes().index(target)
        state.lines.append(SetLine("std", "worm", 0, 0, 10, 0, "flats", [Hook(True)]))
        old_world = session.world
        old_lake = state.lake_id

        dev.execute(6)

        self.assertIs(session.world, old_world)
        self.assertEqual(state.lake_id, old_lake)
        self.assertNotIn(f"travel:{target}", state.v2.get("unlocks", []))
        self.assertIn("Pick up", dev.message)


    def test_open_panel_owns_play_input_and_enter_runs_only_cheat(self):
        session = self.session(dev=True)
        session.ui.mode = "play"
        session.dev_mode.open = True
        session.dev_mode.selected = 0
        before = (session.state.throttle, session.state.throttle_setting,
                  session.state.steer, session.state.yaw, session.state.money)

        session.tick(Keys(pressed={"return"}, held={"w", "a"}), 0.1)

        after = (session.state.throttle, session.state.throttle_setting,
                 session.state.steer, session.state.yaw, session.state.money)
        self.assertEqual(after[:3], before[:3])
        self.assertAlmostEqual(after[3], before[3])
        self.assertEqual(after[4], before[4] + 1000)
    def test_mouse_input_is_consumed_while_panel_owns_frame(self):
        session = self.session(dev=True)
        session.ui.mode = "journal"
        session.ui.book_ceremony = True
        session.dev_mode.open = True

        session.tick(Keys(mouse_click=(20, 20), mouse_wheel=1), 0.0)
        self.assertTrue(session.ui.book_ceremony)

        session.ui.book_ceremony = False
        before_entry = session.ui.book_entry_i
        session.tick(Keys(mouse_wheel=1), 0.0)
        self.assertEqual(session.ui.book_entry_i, before_entry)
    def test_old_lantern_impossible_precondition_preserves_state(self):
        session = self.session(dev=True)
        state = session.state
        state.lines.append(object())
        before = (dict(state.bait), state.x, state.z, state.yaw, state.game_minutes,
                  state.light, list(state.lines))
        session.dev_mode.execute(7)
        self.assertEqual((dict(state.bait), state.x, state.z, state.yaw, state.game_minutes,
                          state.light, list(state.lines)), before)

    def test_old_lantern_fixture_uses_real_legendary_hook(self):
        session = self.session(dev=True)
        state, dev = session.state, session.dev_mode
        before_rng = state.rng.s

        dev.execute(7)

        catch = next((hook.catch for line in state.lines for hook in line.hooks
                      if hook.catch is not None), None)
        self.assertIsNotNone(catch, dev.message)
        self.assertEqual(catch.species, "old_lantern")
        self.assertTrue(catch.legendary)
        self.assertEqual(state.game_minutes % 1440, 15 * 60)
        self.assertTrue(state.light)
        self.assertEqual(state.rng.s, before_rng)

    def test_old_lantern_encounter_miss_rolls_back_fixture(self):
        session = self.session(dev=True)
        state, dev = session.state, session.dev_mode
        state.v2.setdefault("legendaries", {}).setdefault("old_lantern", {})[
            "records"
        ] = [{"game_minute": state.game_minutes}]
        before = (
            dict(state.bait), list(state.held), list(state.lines), state.preferred_bait,
            state.x, state.z, state.yaw, state.game_minutes, state.minute_acc,
            state.light, state.anchored, state.speed, state.throttle,
            state.throttle_setting, state.rng.s, state.hooked_total,
        )
        before_v2 = deepcopy(state.v2)
        before_narrative = deepcopy(state.narrative)
        before_journal = deepcopy(state.journal)
        before_events = list(state.book_events)
        before_toasts = deepcopy(state.toasts)

        dev.execute(7)

        after = (
            dict(state.bait), list(state.held), list(state.lines), state.preferred_bait,
            state.x, state.z, state.yaw, state.game_minutes, state.minute_acc,
            state.light, state.anchored, state.speed, state.throttle,
            state.throttle_setting, state.rng.s, state.hooked_total,
        )
        self.assertEqual(after, before)
        self.assertEqual(state.v2, before_v2)
        self.assertEqual(state.narrative, before_narrative)
        self.assertEqual(state.journal, before_journal)
        self.assertEqual(state.book_events, before_events)
        self.assertEqual(state.toasts, before_toasts)
        self.assertIn("rolled back", dev.message.lower())




    def test_old_lantern_line_event_exception_rolls_back_fixture(self):
        """A failed quest-event callback cannot leave a temporary line or bait spent."""
        session = self.session(dev=True)
        state, dev = session.state, session.dev_mode
        before = (
            dict(state.bait), list(state.held), list(state.lines), state.preferred_bait,
            state.x, state.z, state.yaw, state.game_minutes, state.minute_acc,
            state.light, state.anchored, state.speed, state.throttle,
            state.throttle_setting, state.rng.s,
        )
        before_v2 = deepcopy(state.v2)
        before_narrative = deepcopy(state.narrative)
        previous_handler = state._quest_event_handler

        def fail_line_event(_state, event):
            if event["type"] == "line.set":
                raise RuntimeError("line-set event failed")

        state._quest_event_handler = fail_line_event
        dev.execute(7)
        state._quest_event_handler = previous_handler

        after = (
            dict(state.bait), list(state.held), list(state.lines), state.preferred_bait,
            state.x, state.z, state.yaw, state.game_minutes, state.minute_acc,
            state.light, state.anchored, state.speed, state.throttle,
            state.throttle_setting, state.rng.s,
        )
        self.assertEqual(after, before)
        self.assertEqual(state.v2, before_v2)
        self.assertEqual(state.narrative, before_narrative)
        self.assertIn("line-set event failed", dev.message)

    def test_open_devmode_does_not_capture_physical_key_in_settings(self):
        """The overlay owns physical-key metadata before a Settings binding capture."""
        from types import SimpleNamespace

        session = self.session(dev=True)
        session.ui.mode = "settings"
        session.ui.settings_page = "keys"
        session.ui.capturing_key = True
        bindings = deepcopy(session.state.v2["settings"]["key_bindings"])
        session.dev_mode.open = True
        keys = SimpleNamespace(
            keyboard_pressed={"p"}, keyboard_held=set(), keyboard_press_order=["p"],
            physical_keyboard_pressed={"p"}, physical_keyboard_held={"p"},
            physical_keyboard_press_order=["p"], gamepad_pressed=set(), gamepad_held=set(),
            pressed=set(), held=set(), quit=False, focused=True, device="keyboard",
            mouse_click=None, mouse_wheel=0, viewport=(1280, 720),
        )

        session.tick(keys, 0.0)

        self.assertTrue(session.ui.capturing_key)
        self.assertEqual(session.state.v2["settings"]["key_bindings"], bindings)

    def test_continue_keeps_dev_cheats_in_memory_without_overwriting_save(self):
        state = State.new(self.world, seed=17)
        state.save(self.save_path)
        saved_bytes = self.save_path.read_bytes()
        session = Session(self.world, self.save_path, state, has_save=True, dev=True)
        session._title_catchup_pending = False
        session.dev_mode.execute(0)
        expected_money = state.money

        session.tick(Keys(pressed={"return"}), 0.0)

        self.assertEqual(session.ui.mode, "play")
        self.assertEqual(session.state.money, expected_money)
        self.assertEqual(self.save_path.read_bytes(), saved_bytes)
if __name__ == "__main__":
    unittest.main()
