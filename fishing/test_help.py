"""In-game help (V1-41) and its Field Guide notebook (#139): every spread fits, the glyph
tables follow the bindings and line up by column, sentences and commands flow whole across
the authored line ends, the notebook shows two pages at a time and says when more follow,
page turns move a spread, and every system and player action has a page."""

import os
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from . import comfort, fieldguide
from .data import SPOIL_HOURS
from .game import Keys, Session
from .gamepad import (
    ACTION_ALIASES, ACTION_SYMBOLS, BUTTON_ACTIONS, BUTTON_Y, normalize_key_bindings,
    set_key_binding,
)
from .platform import FONT_CANDIDATES, Text, find_font
from .sim import State
from .ui import (
    FIELD_GUIDE_TITLE, GAME_TITLE, HELP_N, HELP_SPREADS, TEXT_SIZE_SCALES, UI, UIState,
    _GAMEPAD_HELP_CONTROLS, _HELP, _KEYBOARD_ROWS, _PAD_BUTTON_ROWS, _glyph, help_pages,
    help_topics,
)
from .world import World

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


def _words(topics):
    """Every word of the topics' rows, in reading order: what the pages must show."""
    return [word for _title, lines in topics for cell in _cells(lines) for word in cell.split()]


def _painter(text, scale=1.0, dyslexia=False):
    """A bare UI painter for the help: the game's own text rendering at one text size, in
    the dyslexia-friendly face when `dyslexia` is set."""
    ui = UI.__new__(UI)
    ui.text, ui._cw, ui._ch = text, {}, {}
    ui._text_scale, ui._dyslexia_font = scale, dyslexia
    return ui


def _draw_spread(ui, width, height, spread=0, *, device="keyboard", state=None, paint=False,
                 caption=""):
    """Draw the Field Guide open at `spread` on a fresh `width` x `height` frame.

    With a `caption`, a sound's caption is showing, and the frame is finished as `UI.draw`
    finishes it in help mode, with `UI._caption`. Returns (layout, frame, panel, texts): the
    notebook's layout, the frame, the UIState the guide updated, and each string drawn as
    (label, x, y, w, h, size, color, family), measured by the game's own rendering. Strings
    are painted into the frame only when `paint` is set.
    """
    texts, draw = [], ui._text

    def text(frame, label, x, y, size, color, shadow=True, family="mono"):
        if label:
            image = ui._render(label, size, color, family)
            texts.append((label, x, y, image.shape[1], image.shape[0], size, color, family))
        return draw(frame, label, x, y, size, color, shadow, family) if paint else 0

    ui._text = text
    try:
        frame = np.zeros((height, width, 3), np.uint8)
        panel = UIState(mode="help", input_device=device, help_spread=spread,
                        caption=caption, caption_timer=2.4 if caption else 0.0)
        ui._help(frame, panel, state)
        if caption:
            ui._caption(frame, state, panel)
    finally:
        ui._text = draw
    return next(reversed(ui._guide_layouts.values())), frame, panel, texts


def _read_guide(ui, width, height, *, device="keyboard", state=None):
    """Every spread of the Field Guide in turn, from the opening one.

    Returns (layout, spreads): the notebook's layout and, per spread, (the topics on view,
    the strings drawn as `_draw_spread` records them)."""
    guide, _frame, panel, texts = _draw_spread(ui, width, height, device=device, state=state)
    spreads = [(panel.help_shown, texts)]
    for spread in range(1, panel.help_spreads):
        _guide, _frame, panel, texts = _draw_spread(ui, width, height, spread,
                                                    device=device, state=state)
        spreads.append((panel.help_shown, texts))
    return guide, spreads


def _corner_pixels(frame, guide, side, color):
    """How many pixels of `color` lie in the bottom outer corner of page `side` (0 left)."""
    x, y, w, h = guide.pages[side]
    size = guide.corner
    left = x + w - size if side else x
    box = frame[y + h - size:y + h, left:left + size]
    return int(np.count_nonzero(np.all(box == color, axis=2)))


def _track_pixels(frame, guide, color):
    """How many pixels of `color` the cover's band below the right page holds: the progress
    track's spreads already read, or still ahead."""
    x, _y, w, _h = guide.pages[1]
    bottom = guide.cover[1] + guide.cover[3]
    band = frame[bottom - guide.band:bottom, x:x + w]
    return int(np.count_nonzero(np.all(band == color, axis=2)))


# The topic whose lines are a list of commands, which the guide keeps a line per command.
COMMAND_LIST = "ON THE WATER"
# A run of two or more spaces: an authored gap between the segments (commands) of a line.
GAP = re.compile(r"( {2,})")
# (width, height, text size index): the smallest window at the smallest and the largest
# text, where rows are narrowest, and the largest window at the largest text.
FLOW_LAYOUTS = ((480, 270, 0), (480, 270, len(TEXT_SIZE_SCALES) - 1),
                (1920, 1080, len(TEXT_SIZE_SCALES) - 1))
# (width, height, text size index, dyslexia-friendly face): more layouts whose row widths
# end a row inside one of the ON THE WATER command lines, with the system face and with the
# dyslexia-friendly one, so a command split from its key would show there.
COMMAND_LAYOUTS = ((1280, 720, len(TEXT_SIZE_SCALES) - 1, False), (640, 360, 0, False),
                   (640, 360, 1, False), (480, 270, 0, True), (480, 270, 1, True))


def _drawn_topics(ui, width, height, device):
    """Each topic's ink as the Field Guide draws it, read through every spread.

    Returns (layout, {topic index: [(label, x)]}): each topic's rows in draw order, x in px
    from the start of the text column of the page each is on."""
    guide, spreads = _read_guide(ui, width, height, device=device)
    drawn = {}
    for shown, texts in spreads:
        for label, x, _y, _w, _h, _size, color, _family in texts:
            side = 0 if x < guide.pages[1][0] else 1
            if color == fieldguide.INK and side < len(shown):
                drawn.setdefault(shown[side], []).append(
                    (label, x - guide.pages[side][0] - guide.text_x))
    return guide, drawn


def _drawn_lines(lines, drawn):
    """Pair each of a topic's lines, as the Field Guide joins them up, with its drawn rows.

    `drawn` is the topic's [(label, x)] from `_drawn_topics`. Returns [(line, rows)] for
    every line that is not blank: a paragraph string or a table row tuple, and the
    (label, x) rows that show it. Rows are matched word by word, since every word is drawn
    once, in order."""
    paired, cursor = [], 0
    for line in fieldguide._paragraphs(lines):
        left, rows = sum(len(cell.split()) for cell in _cells([line])), []
        while left > 0:
            label, x = drawn[cursor]
            cursor += 1
            rows.append((label, x))
            left -= len(label.split())
        if left:
            raise AssertionError(f"{rows[-1][0]!r} runs on past {line!r}")
        if rows:
            paired.append((line, rows))
    if cursor != len(drawn):
        raise AssertionError(f"{len(drawn) - cursor} drawn rows belong to no line")
    return paired


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
        lines = [line for title, page in help_pages(bindings)
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
        state = SimpleNamespace(v2={"settings": {
            "key_bindings": set_key_binding(None, "catnap", "x")}})
        index = next(i for i, (title, _lines) in enumerate(help_pages())
                     if title == "KEYBOARD: THE REST")
        _guide, spreads = _read_guide(_painter(text), 960, 540, state=state)
        labels = next([label for label, *_rest in texts]
                      for shown, texts in spreads if index in shown)
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
    """The corrected claims (V1-41 audit, #122, #140, #141) and the topics the help covers."""

    def test_the_original_pages_keep_their_places(self):
        self.assertEqual([title for title, _ in help_pages()[:4]],
                         ["ON THE WATER", "TROT LINES", "THE LANDING", "BOATS AND OTHER WATERS"])

    def test_boats_describe_the_full_shop_unlocks_and_landing_restrictions(self):
        """Both device variants explain all boat tiers without gating the original four."""
        for device in ("keyboard", "gamepad"):
            with self.subTest(device=device):
                page = " ".join(dict(help_topics(None, device))["BOATS AND OTHER WATERS"])
                for claim in (
                    "Boats tab: 24 boats in 8 tiers.",
                    "Jon, rowboat, daysailer and pontoon start unlocked.",
                    "New boats: tiers 1–2 at start, tiers 3–4 after chapter 2, "
                    "tiers 5–6 after chapter 3, tier 7 after chapter 4, "
                    "and tier 8 after chapter 5.",
                    "Tier 8 boats sell only at Cosmic Drift Station in the Nebula.",
                    "Buy and switch only at a landing.",
                    "Owned boats switch freely at any landing.",
                ):
                    self.assertIn(claim, page)
                self.assertNotIn("buy a daysailer or a pontoon", page)

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

    def test_the_offline_soak_names_each_mode_cap_apart_from_the_hook_rule(self):
        # #140: closed-game soaking stops at a cap per mode, in real hours. A hooked fish
        # gets away by the game-hour hook rule, never because the cap ran out.
        page = " ".join(_page_lines("TROT LINES"))
        cozy, old_salt = comfort.OFFLINE_SOAK_HOURS["cozy"], comfort.OFFLINE_SOAK_HOURS["old_salt"]
        self.assertIn("While the game is closed the lines keep soaking, for up to "
                      f"{cozy} real hours in Cozy or {old_salt} in Old Salt.", page)
        self.assertIn(f"Hooked fish still get away after {SPOIL_HOURS:g} game hours.", page)
        self.assertNotIn("six real hours", page)
        self.assertNotIn("then the fish get away", page)


class HelpLayoutChecks(unittest.TestCase):
    """Drawn positions of the glyph tables, read from the game's own text calls, on the
    narrowest window and a mid-sized one, where the tables take different shapes."""

    def setUp(self):
        self.text = Text()
        self.addCleanup(self.text.close)

    def _column_starts(self, lines, drawn):
        """Walk a topic's rows against its drawn text; return each table column's x positions.

        A cell too long for its column wraps beneath itself, so it may take several draws,
        each at the column's x."""
        cursor, starts = 0, {}
        for line in lines:
            cells = enumerate(line) if isinstance(line, tuple) else ((None, line),)
            for index, cell in cells:
                if not cell:
                    continue
                label, x = drawn[cursor]
                cursor += 1
                shown = label
                while shown != cell:
                    self.assertTrue(cell.startswith(shown + " "), (cell, shown))
                    piece, piece_x = drawn[cursor]
                    cursor += 1
                    if index is not None:
                        self.assertEqual(piece_x, x, f"{cell!r} wraps out of its column")
                    shown += " " + piece
                if index is not None:
                    starts.setdefault(index, set()).add(x)
        self.assertEqual(cursor, len(drawn))
        return starts

    def _columns(self, device, prefix):
        """[(title, scale, width, {column: x})] for each table topic whose title starts with
        `prefix`, at every text size on 480x270 and 960x540. Each column starts at one x."""
        found = []
        topics = help_topics(None, device)
        for scale in TEXT_SIZE_SCALES:
            for width, height in ((480, 270), (960, 540)):
                _guide, drawn = _drawn_topics(_painter(self.text, scale), width, height, device)
                for index, (title, lines) in enumerate(topics):
                    if not title.startswith(prefix):
                        continue
                    with self.subTest(page=title, scale=scale, width=width):
                        starts = self._column_starts(lines, drawn[index])
                        for column, xs in starts.items():
                            self.assertEqual(len(xs), 1, f"column {column} starts at {sorted(xs)}")
                        found.append((title, scale, width,
                                      {column: min(xs) for column, xs in starts.items()}))
        return found

    def test_keyboard_columns_line_up_on_every_keyboard_page(self):
        found = self._columns("keyboard", "KEYBOARD")
        self.assertEqual(len(found), 2 * 2 * len(TEXT_SIZE_SCALES))
        for title, scale, width, x in found:
            with self.subTest(page=title, scale=scale, width=width):
                self.assertEqual(sorted(x), [0, 1, 2, 3])
                # Four columns or, on a page too narrow for them, each row's two pairs stacked.
                self.assertTrue(len(set(x.values())) == 4 or (x[0], x[1]) == (x[2], x[3]), x)

    def test_gamepad_columns_line_up_on_both_gamepad_pages(self):
        found = self._columns("gamepad", "GAMEPAD")
        self.assertEqual(len(found), 2 * 2 * len(TEXT_SIZE_SCALES))
        for title, scale, width, x in found:
            with self.subTest(page=title, scale=scale, width=width):
                self.assertEqual(sorted(x), [0, 1])
                self.assertLess(x[0], x[1])


class HelpFlowChecks(unittest.TestCase):
    """How the help's prose flows over the Field Guide's rows, read from the game's own text
    calls on both devices at each of FLOW_LAYOUTS, and its command lines at COMMAND_LAYOUTS
    too."""

    @classmethod
    def setUpClass(cls):
        text = Text()
        cls.addClassCleanup(text.close)
        # (where, painter, layout, topics, drawn ink by topic) per layout and device.
        cls.reads = cls._read(text, ((*layout, False) for layout in FLOW_LAYOUTS))
        cls.command_reads = cls.reads + cls._read(text, COMMAND_LAYOUTS)

    @staticmethod
    def _read(text, layouts):
        """Read the guide at each (width, height, text size index, dyslexia face) layout."""
        reads = []
        for width, height, size, dyslexia in layouts:
            ui = _painter(text, TEXT_SIZE_SCALES[size], dyslexia)
            for device in ("keyboard", "gamepad"):
                guide, drawn = _drawn_topics(ui, width, height, device)
                reads.append(((width, height, size, dyslexia, device), ui, guide,
                              help_topics(None, device), drawn))
        return reads

    def test_sentences_run_on_across_authored_line_ends(self):
        # The help was written in short lines, and the guide joins each sentence's lines up
        # again. Outside the command list every paragraph it rewraps ends a sentence, and
        # only its first row starts at the margin, so no sentence restarts at the margin
        # where an authored line broke it (say "Crater caldera fog and" / "Nebula aurora.").
        for where, ui, guide, topics, drawn in self.reads:
            hang = fieldguide.HANG_EMS * ui.cell(guide.body)[0]
            for index, (title, lines) in enumerate(topics):
                if title == COMMAND_LIST:
                    continue
                for line, rows in _drawn_lines(lines, drawn[index]):
                    if not isinstance(line, str):
                        continue
                    with self.subTest(where=where, topic=title, paragraph=line):
                        self.assertIn(line[-1], ".!?")
                        self.assertEqual([x for _label, x in rows],
                                         [0] + [hang] * (len(rows) - 1))

    def test_command_segments_stay_whole(self):
        # Authored gaps split a command line into its commands ("F sets a trotline     E
        # checks a line or the landing"). A row never ends on a command's key while its
        # action starts the next row.
        for where, ui, guide, topics, drawn in self.command_reads:
            checked = 0
            for index, (title, lines) in enumerate(topics):
                for line, rows in _drawn_lines(lines, drawn[index]):
                    if isinstance(line, str) and GAP.search(line):
                        checked += 1
                        with self.subTest(where=where, topic=title, line=line):
                            self._check_segments(line, rows, ui, guide)
            self.assertGreater(checked, 0, where)

    def _check_segments(self, line, rows, ui, guide):
        """Check that the drawn `rows` of `line` hold whole segments, with the authored gaps
        between them, or part of one segment too wide for a row; and that each segment
        starts a row at the margin unless it shares one, its later rows hung."""
        hang = fieldguide.HANG_EMS * ui.cell(guide.body)[0]
        pieces = GAP.split(line)  # segment, gap, segment, ...
        segments = pieces[0::2]
        owner = [k for k, segment in enumerate(segments) for _word in segment.split()]
        start = 0
        for label, x in rows:
            count = len(label.split())
            first, last = owner[start], owner[start + count - 1]
            opens = start == 0 or owner[start - 1] != first
            closes = start + count == len(owner) or owner[start + count] != last
            self.assertEqual(x, 0 if opens else hang, label)
            if first != last:
                self.assertTrue(opens and closes, f"{label!r} splits a command of {line!r}")
                self.assertEqual(label, "".join(pieces[2 * first:2 * last + 1]))
            elif not (opens and closes):
                segment = segments[first]
                width = ui._render(segment, guide.body, fieldguide.INK,
                                   fieldguide.BODY_FAMILY).shape[1]
                self.assertGreater(width, guide.text_w, f"{segment!r} fits a row but is split")
            start += count
        self.assertEqual(start, len(owner))


class HelpFitChecks(unittest.TestCase):
    """Every spread at every text size and resolution, on both devices, with the default and
    a rebound keyboard: what each page shows and where, measured with the game's own text
    rendering."""

    def setUp(self):
        self.text = Text()
        self.addCleanup(self.text.close)

    def _check(self, state):
        for scale_index, scale in enumerate(TEXT_SIZE_SCALES):
            ui = _painter(self.text, scale)
            for width, height in RESOLUTIONS:
                for device in ("keyboard", "gamepad"):
                    with self.subTest(scale=scale_index, width=width, height=height,
                                      device=device):
                        self._check_guide(ui, width, height, device, state)

    def _check_guide(self, ui, width, height, device, state):
        topics = help_topics(state, device)
        guide, spreads = _read_guide(ui, width, height, device=device, state=state)
        cover_x, cover_y, cover_w, cover_h = guide.cover
        (left_x, page_y, page_w, page_h), (right_x, *right) = guide.pages
        # The notebook sits in the frame: two pages side by side on the cover, which shows
        # above and below them.
        self.assertTrue(0 <= cover_x and 0 <= cover_y and cover_x + cover_w <= width
                        and cover_y + cover_h <= height, guide.cover)
        self.assertEqual(right, [page_y, page_w, page_h])
        self.assertTrue(cover_x < left_x and left_x + page_w <= right_x
                        and right_x + page_w < cover_x + cover_w, guide.pages)
        self.assertTrue(cover_y < page_y and page_y + page_h < cover_y + cover_h, guide.pages)
        on_view, words = [], []
        for spread, (shown, texts) in enumerate(spreads):
            first, more = len(on_view) + 1, spread < len(spreads) - 1
            on_view += shown
            cover, headings, numbers, cues, marks, tops = [], {}, [], [], [], {}
            for index, (label, x, y, w, h, size, color, family) in enumerate(texts):
                self.assertGreaterEqual(size, 12, label)
                for other, ox, oy, ow, oh, *_rest in texts[:index]:
                    overlaps = x < ox + ow and ox < x + w and y < oy + oh and oy < y + h
                    self.assertFalse(overlaps, f"{label!r} overlaps {other!r}")
                if color in (fieldguide.PAPER, fieldguide.EDGE):
                    # The cover's name and page indicator above the pages, its hint below.
                    self.assertTrue(cover_x <= x and x + w <= cover_x + cover_w, label)
                    self.assertTrue(cover_y <= y and y + h <= page_y
                                    or page_y + page_h <= y and y + h <= cover_y + cover_h, label)
                    cover.append(label)
                    continue
                side = 0 if x < right_x else 1
                page_x = guide.pages[side][0]
                # All else is on a page, right of its margin line.
                self.assertTrue(page_x + guide.margin < x and x + w <= page_x + page_w
                                and page_y <= y and y + h <= page_y + page_h, label)
                if color == fieldguide.INK:
                    words += label.split()
                    tops[side] = min(y, tops.get(side, y))
                elif family == fieldguide.TITLE_FAMILY:
                    headings.setdefault(side, []).append(label)
                elif color == fieldguide.OCHRE:
                    cues.append((side, label, x, w))
                elif label == fieldguide.CONTINUED:
                    marks.append((side, y + h))
                elif label.isdigit():
                    numbers.append((side, label, x, w))
            total = guide.page_count
            pages = f"{first}–{first + 1}" if len(shown) == 2 else f"{first}"
            noun = "Pages" if len(shown) == 2 else "Page"
            self.assertEqual(cover[0], FIELD_GUIDE_TITLE)
            self.assertIn(cover[1], (f"{noun} {pages} of {total}", f"{pages} / {total}"))
            self.assertIn("Esc closes" if device == "keyboard" else "B closes", cover[2])
            # Each page heads with its topic's title and has its number at the foot.
            self.assertEqual({side: " ".join(lines) for side, lines in headings.items()},
                             {side: topics[topic][0] for side, topic in enumerate(shown)})
            self.assertEqual([label for _side, label, _x, _w in numbers],
                             [str(first + side) for side in range(len(shown))])
            # The foot of each page says where the notebook goes: back, on, or to page 1.
            self.assertEqual([side for side, *_rest in cues], [0, 1] if spread else [1])
            for side, cue, _x, _w in cues:
                self.assertIn(cue, fieldguide.BACK_CUES if side == 0 else
                              fieldguide.TURN_CUES if more else fieldguide.FIRST_CUES)
            self._check_foot(ui, guide, numbers, cues)
            # Every page that carries its topic over says "continued", once, above the text
            # it carries on with, however little room its title leaves.
            carried = [side for side, page in enumerate(guide.spreads[spread])
                       if page is not None and page.part]
            self.assertEqual([side for side, _bottom in marks], carried)
            for side, bottom in marks:
                self.assertLessEqual(bottom, tops[side])
        # Every topic starts on a page of its own, in order, and every word is on a page.
        self.assertEqual(on_view, sorted(on_view))
        self.assertEqual(sorted(set(on_view)), list(range(HELP_N)))
        self.assertEqual(len(on_view), guide.page_count)
        self.assertEqual(words, _words(topics))

    def _check_foot(self, ui, guide, numbers, cues):
        """Check where each page's number and cue sit at its foot.

        The number keeps to the spine: it ends the left page's text column and starts the
        right page's. The cue sits by the outer corner the page turns at, its chevron at its
        outer end, and at least FOOT_GAP_EMS from the number, so the chevron points at the
        corner and never at the number. `numbers` and `cues` hold (side, label, x, w)."""
        em = ui.cell(guide.body)[0]
        for side, (page_x, _y, page_w, _h) in enumerate(guide.pages):
            start = page_x + guide.text_x
            end = start + guide.text_w
            number = [(x, w) for s, _label, x, w in numbers if s == side]
            for x, w in number:
                self.assertEqual(x + w if side == 0 else x, end if side == 0 else start)
            for s, label, x, w in cues:
                if s != side:
                    continue
                if side == 0:
                    self.assertTrue(label.startswith("‹"), label)
                    self.assertEqual(x, start, label)
                else:
                    self.assertTrue(label.endswith("›"), label)
                    corner = page_x + page_w - guide.corner
                    self.assertTrue(corner - em <= x + w <= corner, (label, x + w, corner))
                for nx, nw in number:
                    gap = nx - (x + w) if side == 0 else x - (nx + nw)
                    self.assertGreaterEqual(gap, fieldguide.FOOT_GAP_EMS * em, label)

    def test_every_spread_fits_with_default_keys(self):
        self._check(None)

    def test_every_spread_fits_with_rebound_keys(self):
        bindings = set_key_binding(None, "catnap", "x")
        self.assertEqual(len(help_pages(bindings)), HELP_N)
        self._check(SimpleNamespace(v2={"settings": {"key_bindings": bindings}}))


class HelpSpreadChecks(unittest.TestCase):
    """What the open notebook shows at 1280x720: two facing pages, where they sit in the
    guide, and whether more pages follow."""

    def setUp(self):
        self.text = Text()
        self.addCleanup(self.text.close)

    def test_the_opening_spread_shows_two_pages_and_that_more_follow(self):
        guide, frame, panel, texts = _draw_spread(_painter(self.text), 1280, 720)
        self.assertEqual(panel.help_spreads, len(guide.spreads))
        self.assertEqual(panel.help_shown, (0, 1))
        labels = [label for label, *_rest in texts]
        self.assertEqual(labels[0], FIELD_GUIDE_TITLE)
        self.assertIn(GAME_TITLE, labels[0])
        self.assertIn(f"Pages 1–2 of {guide.page_count}", labels)
        (left_x, _y, page_w, _h), (right_x, *_rest) = guide.pages
        drawn_at = {label: x for label, x, *_rest in texts}
        # The first topic opens the left page and the second faces it.
        self.assertTrue(left_x < drawn_at[help_pages()[0][0]] < left_x + page_w)
        self.assertTrue(right_x < drawn_at[help_pages()[1][0]] < right_x + page_w)
        self.assertGreater(drawn_at[fieldguide.TURN_CUES[0]], right_x)
        self.assertFalse(set(labels) & {*fieldguide.BACK_CUES, *fieldguide.FIRST_CUES})
        # The right page's corner is turned up and the progress track is all still ahead.
        self.assertGreater(_corner_pixels(frame, guide, 1, fieldguide.FOLD), 0)
        self.assertEqual(_corner_pixels(frame, guide, 0, fieldguide.FOLD), 0)
        self.assertGreater(_track_pixels(frame, guide, fieldguide.TRACK_AHEAD), 0)
        self.assertEqual(_track_pixels(frame, guide, fieldguide.TRACK_READ), 0)

    def test_the_last_spread_turns_back_to_page_one(self):
        guide, frame, panel, texts = _draw_spread(_painter(self.text), 1280, 720, -1)
        self.assertEqual(panel.help_spreads, len(guide.spreads))
        self.assertEqual(panel.help_spread, len(guide.spreads) - 1)
        last_spread = guide.spreads[-1]
        self.assertEqual(panel.help_shown,
                         tuple(page.topic for page in last_spread if page is not None))
        labels = [label for label, *_rest in texts]
        first_page = 2 * (len(guide.spreads) - 1) + 1
        if last_spread[1] is None:
            expected_label = f"Page {first_page} of {guide.page_count}"
        else:
            expected_label = f"Pages {first_page}–{first_page + 1} of {guide.page_count}"
        self.assertIn(expected_label, labels)
        self.assertIn(fieldguide.BACK_CUES[0], labels)
        self.assertIn(fieldguide.FIRST_CUES[0], labels)
        self.assertNotIn(fieldguide.TURN_CUES[0], labels)
        self.assertEqual(_corner_pixels(frame, guide, 1, fieldguide.FOLD), 0)
        self.assertGreater(_corner_pixels(frame, guide, 0, fieldguide.FOLD), 0)
        self.assertGreater(_track_pixels(frame, guide, fieldguide.TRACK_READ), 0)
        self.assertEqual(_track_pixels(frame, guide, fieldguide.TRACK_AHEAD), 0)

    def test_an_odd_last_page_faces_a_blank_page_that_ends_the_guide(self):
        three = help_pages()[:3]
        with patch("fishing.ui.help_pages", lambda saved_bindings=None: three):
            guide, frame, panel, texts = _draw_spread(_painter(self.text), 1280, 720, 1)
        self.assertEqual((panel.help_spread, panel.help_spreads), (1, 2))
        self.assertEqual(panel.help_shown, (2,))
        self.assertIn("Page 3 of 3", [label for label, *_rest in texts])
        x, y, w, h = guide.pages[1]
        right = {label for label, tx, ty, *_rest in texts if x <= tx < x + w and y <= ty < y + h}
        self.assertEqual(right, {fieldguide.END_NOTE, fieldguide.FIRST_CUES[0]})
        # The blank page is ruled like the rest, and no corner turns: the guide ends here.
        column = frame[y:y + h, x + guide.margin - 2]
        ruled = int(np.count_nonzero(np.all(column == fieldguide.RULE_BLUE, axis=1)))
        self.assertEqual(ruled, guide.rows)
        self.assertEqual(_corner_pixels(frame, guide, 1, fieldguide.FOLD), 0)


class HelpCaptionChecks(unittest.TestCase):
    """A sound's caption while the Field Guide is open. The notebook covers the window, so
    the caption takes the controls hint's place on the cover below the pages, where it
    covers no page, cover text or progress track, at every layout resolution."""

    def test_a_caption_takes_the_hints_place_below_the_pages(self):
        text = Text()
        self.addCleanup(text.close)
        short = "A bell rings in the day. It's a Lake Day."
        long = " ".join([short] * 4)  # wider than the spread at every layout: cut with ".."
        shown = SimpleNamespace(v2={"settings": {"captions": True}})
        hidden = SimpleNamespace(v2={"settings": {"captions": False}})
        for scale in (TEXT_SIZE_SCALES[0], TEXT_SIZE_SCALES[-1]):
            ui = _painter(text, scale)
            for width, height in RESOLUTIONS:
                for caption in (short, long):
                    with self.subTest(scale=scale, width=width, height=height, caption=caption):
                        guide, frame, _panel, texts = _draw_spread(
                            ui, width, height, state=shown, caption=caption)
                        self._check_caption(guide, frame, texts, caption, short)
                        # With captions off the hint keeps its place and no caption shows.
                        _guide, _frame, _panel, texts = _draw_spread(
                            ui, width, height, state=hidden, caption=caption)
                        labels = [label for label, *_rest in texts]
                        self.assertFalse([label for label in labels if label.startswith("A bell")])
                        self.assertTrue(any("Esc closes" in label for label in labels), labels)

    def _check_caption(self, guide, frame, texts, caption, short):
        """Check that `caption`, whole when it is `short` and cut with ".." otherwise, is
        drawn once, in place of the hint, on the cover below the pages and across no other
        string or track segment."""
        labels = [label for label, *_rest in texts]
        self.assertFalse([label for label in labels if "Esc closes" in label], labels)
        drawn = [entry for entry in texts if entry[0].startswith("A bell")]
        self.assertEqual(len(drawn), 1, labels)
        label, x, y, w, h, *_rest = drawn[0]
        if caption == short:
            self.assertEqual(label, caption)
        else:
            self.assertTrue(label.endswith("..") and caption.startswith(label[:-2]), label)
        (left_x, page_y, _w, page_h), (right_x, _y, page_w, _h) = guide.pages
        self.assertTrue(left_x <= x and x + w <= right_x + page_w, label)
        self.assertTrue(page_y + page_h <= y and y + h <= guide.cover[1] + guide.cover[3], label)
        for other, ox, oy, ow, oh, *_rest in texts:
            if (other, ox, oy) != (label, x, y):
                overlaps = x < ox + ow and ox < x + w and y < oy + oh and oy < y + h
                self.assertFalse(overlaps, f"{label!r} overlaps {other!r}")
        # Strings are not painted here, so any paper or track colour under it is the track.
        box = frame[y:y + h, x:x + w]
        for color in (fieldguide.PAPER, fieldguide.TRACK_READ, fieldguide.TRACK_AHEAD):
            self.assertEqual(int(np.count_nonzero(np.all(box == color, axis=2))), 0, color)


class HelpNavigationChecks(unittest.TestCase):
    """Page turns in a running session move one spread and wrap around by the spreads the
    guide last drew, which the window and text size decide."""

    def test_page_turns_follow_the_spreads_the_guide_draws(self):
        world = World()
        text = Text()
        self.addCleanup(text.close)
        painter = UI(text, world)
        self.addCleanup(painter.close)
        frame = np.zeros((720, 1280, 3), np.uint8)
        with tempfile.TemporaryDirectory(prefix="trotline-field-guide-") as temp:
            state = State.new(world, seed=139)
            state.v2["settings"]["text_size"] = len(TEXT_SIZE_SCALES) - 1
            session = Session(world, Path(temp) / "save.json", state, False)
            session.ui.mode = "play"
            session.tick(Keys(pressed={"h"}), 0.05)
            self.assertEqual((session.ui.mode, session.ui.help_spread), ("help", 0))
            painter.draw(frame, state, session.ui)
            spreads = session.ui.help_spreads
            # At the largest text long topics run on to further pages, so there are more
            # spreads than the one-page-per-topic count the game starts from.
            self.assertGreater(spreads, HELP_SPREADS)
            self.assertEqual(session.ui.help_shown[0], 0)
            for key, spread in (("right", 1), ("d", 2), ("left", 1), ("w", 0),
                                ("up", spreads - 1), ("down", 0)):
                session.tick(Keys(pressed={key}), 0.05)
                self.assertEqual(session.ui.help_spread, spread, key)
                painter.draw(frame, state, session.ui)
                self.assertEqual(session.ui.help_spreads, spreads)
                if spread == spreads - 1:
                    self.assertEqual(session.ui.help_shown[-1], HELP_N - 1)
            session.tick(Keys(pressed={"h"}), 0.05)
            self.assertEqual(session.ui.mode, "play")
            session.tick(Keys(pressed={"h"}), 0.05)
            self.assertEqual((session.ui.mode, session.ui.help_spread), ("help", 0))
            session.tick(Keys(pressed={"esc"}), 0.05)
            self.assertEqual(session.ui.mode, "play")


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
