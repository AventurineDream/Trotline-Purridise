"""V1-43 accessibility checks.

Contrast: every UI string reads at WCAG AA contrast against what is drawn behind it. Each screen UI.draw can show is drawn at 1280x720 with the largest text, over two backdrops
that stand in for the 3D lake: black (night) and a bright overcast sky. The backdrop behind
each string is the median colour of its box just before the string is drawn, so a panel,
scrim or backing counts and the string's own drop shadow does not.
AA asks for 4.5:1, or 3:1 for text 24 px and larger.

Captions: toasts and sound captions stay up long enough to read (fishing/reading.py).

Gamepad: everything a keyboard player can reach, a pad player can too, through the pause
menu where a pad button would run out.

Markers: every chart marker differs from the others in shape, not only colour, so the chart
reads with any colour vision.
"""

from __future__ import annotations

import unittest

import numpy as np

from .platform import Text
from .reading import READ_CHARS_PER_SECOND, READ_MAX_SECONDS, READ_NOTICE_SECONDS, reading_seconds
from .uiscreens import screens as _largest_text_screens
from .sim import State
from .ui import UI
from .world import World

BACKDROPS = {"night": (0, 0, 0), "bright sky": (196, 214, 219)}
LARGE_TEXT_PX = 24


def _luminance(color) -> float:
    c = np.asarray(color, np.float64) / 255.0
    c = np.where(c <= 0.03928, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)
    return float(0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2])


def contrast(a, b) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class ContrastChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = Text()

    def test_contrast_formula(self):
        self.assertAlmostEqual(contrast((0, 0, 0), (255, 255, 255)), 21.0, places=3)
        self.assertAlmostEqual(contrast((118, 118, 118), (255, 255, 255)), 4.54, places=2)

    def test_every_screen_meets_wcag_aa_over_night_and_bright_sky(self):
        for dyslexia_font in (False, True):
            font = "dyslexia" if dyslexia_font else "mono"
            world = World()
            ui = UI(self.text, world)
            ui._cw, ui._ch = {}, {}
            draw = ui._text
            failures = []

            def text(frame, label, x, y, size, color, shadow=True, family="mono"):
                image = ui._render(label, size, color, family)
                th, tw = image.shape[:2]
                x0, y0 = int(max(0, x)), int(max(0, y))
                region = frame[y0:y0 + th, x0:x0 + tw].reshape(-1, 3)
                if region.size and label.strip():
                    backdrop = np.median(region, axis=0)
                    ratio = contrast(color, backdrop)
                    need = 3.0 if size >= LARGE_TEXT_PX else 4.5
                    if ratio < need:
                        failures.append((label[:48], tuple(int(v) for v in color),
                                         tuple(int(v) for v in backdrop), round(ratio, 2)))
                return draw(frame, label, x, y, size, color, shadow, family)

            ui._text = text
            try:
                for name, state, panel in _largest_text_screens(ui, world, dyslexia_font):
                    for backdrop, fill in BACKDROPS.items():
                        with self.subTest(screen=name, font=font, backdrop=backdrop):
                            failures.clear()
                            frame = np.empty((720, 1280, 3), np.uint8)
                            frame[:] = fill
                            ui.draw(frame, state, panel)
                            self.assertEqual(failures, [])
            finally:
                ui._text = draw


class CaptionTiming(unittest.TestCase):
    def test_reading_time_grows_with_the_text_between_floor_and_cap(self):
        self.assertEqual(reading_seconds("Plop.", 2.4), 2.4)
        short, long = reading_seconds("x" * 40), reading_seconds("x" * 100)
        self.assertGreater(long, short)
        self.assertAlmostEqual(long, READ_NOTICE_SECONDS + 100 / READ_CHARS_PER_SECOND)
        self.assertEqual(reading_seconds("x" * 1000), READ_MAX_SECONDS)
        self.assertEqual(reading_seconds("x" * 1000, 12.0), 12.0)

    def test_a_long_toast_outlasts_the_old_fixed_hold(self):
        state = State.new(World(), seed=3)
        line = ("Maeve says the channel cats sulk in the deep bend until the light goes, "
                "then come up the drop like they own it.")
        state.toast(line)
        self.assertGreaterEqual(state.toasts[-1][1], len(line) / READ_CHARS_PER_SECOND)
        self.assertGreater(state.toasts[-1][1], 4.8)
        state.toast("Saved.")
        self.assertEqual(state.toasts[-1][1], 4.8)

    def test_every_cookout_toast_holds_long_enough_to_read(self):
        from .calendar import CALENDAR_DATA
        state = State.new(World(), seed=3)
        for npc_id, line in CALENDAR_DATA["cookout_lines"].items():
            with self.subTest(npc=npc_id):
                state.toast("Someone: " + line, 8)
                self.assertGreaterEqual(state.toasts[-1][1], min(READ_MAX_SECONDS, len(line) / READ_CHARS_PER_SECOND))

    def test_every_sound_caption_holds_long_enough_to_read(self):
        from types import SimpleNamespace
        from .game import CAPTION_SECONDS, Session
        from .soundscape import CAPTIONS
        from .ui import UIState
        for kind in CAPTIONS:
            with self.subTest(sound=kind):
                session = Session.__new__(Session)
                session.state = SimpleNamespace(v2={"settings": {"captions": True}})
                session.ui = UIState()
                session.sound = kind
                session._tick_caption(0.0)
                self.assertTrue(session.ui.caption)
                self.assertGreaterEqual(session.ui.caption_timer, CAPTION_SECONDS)
                self.assertGreaterEqual(session.ui.caption_timer,
                                        len(session.ui.caption) / READ_CHARS_PER_SECOND)


class GamepadFlow(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from .game import Session
        folder = tempfile.TemporaryDirectory(prefix="trotline-pad-")
        self.addCleanup(folder.cleanup)
        self.world = World("briar")
        self.session = Session(self.world, Path(folder.name) / "save.json",
                               State.new(self.world, seed=41), False)
        self.session.ui.mode = "play"

    def press(self, *buttons):
        from .gamepad import BUTTON_ACTIONS
        from .platform import Input
        keys = Input()
        keys.device = "gamepad"
        keys.gamepad_pressed = {key for button in buttons for key in BUTTON_ACTIONS[button]}
        self.session.tick(keys, 0.05)

    def choose(self, label):
        """Start, D-pad down to the label, A."""
        from .gamepad import BUTTON_A, BUTTON_DPAD_DOWN, BUTTON_START
        from .ui import pause_options
        self.press(BUTTON_START)
        self.assertEqual(self.session.ui.mode, "pause")
        options = pause_options(self.session.state)
        self.assertIn(label, options)
        for _ in range(options.index(label)):
            self.press(BUTTON_DPAD_DOWN)
        self.press(BUTTON_A)

    def test_pause_opens_the_book_and_b_closes_it(self):
        from .gamepad import BUTTON_B
        self.choose("Book")
        self.assertEqual(self.session.ui.mode, "journal")
        self.press(BUTTON_B)
        self.assertEqual(self.session.ui.mode, "play")

    def test_pause_opens_the_livewell(self):
        self.choose("Livewell")
        self.assertEqual(self.session.ui.mode, "well")

    def test_pause_changes_time_speed_and_stays_open(self):
        self.choose("Time 1x")
        self.assertEqual(self.session.state.time_scale, 3)
        self.assertEqual(self.session.ui.mode, "pause")
        from .ui import pause_options
        self.assertIn("Time 3x", pause_options(self.session.state))

    def test_pause_raises_the_sail_on_a_sailing_boat_only(self):
        from .ui import pause_options
        self.assertNotIn("Raise the sail", pause_options(self.session.state))
        self.session.state.boat_id = "small_sloop"
        self.session.state.anchored = False
        self.choose("Raise the sail")
        self.assertTrue(self.session.state.sail_raised)
        self.assertEqual(self.session.ui.mode, "play")
        self.assertIn("Lower the sail", pause_options(self.session.state))

    def test_a_refused_tow_says_why_in_the_pause_menu(self):
        self.session.state.boat_id = "small_sloop"
        self.session.state.sail_raised = True
        self.choose("Call a tow")
        self.assertEqual(self.session.ui.mode, "pause")
        self.assertIn("idle", self.session.ui.note)

    def test_a_tow_from_pause_runs_and_returns_to_play(self):
        before = self.session.state.game_minutes
        self.choose("Call a tow")
        self.assertEqual(self.session.ui.mode, "play")
        self.assertGreater(self.session.state.game_minutes, before)

    def test_the_pad_help_page_no_longer_lists_missing_buttons(self):
        from .ui import help_pages
        text = " ".join(str(line) for page in help_pages() for line in page[1])
        self.assertNotIn("no pad button", text)
        self.assertIn("Book, livewell, sail, tow and time.", text)


class FocusStates(unittest.TestCase):
    def test_the_livewell_marks_its_chosen_row_with_a_band_not_only_colour(self):
        from .sim import Catch
        from .ui import UIState
        text = Text()
        self.addCleanup(text.close)
        world = World()
        ui = UI(text, world)
        state = State.new(world, seed=5)
        state.well = [Catch("bluegill", 0.75, 1.0, 0.0, "flats", "worm", 8.0),
                      Catch("bluegill", 0.5, 1.0, 0.0, "flats", "worm", 8.0)]
        frames = []
        for chosen in (0, 1):
            frame = np.zeros((720, 1280, 3), np.uint8)
            ui.draw(frame, state, UIState(mode="well", well_i=chosen))
            frames.append(frame)
        # The strip between the panel edge and the text holds no glyphs: only a band shows there.
        pw = int(1280 * 0.56)
        x = (1280 - pw) // 2
        rows = np.nonzero((frames[0] != frames[1]).any(axis=2))[0]
        self.assertTrue(rows.size)
        gutter_0 = frames[0][rows.min():rows.max() + 1, x + 9:x + 15]
        gutter_1 = frames[1][rows.min():rows.max() + 1, x + 9:x + 15]
        self.assertFalse(np.array_equal(gutter_0, gutter_1))


class MarkerShapes(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = Text()
        cls.world = World()
        cls.ui = UI(cls.text, cls.world)
        cls.state = State.new(cls.world, seed=7)

    def _mask(self, kind, legend):
        frame = np.zeros((32, 32, 3), np.uint8)
        self.ui._marker(frame, kind, 16, 16, legend=legend)
        return frame.any(axis=2)

    def _assert_distinct(self, kinds, legend):
        masks = {kind: self._mask(kind, legend) for kind in kinds}
        for kind, mask in masks.items():
            self.assertTrue(mask.any(), kind)
        for i, a in enumerate(kinds):
            for b in kinds[i + 1:]:
                with self.subTest(a=a, b=b, legend=legend):
                    overlap = (masks[a] & masks[b]).sum() / (masks[a] | masks[b]).sum()
                    self.assertLess(overlap, 0.75)

    def test_chart_markers_differ_in_shape(self):
        self._assert_distinct(["fish", "tired", "bait", "cat", "bot"], legend=False)

    def test_every_legend_entry_has_its_own_shape(self):
        kinds = [kind for kind, _words in self.ui.legend_items(self.state, sonar_bands=True)]
        self.assertEqual(len(kinds), len(set(kinds)))
        self._assert_distinct(kinds, legend=True)

    def test_the_legend_names_shapes_without_naming_colours(self):
        words = {w for _kind, item in self.ui.legend_items(self.state, sonar_bands=True)
                 for w in item.lower().split()}
        self.assertFalse(words & {"gold", "green", "red", "blue", "orange", "yellow"}, words)


if __name__ == "__main__":
    unittest.main()
