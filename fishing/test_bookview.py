"""Book navigation, persistence ceremonies and native-font layout checks."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from .book import BOOK_SPECIES_IDS, LEGENDARY_IDS
from .bookview import (BOOK_TABS, ENTRY_IDS, book_controls, book_layout,
                       collection_rows)
from .game import Keys, Session
from .narrative import QUEST_IDS, RIPPLE_BY_QUEST
from .platform import Input, Text
from .sim import Catch, State
from .ui import UI, UIState
from .world import World


class BookNavigationChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="trotline-book-ui-")
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "save.json"
        self.state = State.new(self.world, seed=812)
        self.session = Session(self.world, self.path, self.state, False)
        self.session.ui.mode = "journal"

    def test_all_tabs_wrap_with_keyboard_and_gamepad(self):
        for source in ("keyboard", "gamepad"):
            self.session.ui.journal_page = 0
            for expected in (*range(1, len(BOOK_TABS)), 0):
                keys = Input()
                setattr(keys, source + "_pressed", {"right"})
                keys.device = source
                before = self.state.game_minutes
                self.session.tick(keys, .1)
                self.assertEqual(self.session.ui.journal_page, expected)
                self.assertEqual(self.state.game_minutes, before)
            self.session.tick(Keys(pressed={"a"}), .1)
            self.assertEqual(self.session.ui.journal_page, len(BOOK_TABS)-1)

    def test_every_species_and_legendary_page_is_reachable(self):
        self.session.tick(Keys(pressed={"up"}), .1)
        self.assertEqual(self.session.ui.journal_i, len(BOOK_SPECIES_IDS) - 1)
        self.session.tick(Keys(pressed={"return"}), .1)
        self.assertEqual(self.session.ui.journal_page, 1)
        self.assertEqual(self.session.ui.book_entry_i, 143)
        visited = set()
        for _ in ENTRY_IDS:
            visited.add(ENTRY_IDS[self.session.ui.book_entry_i])
            self.session.tick(Keys(pressed={"down"}), .01)
        self.assertEqual(visited, set(ENTRY_IDS))

    def test_mouse_survives_action_remapping_and_opens_cards_and_tabs(self):
        """Route remapped pointer clicks only through freshly displayed Book geometry."""
        layout = book_layout(1280, 720)
        text = Text()
        self.addCleanup(text.close)
        renderer = UI(text, self.world)
        self.addCleanup(renderer.close)
        def click(rect):
            renderer.draw(np.zeros((720, 1280, 3), np.uint8),
                          self.state, self.session.ui)
            keys = Input()
            keys.device = "mouse"
            keys.mouse_click = (rect[0] + 4, rect[1] + 4)
            self.session.tick(keys, .1)
        click(layout.cells()[2])
        self.assertEqual((self.session.ui.journal_page, self.session.ui.book_entry_i), (1, 2))
        for index, rect in enumerate(layout.tabs):
            click(rect)
            self.assertEqual(self.session.ui.journal_page, index)
        click(layout.tabs[4])
        click(book_controls(layout)["turn"])
        self.assertEqual(self.session.ui.book_entry_i, len(BOOK_SPECIES_IDS))
        click(book_controls(layout)["close"])
        self.assertEqual(self.session.ui.mode, "play")

    def test_collection_shelves_and_old_quests_remain_reachable(self):
        self.state.narrative.ripples = list(RIPPLE_BY_QUEST.values())
        self.state.v2["keepsakes"] = [{"name": "A knot", "text": "A remembered day."}]
        self.state.well = [Catch("bluegill", .5, 1, 0, "flats", "worm", 8, shiny=True)]
        self.session.ui.journal_page = 2
        for expected in (1, 2, 0):
            self.session.tick(Keys(pressed={"return"}), .1)
            self.assertEqual(self.session.ui.book_shelf, expected)
            self.assertTrue(collection_rows(self.state, self.session._npc_content, expected))
        self.session.ui.journal_page = 3
        for index in range(1, len(QUEST_IDS) + 1):
            self.session.tick(Keys(pressed={"down"}), .1)
            self.assertEqual(self.session.ui.journal_quest_i, index % len(QUEST_IDS))

    def test_stage_prompt_opens_the_exact_page_and_expires_without_replaying(self):
        self.session.ui.mode = "play"
        self.state._note_journal(Catch("carp", 1, 1, 0, "flats", "worm", 8))
        self.session.tick(Keys(pressed={"j"}), .1)
        self.assertEqual(self.session.ui.journal_page, 1)
        self.assertEqual(ENTRY_IDS[self.session.ui.book_entry_i], "carp")
        self.assertFalse(self.state.book_events)
        self.session.ui.mode = "play"
        self.state._note_journal(Catch("bluegill", .5, 1, 0, "flats", "worm", 8))
        self.session.tick(Keys(), .1)
        self.session.tick(Keys(), 3.1)
        self.assertEqual(self.session.ui.book_prompt_species, "")
        self.assertEqual(self.state.journal["bluegill"]["count"], 1)

    def test_title_ceremony_waits_for_the_landing_and_is_once_after_reload(self):
        self.state.set_book_title("book_of_five_waters")
        self.state.x = self.state.z = 0
        self.session.ui.mode = "play"
        self.session.tick(Keys(), .1)
        self.assertEqual(self.session.ui.mode, "play")
        self.state._park(self.world)
        before = self.state.game_minutes
        self.session.tick(Keys(), .1)
        self.assertEqual(self.session.ui.book_ceremony, "book_of_five_waters")
        self.assertEqual(self.state.game_minutes, before)
        self.session.tick(Keys(pressed={"return"}), .1)
        loaded = State.load(self.path, self.world)
        again = Session(self.world, self.path, loaded, True)
        again.ui.mode = "play"
        again.tick(Keys(), .1)
        self.assertEqual(again.ui.book_ceremony, "")


class BookLayoutChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world = World()

    def test_every_tab_fits_all_text_sizes_without_text_overlap(self):
        text = Text()
        self.addCleanup(text.close)
        renderer = UI(text, self.world)
        state = State.new(self.world, seed=813)
        for _ in range(10):
            state._note_journal(Catch("bluegill", .5, 1, 0, "flats", "worm", 8, depth_m=2.5))
        state.narrative.ripples = list(RIPPLE_BY_QUEST.values())
        original = renderer._text
        records = []
        def record(frame, label, x, y, size, color, shadow=True, family="mono"):
            image = renderer._render(label, size, color, family)
            if label:
                records.append((label, int(x), int(y), image.shape[1], image.shape[0]))
            return original(frame, label, x, y, size, color, shadow, family)
        renderer._text = record
        for dyslexia in (False, True):
            state.v2["settings"]["dyslexia_font"] = dyslexia
            for size in (0, 1, 2):
                state.v2["settings"]["text_size"] = size
                for tab in range(len(BOOK_TABS)):
                    records.clear()
                    frame = np.zeros((720, 1280, 3), np.uint8)
                    renderer.draw(frame, state, UIState(mode="journal", journal_page=tab))
                    for i, (label, x, y, w, h) in enumerate(records):
                        with self.subTest(tab=tab, size=size, dyslexia=dyslexia, label=label):
                            self.assertGreaterEqual(x, 0)
                            self.assertGreaterEqual(y, 0)
                            self.assertLessEqual(x + w, 1280)
                            self.assertLessEqual(y + h, 720)
                            for other, ox, oy, ow, oh in records[:i]:
                                overlaps = x < ox + ow and ox < x + w and y < oy + oh and oy < y + h
                                self.assertFalse(overlaps, f"{label!r} overlaps {other!r}")

    def test_unknown_fish_stays_a_silhouette_with_its_folk_name(self):
        text = Text()
        self.addCleanup(text.close)
        state = State.new(self.world, seed=814)
        renderer = UI(text, self.world)
        labels = []
        renderer._text = lambda _f, value, *_a, **_kw: labels.append(value)
        with patch("fishing.fishmesh.fish_thumbnail") as art:
            renderer.draw(np.zeros((720, 1280, 3), np.uint8), state, UIState(mode="journal"))
        self.assertIn("Sunny", labels)
        self.assertNotIn("Bluegill", labels)
        art.assert_not_called()
