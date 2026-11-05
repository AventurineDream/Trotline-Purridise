"""In-game help (V1-41): every page fits, the glyph tables follow the bindings and
line up by column, and every system and player action has a page."""

import os
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from .gamepad import (
    ACTION_ALIASES, ACTION_SYMBOLS, BUTTON_ACTIONS, BUTTON_Y, normalize_key_bindings,
    set_key_binding,
)
from .platform import FONT_CANDIDATES, Text, find_font
from .ui import (
    HELP_N, TEXT_SIZE_SCALES, UI, UIState, _GAMEPAD_HELP_CONTROLS, _HELP,
    _KEYBOARD_ROWS, _PAD_BUTTON_ROWS, _glyph, _help_title, help_pages,
)

RESOLUTIONS = ((480, 270), (640, 360), (960, 540), (1280, 720), (1920, 1080))

# A key named in a line of help text. A single letter counts when it sits in a
# key pattern ("W/S", "press E", "E checks", "A and D steer"), so an article
# such as "A day" is not mistaken for the A key.
KEY_TOKEN = re.compile(
    r"(?:(?<!\w)[WASDEFQRBCGHIJKMNTZ](?=/))"
    r"|(?:(?<=/)[WASDEFQRBCGHIJKMNTZ](?!\w))"
    r"|(?:(?<=[Pp]ress )[A-Z](?!\w))"
    r"|(?:(?<=[Hh]old )[A-Z](?!\w))"
    r"|(?:(?<!\w)[A-Z](?= (?:checks|sets|opens|hails|closes|sends|marks|pauses|picks|"
    r"rebinds|mutes|changes|travels|goes|steer|steers|throttles|chooses|raises|calls|"
    r"help|mute|chart|journal|livewell|pause|speeds|continues|and|or)\b))"
    r"|(?:(?<!\w)(?:Shift|Space|Tab|Esc|Enter|Backspace)(?!\w))"
)
# Gamepad wording names a pad control, or says that the line is keyboard only.
PAD_WORDING = re.compile(
    r"\b(?:A|B|X|Y|LB|RB|LT|RT|Start|Back|D-pad|stick|triggers|pad|tap|hold)\b|\(keyboard\)"
)
# Each system topic, and a word its help page uses (matched without case).
SYSTEM_KEYWORDS = {
    "lakes and travel": "Lakes",
    "the book": "Book",
    "dialogue": "Dialogue",
    "quests and Ripples": "Ripple",
    "calendar": "Lake Days",
    "galley and kitchen": "Galley",
    "comfort modes": "Old Salt",
    "Bot and his tools": "Bot",
    "catnap": "Catnap",
    "legendaries and trophies": "Legendar",
    "settings and captions": "Captions",
    "saves": "save.json",
}


def _cells(lines):
    """The text of every drawn cell, in draw order. A table row is a tuple of cells."""
    return [cell for line in lines
            for cell in (line if isinstance(line, tuple) else (line,)) if cell]


def _all_lines(pages):
    return _cells(line for _title, lines in pages for line in lines)


def _has_cell(lines, glyph, label):
    """Whether a table row holds `glyph` and `label` as one key cell (columns 0-1 or 2-3)."""
    return any(isinstance(line, tuple)
               and any(line[i:i + 2] == (glyph, label) for i in (0, 2))
               for line in lines)


class HelpTextChecks(unittest.TestCase):
    def test_help_count_does_not_depend_on_bindings(self):
        rebound = set_key_binding(None, "catnap", "x")
        self.assertEqual(len(help_pages()), HELP_N)
        self.assertEqual(len(help_pages({"catnap": "x"})), HELP_N)
        self.assertEqual(len(help_pages(rebound)), HELP_N)

    def test_every_player_action_has_a_keyboard_row(self):
        covered = {action for _title, rows in _KEYBOARD_ROWS
                   for left, right in rows
                   for item in (left, right) if item is not None
                   for action in item[1]}
        aliases = {alias for group in ACTION_ALIASES for alias in group[1:]}
        menus = {"menu_up", "menu_down", "menu_left", "menu_right", "select"}
        player = [action for action in ACTION_SYMBOLS
                  if action not in aliases and action not in menus]
        missing = [action for action in player if action not in covered]
        self.assertEqual(missing, [])
        for action in menus - {"select"}:
            self.assertIn(action, covered)

    def test_each_keyboard_row_shows_the_bound_key(self):
        bindings = normalize_key_bindings(set_key_binding(None, "catnap", "x"))
        lines = [line for title, page in help_pages({"catnap": "x"})
                 if title.startswith("KEYBOARD") for line in page]
        for _title, rows in _KEYBOARD_ROWS:
            for left, right in rows:
                for item in (left, right):
                    if item is None:
                        continue
                    label, actions = item
                    glyphs = "/".join(_glyph(bindings[action]) for action in actions)
                    with self.subTest(label=label):
                        self.assertTrue(_has_cell(lines, glyphs, label),
                                        f"({glyphs!r}, {label!r}) is not on a keyboard page")

    def test_rebinding_changes_the_keyboard_page(self):
        default = [line for title, page in help_pages() if title.startswith("KEYBOARD")
                   for line in page]
        rebound = [line for title, page in help_pages({"catnap": "x"})
                   if title.startswith("KEYBOARD") for line in page]
        self.assertNotEqual(default, rebound)
        self.assertTrue(_has_cell(rebound, "X", "Catnap"))
        self.assertFalse(_has_cell(rebound, "Z", "Catnap"))
        self.assertTrue(_has_cell(default, "Z", "Catnap"))

    def test_rebinding_reaches_the_drawn_keyboard_page(self):
        text = Text()
        self.addCleanup(text.close)
        ui = UI.__new__(UI)
        ui.text, ui._cw, ui._ch = text, {}, {}
        ui._text_scale = 1.0
        labels = []
        ui._text = lambda _frame, label, *args, **kwargs: labels.append(label)
        ui._panel = lambda *args, **kwargs: None
        state = SimpleNamespace(v2={"settings": {
            "key_bindings": set_key_binding(None, "catnap", "x")}})
        index = next(i for i, (title, _lines) in enumerate(help_pages())
                     if title == "KEYBOARD: THE REST")
        frame = np.zeros((540, 960, 3), np.uint8)
        ui._help(frame, UIState(mode="help", help_page=index), state)
        pairs = list(zip(labels, labels[1:]))
        self.assertIn(("X", "Catnap"), pairs, labels)
        self.assertNotIn(("Z", "Catnap"), pairs, labels)

    def test_gamepad_page_covers_every_mapped_button(self):
        covered = set()
        for buttons, _name, _what in _PAD_BUTTON_ROWS:
            covered.update(buttons)
        self.assertTrue(set(BUTTON_ACTIONS) <= covered)
        self.assertIn(BUTTON_Y, covered)

    def test_every_help_line_that_names_a_key_has_gamepad_wording(self):
        missing, unclear = [], []
        for title, lines in _HELP:
            for line in lines:
                if not KEY_TOKEN.search(line):
                    continue
                wording = _GAMEPAD_HELP_CONTROLS.get(line)
                if wording is None:
                    missing.append((title, line))
                elif not PAD_WORDING.search(wording):
                    unclear.append((title, line, wording))
        self.assertEqual(missing, [], "lines that name a key need gamepad wording")
        self.assertEqual(unclear, [], "gamepad wording must name a pad control or say (keyboard)")

    def test_every_system_has_a_help_page(self):
        text = "\n".join(_all_lines(help_pages()) + [title for title, _ in help_pages()]).casefold()
        for system, keyword in SYSTEM_KEYWORDS.items():
            with self.subTest(system=system):
                self.assertIn(keyword.casefold(), text)


def _page_lines(title):
    """The authored lines of one help page, table rows flattened to their cells."""
    for page_title, lines in help_pages():
        if page_title == title:
            return _cells(lines)
    raise AssertionError(f"no help page named {title!r}")


class HelpContentChecks(unittest.TestCase):
    """The corrected claims (V1-41 audit, #122) and the topics the help now covers."""

    def test_the_original_pages_keep_their_places(self):
        self.assertEqual([title for title, _ in help_pages()[:4]],
                         ["ON THE WATER", "TROT LINES", "THE LANDING", "BOATS AND OTHER WATERS"])

    def test_no_claim_of_foraging_or_a_pressed_h_anywhere(self):
        text = "\n".join(_all_lines(help_pages()))
        self.assertNotIn("Worms", text)
        self.assertNotIn("any time to come back", text)
        self.assertNotIn("Numbers 1 to 9", text)

    def test_numbers_are_described_as_one_to_five(self):
        self.assertTrue(any(line.startswith("Numbers 1 to 5 pick one too.")
                            for line in _page_lines("CATS AND HAILING")))

    def test_new_morning_is_labelled_as_a_title_key_only(self):
        keyboard = [line for title, page in help_pages() if title.startswith("KEYBOARD")
                    for line in _cells(page)]
        self.assertNotIn("New morning", keyboard)
        self.assertTrue(any(isinstance(line, tuple) and "New (title)" in line
                            for title, page in help_pages() if title.startswith("KEYBOARD")
                            for line in page))

    def test_guardian_and_star_whale_are_split(self):
        lines = _page_lines("LEGENDARIES")
        guardian = next(line for line in lines if "Whiskered Guardian" in line)
        whale = next(line for line in lines if "Star-Whale" in line)
        self.assertIn("no Settle In", guardian)
        self.assertIn("Settle In", whale)
        self.assertIn("Press C", " ".join(lines))
        text = " ".join(lines)
        self.assertIn("Cedar Creek", text)
        self.assertIn("6 to 8 PM", text)
        self.assertIn("8 Ripples", text)

    def test_bait_sections_are_covered(self):
        page = " ".join(_page_lines("BAIT SECTIONS"))
        self.assertIn("one to three bait sections", page)
        self.assertIn("Q or G sets how many sections, 1 to 3.", page)
        self.assertIn("Tab picks which section you edit.", page)
        # The gamepad wording names LB (sections) and Back (section).
        self.assertIn("LB", _GAMEPAD_HELP_CONTROLS["Q or G sets how many sections, 1 to 3."])
        self.assertIn("Back", _GAMEPAD_HELP_CONTROLS["Tab picks which section you edit."])
        self.assertIn("A line can mix up to three.", " ".join(_page_lines("TROT LINES")))

    def test_chart_keys_are_covered(self):
        page = " ".join(_page_lines("THE CHART"))
        for phrase in ("C hails", "Space anchors", "Q sails", "R tows", "B sends Bot",
                       "Tab or Esc closes"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, page)
        self.assertIn("RB", _GAMEPAD_HELP_CONTROLS["On the chart: C hails, Space anchors, Q sails,"])

    def test_mouse_is_covered_on_the_book_page(self):
        page = " ".join(_page_lines("THE BOOK"))
        self.assertIn("Mouse: click tabs, species, controls and week rows.", page)
        self.assertIn("The wheel scrolls the book.", page)

    def test_the_pad_says_it_has_no_look_control(self):
        self.assertIn("no look control",
                      _GAMEPAD_HELP_CONTROLS["A D or arrows steer   arrows look up and down"])

    def test_the_first_hour_describes_h_truthfully(self):
        page = " ".join(_page_lines("FIRST HOUR"))
        self.assertIn("H opens these pages on the water. Pause has Help too.", page)


class HelpLayoutChecks(unittest.TestCase):
    """Drawn positions of the glyph tables, read from the game's own text calls."""

    def setUp(self):
        self.text = Text()
        self.addCleanup(self.text.close)

    def _draw(self, page, *, scale=1.0, width=960, height=540, device="keyboard", state=None):
        """Draw one help page; returns [(label, x)] for its drawn text, in draw order."""
        ui = UI.__new__(UI)
        ui.text, ui._cw, ui._ch = self.text, {}, {}
        ui._text_scale = scale
        ui._dyslexia_font = False
        drawn = []
        ui._text = lambda _frame, label, x, *args, **kwargs: drawn.append((label, x))
        ui._panel = lambda *args, **kwargs: None
        frame = np.zeros((height, width, 3), np.uint8)
        ui._help(frame, UIState(help_page=page, input_device=device), state)
        return drawn

    def _column_starts(self, lines, drawn):
        """Walk the page's rows against the drawn cells; return each column's x positions."""
        cursor = 0
        starts = {}
        for line in lines:
            if not isinstance(line, tuple):
                if line:
                    self.assertEqual(drawn[cursor][0], line)
                    cursor += 1
                continue
            for index, cell in enumerate(line):
                if not cell:
                    continue
                label, x = drawn[cursor]
                self.assertEqual(label, cell)
                starts.setdefault(index, set()).add(x)
                cursor += 1
        self.assertEqual(cursor, len(drawn))
        return starts

    def test_keyboard_columns_line_up_on_every_keyboard_page(self):
        for page, (title, lines) in enumerate(help_pages()):
            if not title.startswith("KEYBOARD"):
                continue
            for scale in TEXT_SIZE_SCALES:
                with self.subTest(page=title, scale=scale):
                    # Title, page number and footer are the first two and last draws.
                    drawn = self._draw(page, scale=scale)[2:-1]
                    starts = self._column_starts(lines, drawn)
                    self.assertEqual(sorted(starts), [0, 1, 2, 3])
                    for index, xs in starts.items():
                        self.assertEqual(len(xs), 1, f"column {index} starts at {sorted(xs)}")

    def test_gamepad_columns_line_up_on_both_gamepad_pages(self):
        for page, (title, lines) in enumerate(help_pages()):
            if not title.startswith("GAMEPAD"):
                continue
            for scale in TEXT_SIZE_SCALES:
                with self.subTest(page=title, scale=scale):
                    drawn = self._draw(page, scale=scale, device="gamepad")[2:-1]
                    starts = self._column_starts(lines, drawn)
                    for index, xs in starts.items():
                        self.assertEqual(len(xs), 1, f"column {index} starts at {sorted(xs)}")


class HelpFitChecks(unittest.TestCase):
    """Every page at every text size and resolution, on both devices, with the
    default and a rebound keyboard. Measured with the game's own text rendering."""

    def setUp(self):
        self.text = Text()
        self.addCleanup(self.text.close)

    def _ui(self, scale):
        ui = UI.__new__(UI)
        ui.text, ui._cw, ui._ch = self.text, {}, {}
        ui._text_scale = scale
        ui._dyslexia_font = False
        return ui

    def _check(self, bindings, state):
        pages = help_pages(bindings)
        self.assertEqual(len(pages), HELP_N)
        for scale_index, scale in enumerate(TEXT_SIZE_SCALES):
            ui = self._ui(scale)
            text_draw, panel_draw = ui._text, ui._panel
            records, panels = [], []

            def text(frame, label, x, y, size, color, shadow=True, family="mono"):
                # The game's own rendering, at this text size (the scale is applied inside).
                image = ui._render(label, size, color, family)
                records.append((label, x, y, image.shape[1], image.shape[0]))
                return text_draw(frame, label, x, y, size, color, shadow, family)

            def panel(frame, x, y, width, height, alpha):
                panels.append((x, y, width, height))
                panel_draw(frame, x, y, width, height, alpha)

            ui._text, ui._panel = text, panel
            for width, height in RESOLUTIONS:
                for device in ("keyboard", "gamepad"):
                    for page, (title, lines) in enumerate(pages):
                        with self.subTest(scale=scale_index, width=width, height=height,
                                          device=device, page=title):
                            records.clear()
                            panels.clear()
                            frame = np.zeros((height, width, 3), np.uint8)
                            ui._help(frame, UIState(help_page=page, input_device=device), state)
                            self.assertEqual(len(panels), 1)
                            px, py, pw, ph = panels[0]
                            self.assertGreaterEqual(px, 0)
                            self.assertGreaterEqual(py, 0)
                            self.assertLessEqual(px + pw, width)
                            self.assertLessEqual(py + ph, height)
                            drawn = [record[0] for record in records[2:-1]]
                            shown = [_GAMEPAD_HELP_CONTROLS.get(line, line)
                                     if device == "gamepad" else line
                                     for line in lines]
                            self.assertEqual(drawn, _cells(shown))
                            self.assertEqual(records[0][0], _help_title(title))
                            for label, x, y, tw, th in records:
                                self.assertGreaterEqual(x, px, label)
                                self.assertGreaterEqual(y, py, label)
                                self.assertLessEqual(x + tw, px + pw, label)
                                self.assertLessEqual(y + th, py + ph, label)

    def test_every_help_page_fits_with_default_keys(self):
        self._check(None, None)

    def test_every_help_page_fits_with_rebound_keys(self):
        bindings = set_key_binding(None, "catnap", "x")
        self._check(bindings, SimpleNamespace(v2={"settings": {"key_bindings": bindings}}))


# DejaVu Sans Mono is what CI gets from fonts-dejavu-core; it has no Liberation copy.
DEJAVU_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
DEJAVU_SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def _installed_mono_fonts():
    return [path for path in FONT_CANDIDATES
            if "Mono" in Path(path).name and os.path.exists(path)]


class MonoFontChecks(unittest.TestCase):
    """The "mono" family must be a monospace face wherever one is installed (#122)."""

    def setUp(self):
        self.text = Text()
        self.addCleanup(self.text.close)

    def _advances(self, text):
        # Thin and wide glyphs in a monospace face draw at one width. SDL_ttf sizes the
        # surface to the ink, which can overhang the advance by a pixel, so allow one.
        thin = text.render("iiiiiiii", 14, (255, 255, 255), "mono").shape[1]
        wide = text.render("WWWWWWWW", 14, (255, 255, 255), "mono").shape[1]
        return thin, wide

    def test_mono_resolves_to_a_monospace_font_when_one_is_installed(self):
        installed = _installed_mono_fonts()
        if not installed:
            self.skipTest("no monospace candidate font is installed here")
        self.assertIn(find_font("mono"), installed)

    def test_mono_text_has_one_advance_for_thin_and_wide_glyphs(self):
        if not _installed_mono_fonts():
            self.skipTest("no monospace candidate font is installed here")
        thin, wide = self._advances(self.text)
        self.assertLessEqual(abs(thin - wide), 1, f"iiiiiiii is {thin}px, WWWWWWWW is {wide}px")

    def test_dejavu_mono_is_chosen_over_dejavu_sans_as_on_ci(self):
        # CI installs only fonts-dejavu-core. Simulate that machine: the Liberation
        # and JetBrains entries are absent, so the proportional DejaVuSans was the
        # match before the mono paths were added.
        if not (os.path.exists(DEJAVU_MONO) and os.path.exists(DEJAVU_SANS)):
            self.skipTest("DejaVu Sans Mono and Sans are not both installed")
        present = {DEJAVU_MONO, DEJAVU_SANS}
        # setUp's Text has drawn nothing yet, so its font opens under the patch.
        with patch("os.path.exists", side_effect=lambda p: p in present):
            self.assertEqual(find_font("mono"), DEJAVU_MONO)
            thin, wide = self._advances(self.text)
        self.assertLessEqual(abs(thin - wide), 1, f"iiiiiiii is {thin}px, WWWWWWWW is {wide}px")


if __name__ == "__main__":
    unittest.main()
