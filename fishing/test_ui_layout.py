"""Guide layout checks using the native font metrics used by the game."""

import unittest

import numpy as np

from .platform import Text
from .ui import UI, UIState, _HELP


class GuideLayoutChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = Text()

    @classmethod
    def tearDownClass(cls):
        cls.text.close()

    def test_every_authored_page_fits_without_clipping_or_text_overlap(self):
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
            for page, (title, lines) in enumerate(_HELP):
                with self.subTest(width=width, height=height, page=page):
                    records.clear()
                    panels.clear()
                    frame = np.zeros((height, width, 3), np.uint8)
                    ui._help(frame, UIState(help_page=page))
                    self.assertEqual(len(panels), 1)
                    px, py, pw, ph = panels[0]
                    self.assertGreaterEqual(px, 0)
                    self.assertGreaterEqual(py, 0)
                    self.assertLessEqual(px + pw, width)
                    self.assertLessEqual(py + ph, height)
                    self.assertEqual([r[0] for r in records[2:-1]], [line for line in lines if line])
                    self.assertEqual(records[0][0], title)
                    self.assertIn('Esc closes', records[-1][0])
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


if __name__ == '__main__':
    unittest.main()
