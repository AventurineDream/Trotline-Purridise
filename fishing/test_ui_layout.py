"""Guide layout checks using the native font metrics used by the game."""

import unittest
from unittest.mock import patch

import numpy as np

from .platform import Text, find_font
from .ui import UI, UIState, _GAMEPAD_HELP_CONTROLS, _HELP, _help_title


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
                for page, (title, original_lines) in enumerate(_HELP):
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
                        self.assertEqual([r[0] for r in records[2:-1]], [line for line in lines if line])
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
