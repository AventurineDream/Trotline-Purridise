"""Guide layout checks using the native font metrics used by the game."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from . import uiscreens
from .platform import Text, find_font
from .sim import State
from .ui import (
    DIM, SPECIES, UI, UIState, _GAMEPAD_HELP_CONTROLS, _help_title,
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
    return uiscreens.settled_state(world, seed, dyslexia_font)


def _haul_state(world, dyslexia_font, *, fish=False, shiny=False):
    return uiscreens.haul_state(world, dyslexia_font, fish=fish, shiny=shiny)


def _largest_text_screens(ui, world, dyslexia_font):
    """(name, state, UIState) for every screen UI.draw can show, at the largest text."""
    return uiscreens.screens(ui, world, dyslexia_font)


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


class PanelFitChecks(unittest.TestCase):
    """V1-43: text drawn on a panel stays inside it, at every text size and on both input
    devices, and a toast never covers the HUD's top panels."""

    def _records(self, ui):
        panels, texts = [], []
        draw, panel, fill = ui._text, ui._panel, ui._fill

        def text(frame, label, x, y, size, color, shadow=True, family="mono"):
            image = ui._render(label, size, color, family)
            texts.append((label, int(x), int(y), image.shape[1], image.shape[0], len(panels)))
            return draw(frame, label, x, y, size, color, shadow, family)

        def record_panel(frame, x, y, w, h, *args, **kwargs):
            panels.append((int(x), int(y), int(w), int(h)))
            return panel(frame, x, y, w, h, *args, **kwargs)

        def record_fill(frame, x, y, w, h, *args, **kwargs):
            if x <= 0 and y <= 0 and x + w >= frame.shape[1] and y + h >= frame.shape[0]:
                panels.append(None)  # a full-screen dim starts a new layer
            return fill(frame, x, y, w, h, *args, **kwargs)

        ui._text, ui._panel, ui._fill = text, record_panel, record_fill
        return panels, texts

    def _spills(self, panels, texts):
        spills = []
        for label, x, y, w, h, drawn in texts:
            layer = panels[:drawn]
            if None in layer:
                layer = layer[len(layer) - layer[::-1].index(None):]
            inside = [p for p in layer if p[0] - 1 <= x < p[0] + p[2] and p[1] - 1 <= y < p[1] + p[3]]
            if inside:
                px, py, pw, ph = inside[-1]
                if x + w > px + pw + 1 or y + h > py + ph + 1:
                    spills.append((label, x + w - px - pw, y + h - py - ph))
        return spills

    def test_text_stays_inside_its_panel_at_every_size_and_device(self):
        from dataclasses import replace
        world = World()
        text = Text()
        self.addCleanup(text.close)
        for dyslexia_font, sizes in ((False, (0, 1, 2)), (True, (2,))):
            ui = UI(text, world)
            panels, texts = self._records(ui)
            for size in sizes:
                for name, state, screen in uiscreens.screens(ui, world, dyslexia_font, size):
                    if name.startswith("book entry"):
                        continue  # book pages are paper, not panels; the layout test covers them
                    for device in ("keyboard", "gamepad"):
                        with self.subTest(screen=name, size=size, dyslexia=dyslexia_font, device=device):
                            panels.clear()
                            texts.clear()
                            ui.draw(np.zeros((720, 1280, 3), np.uint8), state,
                                    replace(screen, input_device=device))
                            self.assertEqual(self._spills(panels, texts), [])

    def test_a_toast_drops_below_the_hud_panels(self):
        world = World()
        text = Text()
        self.addCleanup(text.close)
        ui = UI(text, world)
        for size in (0, 1, 2):
            state = uiscreens.settled_state(world, 51, False, size)
            state.toasts = [["Dawn on Little Briar. The landing is behind the stern.", 4.8]]
            panels, texts = self._records(ui)
            ui.draw(np.zeros((720, 1280, 3), np.uint8), state, UIState(mode="play"))
            toast = panels[-1]
            with self.subTest(size=size):
                for rx, ry, rw, rh in ui._hud_rects:
                    overlaps = (toast[0] < rx + rw and rx < toast[0] + toast[2]
                                and toast[1] < ry + rh and ry < toast[1] + toast[3])
                    self.assertFalse(overlaps, (toast, (rx, ry, rw, rh)))


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
