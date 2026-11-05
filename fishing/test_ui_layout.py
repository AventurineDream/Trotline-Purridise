"""Guide layout checks using the native font metrics used by the game."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from . import comfort
from .data import BAIT_RECIPES, DISHES, PANTRY
from .platform import Text, find_font
from .sim import Catch, Hook, SetLine, State
from .ui import (
    DIM, HELP_N, SHOP_TABS, SPECIES, UI, UIState, _GAMEPAD_HELP_CONTROLS, _help_title,
    _prompt_for_device, _toast_for_device, help_pages,
)
from .world import World


class DevicePromptChecks(unittest.TestCase):
    def test_tutorial_prompts_follow_the_active_input_device(self):
        keyboard = "W/S row or power    Shift idle    A/D steer"
        self.assertEqual(_prompt_for_device(keyboard, "keyboard"), keyboard)
        self.assertEqual(
            _prompt_for_device(keyboard, "gamepad"),
            "Left stick rows or steers    LT/RT set throttle",
        )
        self.assertEqual(
            _prompt_for_device("Stop, then F to set a trotline", "gamepad"),
            "Stop, then X to set a trotline",
        )
        self.assertEqual(
            _prompt_for_device("T changes time while anchored    E checks a line", "gamepad"),
            "Wait for a bite, then A checks a line",
        )
        self.assertEqual(_prompt_for_device("E  Check the line", "gamepad"),
                         "A  Check the line")

    def test_tutorial_toasts_use_gamepad_actions(self):
        self.assertEqual(
            _toast_for_device("Stop the boat and press F to set a trotline.", "gamepad"),
            "Stop the boat and press X to set a trotline.",
        )
        self.assertEqual(
            _toast_for_device("Anchor and press T to let time run. E checks a line.", "gamepad"),
            "After setting a line, wait for a bite; A checks it.",
        )
        self.assertEqual(
            _toast_for_device("Nose into the landing and press E to sell.", "gamepad"),
            "Nose into the landing and press A to sell.",
        )
        self.assertEqual(
            _toast_for_device("Nose into the landing and press E to sell.", "keyboard"),
            "Nose into the landing and press E to sell.",
        )


def _settled_state(world, seed, dyslexia_font):
    state = State.new(world, seed=seed)
    state.v2["settings"]["text_size"] = 2
    state.v2["settings"]["dyslexia_font"] = dyslexia_font
    return state


def _kitchen_state(world, dyslexia_font):
    """A pantry stocked with every dish and recipe, and fish in the well to cook with."""
    state = _settled_state(world, 43015, dyslexia_font)
    state.money = 600
    state.v2["dishes_known"] = list(DISHES)
    state.v2["recipes"] = list(BAIT_RECIPES)
    state.v2["pantry"] = {item: 4 for item in PANTRY}
    state.bait.update({bait: 1 for recipe in BAIT_RECIPES.values() for bait in recipe.parents})
    state.well = [Catch("bluegill", .9, 1, 0, "flats", "worm", 8),
                  Catch("bluegill", 2, 1, 0, "flats", "worm", 8)]
    comfort.serve_dish(state, DISHES["pecan_chowder"])
    state.toasts.clear()
    state.tutorial = 4
    return state


def _haul_state(world, dyslexia_font, *, fish=False, shiny=False):
    """A line with twelve hooks; the fish and the shiny sit on the hooks the panels show."""
    state = _settled_state(world, 17 + int(fish) + int(shiny), dyslexia_font)
    state.toasts.clear()
    state.tutorial = 4
    hooks = [Hook(True) for _ in range(12)]
    if fish:
        catch = Catch("bluegill", 0.75, 1.0, 0.0, "flats", "worm", 8.0, shiny=shiny)
        hooks[0] = Hook(False, catch)
        state._note_journal(catch)
    if shiny:
        shiny_catch = Catch("channel", 2.4, 1.0, 0.0, "flats", "worm", 8.0, shiny=True)
        hooks[5] = Hook(False, shiny_catch)
        state._note_journal(shiny_catch)
    state.lines = [SetLine("std", "worm", state.x + 6, state.z + 6,
                           state.x + 44, state.z + 10, "flats", hooks)]
    return state


def _largest_text_screens(ui, world, dyslexia_font):
    """(name, state, UIState) for every screen UI.draw can show, each with real content."""
    from . import legendshots
    from .bookview import BOOK_TABS, ENTRY_IDS
    from .kitchen import rows as kitchen_rows
    screens = []

    def add(name, state, panel):
        screens.append((name, state, panel))

    base = _settled_state(world, 51, dyslexia_font)
    add("title", base, UIState(mode="title", has_save=True))
    add("title new game", base, UIState(mode="title", has_save=False))
    add("play", base, UIState(mode="play"))
    add("map", base, UIState(mode="map"))
    add("dialogue", base, UIState(
        mode="dialogue",
        conversation=SimpleNamespace(
            npc_id=next(iter(ui.narrative_content.npcs)),
            node_id=next(iter(ui.narrative_content.dialogue)),
            selected=0,
        ),
        dialogue_content=ui.narrative_content,
    ))
    for tab in range(len(SHOP_TABS)):
        add(f"shop {SHOP_TABS[tab]}", base, UIState(mode="shop", shop_tab=tab, shop_i=0))
    add("setbait", base, UIState(mode="setbait"))

    haul = _haul_state(world, dyslexia_font, fish=True, shiny=True)
    add("haul rise", _haul_state(world, dyslexia_font, fish=True), UIState(
        mode="haul", check_line=0, haul_index=6, haul_timer=0.13,
        haul_counts_before={"bluegill": 0}))
    add("haul surface", _haul_state(world, dyslexia_font, fish=True), UIState(
        mode="haul", check_line=0, haul_index=0, haul_phase="surface",
        haul_counts_before={"bluegill": 0}))
    add("haul card", _haul_state(world, dyslexia_font, fish=True), UIState(
        mode="haul", check_line=0, haul_index=0, haul_phase="card",
        haul_counts_before={"bluegill": 0}))
    add("haul shiny card", _haul_state(world, dyslexia_font, shiny=True), UIState(
        mode="haul", check_line=0, haul_index=5, haul_phase="card",
        haul_counts_before={"channel": 0}))
    add("haul empty hook", base, UIState(mode="haul", check_line=0, haul_index=0))
    add("haul summary", haul, UIState(mode="check", check_line=0, check_i=0))
    add("check", base, UIState(mode="check"))

    # The legendary encounter: its hook, the scene as it holds, and its book page.
    legend_world = World("briar")
    legend_state = legendshots._staged(legend_world, "old_lantern")
    legend_state.v2["settings"]["text_size"] = 2
    legend_state.v2["settings"]["dyslexia_font"] = dyslexia_font
    add("legendary rise", legend_state, legendshots._panel("old_lantern", "rise", 0.0))
    add("legendary encounter", legend_state, legendshots._panel("old_lantern", "encounter", 4.6))
    add("legendary card", legend_state, legendshots._panel("old_lantern", "card", 0.0))

    kitchen = _kitchen_state(world, dyslexia_font)
    dish_row = next(i for i, row in enumerate(kitchen_rows(kitchen, world))
                    if row.arg == "pan_fritters")
    add("kitchen menu", kitchen, UIState(mode="kitchen", shop_i=dish_row))
    add("kitchen landing", kitchen, UIState(mode="shop", shop_tab=SHOP_TABS.index("Kitchen")))
    add("cook dish", kitchen, UIState(
        mode="cook_confirm", cook_kind="dish", cook_arg="pan_fritters",
        cook_label="Sunny Pan Fritters", cook_fish=1))
    add("cook recipe", kitchen, UIState(
        mode="cook_confirm", cook_kind="recipe", cook_arg="lantern_liver",
        cook_label="Lantern Liver"))
    add("cook share", kitchen, UIState(
        mode="cook_confirm", cook_kind="cookout", cook_label="Cookout"))
    add("cooking", kitchen, UIState(
        mode="cooking", cook_label="Sunny Pan Fritters", cook_timer=1,
        cook_text=DISHES["pan_fritters"].blurb))

    add("pick a pace: cozy", base, UIState(mode="new_mode", new_mode_i=0))
    add("pick a pace: old salt", base, UIState(mode="new_mode", new_mode_i=1))
    salty = _settled_state(world, 52, dyslexia_font)
    salty.v2["settings"]["mode"] = "old_salt"
    add("needs energy", salty, UIState(mode="needs", needs_kind="energy", comfort_i=0))
    add("needs hunger", salty, UIState(mode="needs", needs_kind="hunger", comfort_i=1))
    add("catnap", base, UIState(mode="catnap", nap_timer=1.0))
    add("catnap forced", base, UIState(mode="catnap", nap_timer=1.0, nap_forced=True))
    add("credits", base, UIState(mode="credits", credits_s=0.0))

    for shelf in range(3):
        add(f"journal trophy shelf {shelf + 1}", base, UIState(
            mode="journal", journal_page=2, book_shelf=shelf, book_collection_i=0))
    # Every species caught, so each Fish and Book entry (and its next page) has real text.
    caught = _settled_state(world, 74, dyslexia_font)
    for index, species in enumerate(SPECIES):
        caught.journal[species.id] = {
            "count": 3 + index % 4, "best": 2.1, "lake_id": "briar", "zone": "flats",
            "bait": "worm", "band": "trophy",
        }
    for tab in range(len(BOOK_TABS)):
        add(f"journal {BOOK_TABS[tab]}", caught, UIState(
            mode="journal", journal_page=tab, journal_i=0, book_entry_i=0,
            journal_quest_i=0, book_week_i=0, book_watch_i=0))
    for entry in range(len(ENTRY_IDS)):
        add(f"book entry {entry + 1}", caught, UIState(
            mode="journal", journal_page=1, book_entry_i=entry, book_detail_page=0))
    add("species detail next page", caught, UIState(mode="journal", journal_page=1,
                                                    book_entry_i=0, book_detail_page=1))
    add("species detail on the Fish tab", caught, UIState(mode="journal", journal_page=0,
                                                          journal_i=0))
    add("well", base, UIState(mode="well"))
    well = _settled_state(world, 75, dyslexia_font)
    well.well = [Catch("bluegill", 0.75, 1.0, 0.0, "flats", "worm", 8.0)]
    add("well with a fish", well, UIState(mode="well", well_i=0))
    add("pause", base, UIState(mode="pause"))
    add("settings", base, UIState(mode="settings"))
    add("keyboard controls", base, UIState(mode="settings", settings_page="keys", key_binding_i=0))
    add("keyboard controls scrolled", base, UIState(
        mode="settings", settings_page="keys", key_binding_i=29))
    for page in range(HELP_N):
        add(f"help page {page + 1}", base, UIState(mode="help", help_page=page))
    return screens


class GuideLayoutChecks(unittest.TestCase):
    def setUp(self):
        self.text = Text()
        self.addCleanup(self.text.close)

    def test_every_authored_page_fits_without_clipping_or_text_overlap(self):
        self._check_pages()

    def test_layout_with_proportional_fallback_font(self):
        # Linux installs without the preferred monospace font use a sans
        # fallback. Its ascenders/descenders can have different surface heights.
        with patch('fishing.platform.find_font', side_effect=lambda family: find_font('sans')):
            self._check_pages()

    def test_settings_screen_fits_at_1280x720_with_large_dyslexia_font(self):
        ui = UI.__new__(UI)
        ui.text, ui._cw, ui._ch = self.text, {}, {}
        ui._text_scale = 1.0
        ui._dyslexia_font = False
        settings = {
            "mode": "cozy", "text_size": 2, "dyslexia_font": True,
            "reduced_motion": True, "haul_speed": "instant", "captions": True,
            "volumes": {"master": 0.8, "music": 0.7,
                        "ambience": 0.6, "sfx": 0.5},
            "collar_visible": False,
        }
        state = SimpleNamespace(v2={
            "mode": "cozy", "settings": settings,
            "profile": {"collar": {"visible": False}},
        })
        records, panels = [], []
        text_draw, panel_draw = ui._text, ui._panel

        def text(frame, label, x, y, size, color, shadow=True, family="mono"):
            image = ui._render(label, size, color, family)
            records.append((label, x, y, image.shape[1], image.shape[0]))
            return text_draw(frame, label, x, y, size, color, shadow, family)

        def panel(frame, x, y, width, height, alpha):
            panels.append((x, y, width, height))
            panel_draw(frame, x, y, width, height, alpha)

        ui._text, ui._panel = text, panel
        frame = np.zeros((720, 1280, 3), np.uint8)
        ui.draw(frame, state, UIState(mode="settings"))
        self.assertEqual(len(panels), 1)
        px, py, pw, ph = panels[0]
        self.assertGreaterEqual(px, 0)
        self.assertGreaterEqual(py, 0)
        self.assertLessEqual(px + pw, frame.shape[1])
        self.assertLessEqual(py + ph, frame.shape[0])
        for label, x, y, tw, th in records:
            with self.subTest(label=label):
                self.assertGreaterEqual(x, px)
                self.assertGreaterEqual(y, py)
                self.assertLessEqual(x + tw, px + pw)
                self.assertLessEqual(y + th, py + ph)
        self.assertGreaterEqual(len(records), 14)

    def test_every_screen_fits_at_1280x720_with_largest_text(self):
        # Every screen UI.draw can show, at the largest text size, with both the
        # dyslexia-friendly font and the default mono font.
        width, height = 1280, 720
        for dyslexia_font in (True, False):
            font = "dyslexia" if dyslexia_font else "mono"
            world = World()
            ui = UI(self.text, world)
            ui._cw, ui._ch = {}, {}
            records = []
            text_draw = ui._text

            def text(frame, label, x, y, size, color, shadow=True, family="mono"):
                image = ui._render(label, size, color, family)
                records.append((label, int(x), int(y), image.shape[1], image.shape[0]))
                return text_draw(frame, label, x, y, size, color, shadow, family)

            ui._text = text
            for name, state, screen in _largest_text_screens(ui, world, dyslexia_font):
                with self.subTest(screen=name, font=font):
                    records.clear()
                    frame = np.zeros((height, width, 3), np.uint8)
                    ui.draw(frame, state, screen)
                    self.assertTrue(records, f"{name} ({font}) rendered no text")
                    for label, x, y, tw, th in records:
                        with self.subTest(screen=name, font=font, label=label):
                            self.assertGreaterEqual(x, 0)
                            self.assertGreaterEqual(y, 0)
                            self.assertLessEqual(x + tw, width)
                            self.assertLessEqual(y + th, height)
            ui._text = text_draw

    def test_species_journal_details_reflow_inside_the_panel_at_minimum_size(self):
        world = World()
        ui = UI(self.text, world)
        state = State.new(world, seed=73)
        state.journal["bluegill"] = {
            "count": 3, "best": 2.1, "lake_id": "briar", "zone": "flats",
            "bait": "worm", "band": "trophy",
        }
        records, panels = [], []
        text_draw, panel_draw = ui._text, ui._panel

        def text(frame, label, x, y, size, color, shadow=True, family="mono"):
            image = ui._render(label, size, color, family)
            records.append((label, x, y, image.shape[1], image.shape[0]))
            return text_draw(frame, label, x, y, size, color, shadow, family)

        def panel(frame, x, y, width, height, alpha):
            panels.append((x, y, width, height))
            panel_draw(frame, x, y, width, height, alpha)

        ui._text, ui._panel = text, panel
        ui._blit_rgb = lambda frame, image, x, y: None
        frame = np.zeros((270, 480, 3), np.uint8)
        ui.draw(frame, state, UIState(mode="journal", journal_page=1, book_detail_page=1))

        from .bookview import book_layout
        layout = book_layout(480, 270)
        px, py, pw, ph = layout.x, layout.y, layout.w, layout.h
        details = [record for record in records if (
            record[0] == "Bluegill"
            or any(token in record[0].casefold() for token in (
                "caught", "flats", "nightcrawlers", "trophy"))
        )]
        self.assertTrue(any(label == "Bluegill" for label, *_ in details))
        self.assertTrue(any("caught" in label.casefold() for label, *_ in details))
        self.assertTrue(any("flats" in label.casefold() for label, *_ in details), records)
        for label, x, y, width, height in details:
            with self.subTest(label=label):
                self.assertGreaterEqual(x, px)
                self.assertGreaterEqual(y, py)
                self.assertLessEqual(x + width, px + pw)
                self.assertLessEqual(y + height, py + ph)

    def test_book_rumor_and_observations_use_separate_columns_with_large_text(self):
        world = World()
        ui = UI(self.text, world)
        state = State.new(world, seed=74)
        state.v2["settings"]["text_size"] = 2
        state.v2["settings"]["dyslexia_font"] = True
        species = SPECIES[0]
        state.journal[species.id] = {
            "count": 3, "best": 2.1, "lake_id": "briar", "zone": "flats",
            "bait": "worm", "band": "trophy",
        }
        records = []
        text_draw = ui._text

        def text(frame, label, x, y, size, color, shadow=True, family="mono"):
            image = ui._render(label, size, color, family)
            records.append((label, x, y, image.shape[1], image.shape[0], color))
            return text_draw(frame, label, x, y, size, color, shadow, family)

        ui._text = text
        ui._blit_rgb = lambda frame, image, x, y: None
        frame = np.zeros((720, 1280, 3), np.uint8)
        ui.draw(frame, state, UIState(mode="journal", journal_page=1))

        details = [record for record in records if record[5] != DIM and (
            record[0] == species.name
            or any(token in record[0].casefold() for token in (
                "caught", "flats", "nightcrawlers", "trophy"))
        )]
        self.assertTrue(any(label == species.name for label, *_ in details))
        self.assertTrue(any("flats" in label.casefold() for label, *_ in details))
        heard = next(record for record in records if record[0] == "What we heard")
        found = next(record for record in records if record[0] == "What we found")
        observations = [record for record in records if "trophy" in record[0].casefold()]
        self.assertGreater(found[1], heard[1] + heard[3])
        self.assertTrue(observations)
        self.assertTrue(all(record[1] >= found[1] for record in observations))

    def _check_pages(self):
        # The guide needs no world or save. Keep the actual font rasterizer and
        # panel/text draws, while recording their geometry before any clipping.
        ui = UI.__new__(UI)
        ui.text, ui._cw, ui._ch = self.text, {}, {}
        text_draw, panel_draw = ui._text, ui._panel
        records, panels = [], []

        def text(frame, label, x, y, size, color, shadow=True, family='mono'):
            image = self.text.render(label, size, color, family)
            records.append((label, x, y, image.shape[1], image.shape[0], size))
            return text_draw(frame, label, x, y, size, color, shadow, family)

        def panel(frame, x, y, width, height, alpha):
            panels.append((x, y, width, height))
            panel_draw(frame, x, y, width, height, alpha)

        ui._text, ui._panel = text, panel
        for width, height in ((480, 270), (640, 360), (960, 540), (1280, 720), (1920, 1080)):
            for device in ("keyboard", "gamepad"):
                for page, (title, original_lines) in enumerate(help_pages()):
                    lines = original_lines
                    if device == "gamepad":
                        lines = tuple(_GAMEPAD_HELP_CONTROLS.get(line, line)
                                      for line in original_lines)
                    with self.subTest(width=width, height=height, page=page, device=device):
                        records.clear()
                        panels.clear()
                        frame = np.zeros((height, width, 3), np.uint8)
                        ui._help(frame, UIState(help_page=page, input_device=device))
                        self.assertEqual(len(panels), 1)
                        px, py, pw, ph = panels[0]
                        self.assertGreaterEqual(px, 0)
                        self.assertGreaterEqual(py, 0)
                        self.assertLessEqual(px + pw, width)
                        self.assertLessEqual(py + ph, height)
                        # A table row is a tuple of cells; each cell is drawn as its own label.
                        cells = [cell for line in lines
                                 for cell in (line if isinstance(line, tuple) else (line,)) if cell]
                        self.assertEqual([r[0] for r in records[2:-1]], cells)
                        self.assertEqual(records[0][0], _help_title(title))
                        self.assertIn('Esc closes' if device == 'keyboard' else 'B closes', records[-1][0])
                        for label, x, y, tw, th, size in records:
                            self.assertGreaterEqual(size, 12, label)
                            self.assertGreaterEqual(x, px, label)
                            self.assertGreaterEqual(y, py, label)
                            self.assertLessEqual(x + tw, px + pw, label)
                            self.assertLessEqual(y + th, py + ph, label)
                        for i, first in enumerate(records):
                            for second in records[i+1:]:
                                _, x, y, tw, th, _ = first
                                _, xx, yy, ww, hh, _ = second
                                overlap = x < xx + ww and xx < x + tw and y < yy + hh and yy < y + th
                                self.assertFalse(overlap, f'{first[0]!r} overlaps {second[0]!r}')
                        self.assertGreater(np.count_nonzero(frame), 0)


class MinimapControlChecks(unittest.TestCase):
    def test_shortcut_label_matches_the_active_input_device(self):
        ui = UI.__new__(UI)
        ui.world = type("WorldMap", (), {
            "map_small": np.zeros((24, 36, 3), dtype=np.uint8),
        })()
        labels = []
        ui._text = lambda _frame, label, *args, **kwargs: labels.append(label)
        ui._panel = lambda *args, **kwargs: None
        for method in ("_plot_trinidad_cove", "_plot_npcs", "_plot_boat", "_plot_bot"):
            setattr(ui, method, lambda *args, **kwargs: None)
        frame = np.zeros((360, 640, 3), dtype=np.uint8)
        state = type("MapState", (), {"lines": []})()

        for device, expected in (("keyboard", "TAB"), ("gamepad", "BACK")):
            with self.subTest(device=device):
                labels.clear()
                ui._minimap(frame, state, 16, frame.shape[0] - 16, device)
                self.assertIn(expected, labels)


if __name__ == '__main__':
    unittest.main()
