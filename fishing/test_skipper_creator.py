"""The Skipper creator: the screen from the pause menu and from a new morning's pace.

These drive the real key path (Session.tick with headless Keys) and check what a player
would see and save. Rows cycle the draft and the card, typing names the Skipper, Done saves
(or starts the morning), Esc discards, a gamepad can finish the screen alone, reduced motion
holds the card still, and the creator draws at every text size. Saves go to a temporary
folder. Other test modules import `finish_creator` to play through a new morning.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from . import comfort, skipperlook, skipperview, uiscreens
from .game import SKIPPER_TURN_RATE, Keys, Session
from .platform import Text
from .quests import scene_state
from .ui import GOLD, UI, _phrase_lines, _toast_for_device, pause_options
from .sim import State
from .world import World

HINT = "Dress your Skipper: Esc, then Your Skipper."


def tap(session, *names, dt: float = 0.05, held=(), device: str = "keyboard") -> None:
    """One frame with `names` pressed and `held`, from the keyboard or from the gamepad.

    A gamepad frame has no physical keyboard keys, which is how the game tells its A button
    (it sends "return" and "e") from the keyboard's E key.
    """
    keys = Keys(pressed=names, held=held)
    keys.device = device
    if device == "gamepad":
        keys.gamepad_pressed, keys.gamepad_held = set(names), set(held) | set(names)
        keys.physical_keyboard_pressed, keys.physical_keyboard_held = set(), set()
    session.tick(keys, dt)


def type_letters(session, *names) -> None:
    """One frame per physical key press, as a keyboard sends them."""
    for name in names:
        tap(session, name)


def finish_creator(session, device: str = "keyboard") -> None:
    """Drive the open creator to Done as a player does: Down to the last row, then Enter."""
    while session.ui.skipper_i < len(skipperlook.ROWS) - 1:
        tap(session, "down", device=device)
    tap(session, "return", device=device)


ROW = {key: index for index, (key, _label) in enumerate(skipperlook.ROWS)}


class SkipperCreatorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="trotline-skipper-")
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "save.json"
        self.world = World()
        self.state = State.new(self.world, seed=42031)
        self.session = Session(self.world, self.path, self.state, False)
        self.text = Text()
        self.addCleanup(self.text.close)
        self.ui = UI(self.text, self.world)

    # --- helpers ----------------------------------------------------------------------
    def open_from_pause(self, device: str = "keyboard") -> None:
        self.session.ui.mode = "pause"
        self.session.ui.pause_i = pause_options(self.state).index("Your Skipper")
        tap(self.session, "return", device=device)
        self.assertEqual(self.session.ui.mode, "skipper")

    def look(self) -> dict:
        return self.session.ui.skipper_look

    def frame(self, width: int = 1280, height: int = 720) -> np.ndarray:
        return np.zeros((height, width, 3), np.uint8)

    # --- entry, rows and the card -----------------------------------------------------
    def test_the_pause_menu_offers_your_skipper_after_the_livewell(self):
        options = pause_options(self.state)
        self.assertEqual(options[options.index("Livewell") + 1], "Your Skipper")

    def test_escape_from_the_pause_creator_discards_the_draft_and_saves_nothing(self):
        self.session.save()
        saved_bytes = self.path.read_bytes()
        before = deepcopy(self.state.v2["skipper"])
        self.open_from_pause()
        self.assertEqual(self.session.ui.skipper_origin, "pause")
        tap(self.session, "down")  # Pattern
        tap(self.session, "right")
        self.assertNotEqual(self.look()["pattern"], before["pattern"])
        tap(self.session, "esc")
        self.assertEqual(self.session.ui.mode, "pause")
        self.assertEqual(self.state.v2["skipper"], before)
        self.assertEqual(self.path.read_bytes(), saved_bytes)

    def test_rows_change_the_draft_and_the_card(self):
        self.open_from_pause()
        ui = self.session.ui
        before_look = deepcopy(self.look())
        before_card = skipperview.preview(self.look(), ui.skipper_clock, ui.skipper_turn, 200, False, 99.0)
        tap(self.session, "down")  # Pattern
        tap(self.session, "right")
        self.assertNotEqual(self.look(), before_look)
        self.assertEqual(ui.skipper_changed_at, ui.skipper_clock)
        # Same clock and turn: only the look differs, so the card must differ too.
        after_card = skipperview.preview(self.look(), ui.skipper_clock, ui.skipper_turn, 200, False, 0.0)
        self.assertFalse(np.array_equal(before_card, after_card))

    def test_backward_and_directional_folds_preview_and_save_from_the_ears_row(self):
        """Players can choose each backward fold, see distinct previews and reload the saved value."""
        cards = []
        options = list(skipperlook.EARS)
        for ears, label in (("folded", "Folded back"), ("folded_left", "Folded left"),
                            ("folded_right", "Folded right")):
            with self.subTest(ears=ears):
                self.open_from_pause()
                for _ in range(ROW["ears"]):
                    tap(self.session, "down")
                steps = (options.index(ears) - options.index(self.look()["ears"])) % len(options)
                for _ in range(steps):
                    tap(self.session, "right")
                self.assertEqual(self.look()["ears"], ears)
                self.assertEqual(skipperlook.value_label(self.look(), "ears"), label)
                cards.append(skipperview.preview(self.look(), 0.0, 0.0, 240, True, 99.0))
                finish_creator(self.session)
                self.assertEqual(self.state.v2["skipper"]["ears"], ears)
                self.assertEqual(State.load(self.path, self.world).v2["skipper"]["ears"], ears)
        for i, card in enumerate(cards):
            for other in cards[i + 1:]:
                self.assertFalse(np.array_equal(card, other))

    def test_frame_finishes_cycle_for_specs_and_goggles_and_survive_saving(self):
        """Brass, silver, gold and rose gold label, preview and reload on both frames."""
        head_kinds = list(skipperlook.SLOTS["head"])

        def worn_head(look):
            item = next((i for i in look["attire"] if i["kind"] in head_kinds[1:]), None)
            return item["kind"] if item else "none"

        cards = []
        for kind in ("spectacles", "goggles"):
            for finish, colour in skipperlook.FRAME_FINISHES:
                with self.subTest(kind=kind, finish=finish):
                    self.open_from_pause()
                    for _ in range(ROW["head"]):
                        tap(self.session, "down")
                    steps = (head_kinds.index(kind) - head_kinds.index(worn_head(self.look()))) % len(head_kinds)
                    for _ in range(steps):
                        tap(self.session, "right")
                    self.assertEqual(worn_head(self.look()), kind)
                    for _ in range(ROW["head_color"] - ROW["head"]):
                        tap(self.session, "down")
                    self.assertTrue(skipperlook.row_enabled(self.look(), "head_color"))
                    # The frame starts at brass; step to the wanted finish and check its label.
                    for _ in range(4):
                        if skipperlook.value_label(self.look(), "head_color") == finish:
                            break
                        tap(self.session, "right")
                    self.assertEqual(skipperlook.value_label(self.look(), "head_color"), finish)
                    cards.append(skipperview.preview(self.look(), 0.0, 0.0, 240, True, 99.0))
                    finish_creator(self.session)
                    saved = self.state.v2["skipper"]["attire"]
                    frame = next(i for i in saved if i["kind"] == kind)
                    self.assertEqual(frame["color"], list(colour))
                    reloaded = State.load(self.path, self.world).v2["skipper"]["attire"]
                    self.assertEqual(next(i for i in reloaded if i["kind"] == kind)["color"], list(colour))
        for i, card in enumerate(cards):
            for other in cards[i + 1:]:
                self.assertFalse(np.array_equal(card, other))

    def test_a_row_that_changes_nothing_does_not_wave(self):
        self.open_from_pause()
        ui = self.session.ui
        for _ in range(ROW["neck_color"]):
            tap(self.session, "down")
        before = deepcopy(self.look())
        tap(self.session, "right")  # no neckwear is worn, so the colour has nothing to change
        self.assertEqual(self.look(), before)
        self.assertEqual(ui.skipper_changed_at, -99.0)

    # --- typing ------------------------------------------------------------------------
    def test_typing_a_name_saves_it_cleaned_and_marks_the_skipper_created(self):
        self.open_from_pause()
        tap(self.session, "return")  # Enter on the Name row starts typing
        self.assertTrue(self.session.ui.skipper_typing)
        # The A, D and E keys are letters here: they must not move the rows or turn the card,
        # and the M key must not mute the game.
        type_letters(self.session, "m", "a", "d", "e", "space", "b", "o", "minus", "1")
        self.assertEqual(self.look()["name"], "Made Bo-1")
        self.assertEqual(self.session.ui.skipper_i, 0)
        self.assertEqual(self.session.ui.skipper_turn, 0.0)
        self.assertFalse(self.state.muted)
        tap(self.session, "return")  # Enter sets the name
        self.assertFalse(self.session.ui.skipper_typing)
        finish_creator(self.session)
        self.assertEqual(self.session.ui.mode, "pause")
        self.assertEqual(self.state.v2["skipper"]["name"], "Made Bo-1")
        self.assertTrue(self.state.v2["skipper"]["created"])
        saved = State.load(self.path, self.world).v2["skipper"]
        self.assertEqual((saved["name"], saved["created"]), ("Made Bo-1", True))

    def test_escape_ends_typing_without_cancelling_and_an_empty_name_is_the_default(self):
        self.open_from_pause()
        tap(self.session, "return")
        for _ in range(len(self.look()["name"])):
            tap(self.session, "backspace")
        self.assertEqual(self.look()["name"], "")
        tap(self.session, "esc")
        self.assertEqual(self.session.ui.mode, "skipper")  # Esc here only ends typing
        self.assertFalse(self.session.ui.skipper_typing)
        self.assertEqual(self.look()["name"], skipperlook.DEFAULT_NAME)
        tap(self.session, "esc")
        self.assertEqual(self.session.ui.mode, "pause")

    def test_entering_the_name_selects_it_so_a_new_name_does_not_join_the_old_one(self):
        self.open_from_pause()
        tap(self.session, "return")
        tap(self.session, "esc")  # leaving without typing keeps the name
        self.assertEqual(self.look()["name"], skipperlook.DEFAULT_NAME)
        tap(self.session, "return")
        type_letters(self.session, "m")  # the first key replaces the selected name
        self.assertEqual(self.look()["name"], "M")

    def test_rebound_keyboard_select_does_not_end_name_typing(self):
        from .gamepad import set_key_binding
        self.open_from_pause()
        self.session.state.v2["settings"]["key_bindings"] = set_key_binding(None, "select", "e")
        tap(self.session, "return")
        for key in ("e", "v", "e"):
            keys = Keys(pressed={key}, held={key})
            keys.device = "keyboard"
            keys.keyboard_pressed = {key}
            keys.keyboard_held = {key}
            keys.keyboard_press_order = [key]
            self.session.tick(keys, 0.05)
        self.assertEqual(self.look()["name"], "Eve")
        self.assertTrue(self.session.ui.skipper_typing)

    def test_rebound_left_action_does_not_cycle_suggested_names_while_typing(self):
        from .gamepad import set_key_binding
        self.open_from_pause()
        self.session.state.v2["settings"]["key_bindings"] = set_key_binding(None, "steer_left", "e")
        tap(self.session, "return")
        for key in ("e", "v", "e"):
            keys = Keys(pressed={key}, held={key})
            keys.device = "keyboard"
            keys.keyboard_pressed = {key}
            keys.keyboard_held = {key}
            keys.keyboard_press_order = [key]
            self.session.tick(keys, 0.05)
        self.assertEqual(self.look()["name"], "Eve")
        self.assertTrue(self.session.ui.skipper_typing)

    def test_keyboard_q_and_e_turn_the_card_while_held_but_not_while_typing(self):
        self.open_from_pause()
        tap(self.session, "e", held=("e",), dt=0.5)
        self.assertAlmostEqual(self.session.ui.skipper_turn, SKIPPER_TURN_RATE * 0.5)
        tap(self.session, "q", held=("q",), dt=0.5)
        self.assertAlmostEqual(self.session.ui.skipper_turn, 0.0)
        tap(self.session, "return")  # start typing
        turn = self.session.ui.skipper_turn
        tap(self.session, "e", held=("e",), dt=0.5)  # a letter now
        self.assertEqual(self.session.ui.skipper_turn, turn)

    def test_shift_held_while_typing_keeps_the_throttle(self):
        # Players hold Shift out of habit for a capital; outside typing, Shift idles the boat.
        self.state.throttle_setting = self.state.throttle = 0.5
        self.open_from_pause()
        tap(self.session, "return")  # start typing
        tap(self.session, "b", held=("shift", "b"))
        self.assertEqual((self.state.throttle_setting, self.state.throttle), (0.5, 0.5))
        tap(self.session, "return")  # the name is set; Shift idles again
        tap(self.session, held=("shift",))
        self.assertEqual((self.state.throttle_setting, self.state.throttle), (0.0, 0.0))

    # --- the two origins --------------------------------------------------------------
    def test_a_new_morning_starts_only_after_the_creator_is_done(self):
        """Done starts the prologue and writes only a fresh named slot, not main."""
        session = self.session
        old_state = session.state
        session.ui.mode, session.ui.new_mode_i = "new_mode", 1  # Old Salt
        tap(session, "return")
        self.assertEqual(session.ui.mode, "skipper")
        self.assertIs(session.state, old_state)
        self.assertIsNone(scene_state(old_state, "prologue"))
        self.assertFalse(self.path.exists())  # nothing is saved before Done
        finish_creator(session)
        self.assertEqual(session.ui.mode, "dialogue")  # the prologue's first line opens on Done's frame
        self.assertIsNot(session.state, old_state)
        self.assertEqual(scene_state(session.state, "prologue"), "pending")
        self.assertEqual(comfort.mode(session.state.v2), "old_salt")
        self.assertTrue(session.state.v2["skipper"]["created"])
        # Done writes the newly allocated named slot, never the original main file.
        self.assertTrue(session.save_path.exists())
        self.assertFalse(self.path.exists())

    def test_escape_from_a_new_morning_returns_to_the_pace_choice_and_starts_nothing(self):
        session = self.session
        session.ui.mode, session.ui.new_mode_i = "new_mode", 1
        tap(session, "return")
        tap(session, "right")  # changes the draft's name, which Esc throws away
        tap(session, "esc")
        self.assertEqual(session.ui.mode, "new_mode")
        self.assertEqual(session.ui.new_mode_i, 1)
        self.assertIs(session.state, self.state)
        self.assertEqual(self.state.v2["skipper"]["name"], skipperlook.DEFAULT_NAME)
        self.assertFalse(self.path.exists())

    def test_a_gamepad_finishes_the_creator_without_a_keyboard(self):
        session = self.session
        session.ui.mode = "pause"
        session.ui.pause_i = pause_options(self.state).index("Your Skipper")
        tap(session, "return", device="gamepad")  # A sends "return" and "e"
        self.assertEqual(session.ui.mode, "skipper")
        self.assertEqual(session.ui.skipper_turn, 0.0)  # A's "e" is not the keyboard's E
        tap(session, "down", device="gamepad")  # Pattern
        tap(session, "right", device="gamepad")
        tap(session, "up", device="gamepad")  # Name
        tap(session, "return", device="gamepad")  # A starts typing
        self.assertTrue(session.ui.skipper_typing)
        tap(session, "right", device="gamepad")  # the D-pad cycles suggested names
        self.assertEqual(self.look()["name"], "Mochi")
        tap(session, "esc", device="gamepad")  # B ends typing
        self.assertFalse(session.ui.skipper_typing)
        tap(session, held=("c",), dt=0.5, device="gamepad")  # RB turns the card one way
        self.assertGreater(session.ui.skipper_turn, 0.0)
        tap(session, held=("g",), dt=0.5, device="gamepad")  # LB turns it back
        self.assertAlmostEqual(session.ui.skipper_turn, 0.0)
        finish_creator(session, device="gamepad")
        self.assertEqual(session.ui.mode, "pause")
        self.assertEqual(self.state.v2["skipper"]["name"], "Mochi")
        self.assertTrue(self.state.v2["skipper"]["created"])

    # --- the card, the frame and the world ---------------------------------------------
    def test_reduced_motion_holds_the_card_still(self):
        self.state.v2["settings"]["reduced_motion"] = True
        self.open_from_pause()
        look = self.look()
        np.testing.assert_array_equal(skipperview.preview(look, 0.0, 0.0, 240, True, 99.0),
                                      skipperview.preview(look, 7.3, 0.0, 240, True, 0.0))
        frames = []
        for clock in (0.0, 7.3):
            self.session.ui.skipper_clock = clock
            frames.append(self.frame())
            self.ui.draw(frames[-1], self.state, self.session.ui)
        np.testing.assert_array_equal(frames[0], frames[1])
        # Without reduced motion the same look does spin.
        self.assertFalse(np.array_equal(skipperview.preview(look, 0.0, 0.0, 240, False, 99.0),
                                        skipperview.preview(look, 7.3, 0.0, 240, False, 99.0)))

    def test_the_creator_is_modal_the_world_is_frozen_and_no_play_hud_draws(self):
        self.session.ui.mode = "skipper"
        self.assertFalse(self.session.world_running())
        with patch.object(UI, "_hud", side_effect=AssertionError("the play HUD drew under the creator")):
            self.ui.draw(self.frame(), self.state, self.session.ui)

    def test_the_creator_draws_at_every_text_size_and_device(self):
        for size in range(3):
            for dyslexia in (False, True):
                screens = [(name, state, panel) for name, state, panel
                           in uiscreens.screens(self.ui, self.world, dyslexia, size)
                           if name.startswith("your skipper")]
                self.assertEqual(len(screens), 3)
                for name, state, panel in screens:
                    for device in ("keyboard", "gamepad"):
                        for width, height in ((1280, 720), (480, 270)):
                            with self.subTest(screen=name, size=size, dyslexia=dyslexia, device=device,
                                              width=width):
                                frame = self.frame(width, height)
                                self.ui.draw(frame, state, replace(panel, input_device=device))
                                self.assertTrue(frame.any())

    def test_a_fresh_name_is_drawn_selected_and_a_kept_name_is_not(self):
        self.open_from_pause()
        tap(self.session, "return")  # typing; the name is selected on entry
        ui = self.session.ui
        self.assertTrue(ui.skipper_fresh)

        def draw(fresh: bool):
            """One frame, and the rectangles UI._fill drew in it."""
            ui.skipper_fresh = fresh
            frame, fills = self.frame(), []
            original = UI._fill

            def record(renderer, dst, x, y, w, h, rgb, alpha):
                fills.append((x, y, w, h))
                return original(renderer, dst, x, y, w, h, rgb, alpha)

            with patch.object(UI, "_fill", record):
                self.ui.draw(frame, self.state, ui)
            return frame, fills

        fresh_frame, fresh_fills = draw(True)
        kept_frame, kept_fills = draw(False)
        boxes = [rect for rect in fresh_fills if rect not in kept_fills]
        self.assertEqual(len(boxes), 1)  # one box, and only while the name is fresh
        x, y, w, h = boxes[0]
        self.assertTrue((fresh_frame[y:y + h, x:x + w] != kept_frame[y:y + h, x:x + w]).any())
        self.assertTrue(np.all(np.abs(fresh_frame[y, x].astype(int) - np.array(GOLD)) <= 2))

    def test_the_creator_footer_breaks_only_between_phrases(self):
        drawn = []
        original = UI._text

        def record(renderer, frame, s, x, y, size, color, shadow=True, family="mono"):
            drawn.append(s)
            return original(renderer, frame, s, x, y, size, color, shadow, family)

        with patch.object(UI, "_text", record):
            for size in range(3):
                for dyslexia in (False, True):
                    for name, state, panel in uiscreens.screens(self.ui, self.world, dyslexia, size):
                        if not name.startswith("your skipper"):
                            continue
                        for device in ("keyboard", "gamepad"):
                            ui = replace(panel, input_device=device)
                            phrases = self.ui._skipper_foot(ui).split("  ·  ")
                            for width, height in ((1280, 720), (480, 270)):
                                drawn.clear()
                                self.ui.draw(self.frame(width, height), state, ui)
                                for phrase in phrases:
                                    with self.subTest(screen=name, size=size, dyslexia=dyslexia, device=device,
                                                      width=width, phrase=phrase):
                                        # A split phrase would sit whole in neither line.
                                        self.assertTrue(any(phrase in line for line in drawn))

    def test_phrase_lines_keep_each_phrase_whole_at_every_width(self):
        hint = "W/S choose  ·  A/D change  ·  Enter picks  ·  Q/E turn  ·  Done saves  ·  Esc cancels"
        phrases = hint.split("  ·  ")
        for cells in range(12, 90):
            lines = _phrase_lines(hint, cells)
            self.assertTrue(all(len(line) <= cells for line in lines), cells)
            self.assertEqual([phrase for line in lines for phrase in line.split("  ·  ")], phrases, cells)
        # A phrase wider than a whole line is word-wrapped: the only break a line can take.
        self.assertEqual(_phrase_lines("Esc or B  ·  A very long phrase here", 12),
                         ["Esc or B", "A very long", "phrase here"])

    # --- Continue's hint ----------------------------------------------------------------
    def new_session(self, *, has_save: bool) -> Session:
        return Session(self.world, self.path, State.load(self.path, self.world), has_save)

    def test_continue_on_an_uncreated_skipper_hints_once_per_session(self):
        self.session.save()  # a save from before the creator: created is False
        shown = []
        original = State.toast

        def record(state, text, seconds=4.8):
            shown.append(text)
            return original(state, text, seconds)

        session = self.new_session(has_save=True)
        session.ui.mode = "title"
        with patch.object(State, "toast", record):
            tap(session, "return")  # Continue
            self.assertEqual(session.ui.mode, "play")
            session.ui.mode = "title"
            tap(session, "return")  # and again, in the same session
        self.assertEqual([text for text in shown if text.startswith("Dress your Skipper")], [HINT])

    def test_a_created_skipper_gets_no_hint_on_continue(self):
        self.session.save()  # the save on disk, with created False
        state = State.load(self.path, self.world)
        state.v2["skipper"]["created"] = True
        state.save(self.path)
        session = self.new_session(has_save=True)
        session.ui.mode = "title"
        tap(session, "return")
        self.assertEqual(session.ui.mode, "play")
        self.assertEqual([text for text, _ttl in session.state.toasts if "Skipper" in text], [])

    def test_the_gamepad_hint_names_the_start_button(self):
        self.assertEqual(_toast_for_device(HINT, "gamepad"), "Dress your Skipper: Start, then Your Skipper.")
        self.assertEqual(_toast_for_device(HINT, "keyboard"), HINT)


if __name__ == "__main__":
    unittest.main()
