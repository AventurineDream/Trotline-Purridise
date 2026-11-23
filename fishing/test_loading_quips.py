"""Loading-card quips (issue #138): authored pools, their validation, varied picks, the card.

Aven's QA (2026-11-22, items 1 and 13) asks for at least 24 shared quips and 12 unique
ones per lake, a different line on startup and on every trip, and copy that stays
readable at the smallest window. Picks use a seeded generator here, so every check is
deterministic.
"""

from copy import deepcopy
import random
import unittest
from unittest.mock import patch

import numpy as np

from . import lakes as lakes_module
from .content import ContentError, validate_content_v2
from .data import CONTENT_V2_RAW, LAKE_LOADING_QUIPS, LOADING_QUIPS
from .game import _loading_quip, _travel_card_text
from .lakes import LAKES, LoadingQuips, loading_quips
from .platform import Text
from .ui import TEXT_SIZE_SCALES

# The smallest window game._window_size opens, and the quip size the card uses there.
SMALLEST_WINDOW = (480, 270)
SMALLEST_QUIP_SIZE = 14


class LoadingQuipPools(unittest.TestCase):
    def test_shared_and_per_lake_pools_are_large_and_distinct(self):
        self.assertGreaterEqual(len(LOADING_QUIPS), 24)
        self.assertEqual(len(set(LOADING_QUIPS)), len(LOADING_QUIPS))
        self.assertEqual(set(LAKE_LOADING_QUIPS), set(LAKES))
        seen = set(LOADING_QUIPS)
        for lake_id, pool in LAKE_LOADING_QUIPS.items():
            with self.subTest(lake=lake_id):
                self.assertGreaterEqual(len(pool), 12)
                self.assertEqual(len(set(pool)), len(pool))
                # Unique to the lake: never shared, never another lake's line.
                self.assertFalse(seen & set(pool))
                seen |= set(pool)
                self.assertEqual(loading_quips(lake_id), LOADING_QUIPS + pool)
                self.assertTrue(all(quip.strip() == quip and quip for quip in pool))
        self.assertEqual(loading_quips("uncharted"), LOADING_QUIPS)

    def test_every_quip_fits_the_smallest_window_at_the_largest_text(self):
        width = int(SMALLEST_WINDOW[0] * 0.92)  # the card's trim width
        size = max(8, round(SMALLEST_QUIP_SIZE * max(TEXT_SIZE_SCALES)))
        text = Text()
        self.addCleanup(text.close)
        for family in ("sans", "dyslexia"):
            for quip in LOADING_QUIPS + tuple(q for pool in LAKE_LOADING_QUIPS.values() for q in pool):
                with self.subTest(family=family, quip=quip):
                    self.assertLessEqual(text.render(quip, size, (255, 255, 255), family).shape[1], width)


class LoadingQuipValidation(unittest.TestCase):
    def _errors(self, broken):
        with self.assertRaises(ContentError) as caught:
            validate_content_v2(broken)
        return str(caught.exception)

    def test_validator_requires_enough_unique_quips_in_every_pool(self):
        broken = deepcopy(CONTENT_V2_RAW)
        lakes = broken["lakes.json"]
        lakes["loading_quips"] = lakes["loading_quips"][:23]
        briar, cedar, flathead, crater, nebula = lakes["lakes"]
        briar["loading_quips"][1] = briar["loading_quips"][0]
        cedar["loading_quips"][0] = lakes["loading_quips"][0]
        flathead["loading_quips"][0] = crater["loading_quips"][0]
        crater["loading_quips"][1] = " "
        del nebula["loading_quips"]
        message = self._errors(broken)
        for expected in (
            "lakes.json:loading_quips: expected at least 24 distinct loading quips, got 23",
            "lakes.json:lakes[0](briar).loading_quips[1]: duplicate loading quip",
            "lakes.json:lakes[1](cedar).loading_quips[0]: duplicate loading quip",
            "already in loading_quips",
            "lakes.json:lakes[3](crater).loading_quips[0]: duplicate loading quip",
            "already in lakes[2](flathead).loading_quips",
            "lakes.json:lakes[3](crater).loading_quips[1]: expected non-empty text",
            "lakes.json:lakes[4](nebula): missing required field 'loading_quips'",
        ):
            with self.subTest(expected=expected):
                self.assertIn(expected, message)

    def test_authored_pools_pass_validation(self):
        validate_content_v2(deepcopy(CONTENT_V2_RAW))


class LoadingQuipPicks(unittest.TestCase):
    def test_a_seeded_picker_repeats_its_sequence(self):
        route = ["briar", "cedar", "nebula", "crater", "nebula", "flathead", "briar"] * 4
        first, second = LoadingQuips(random.Random(138)), LoadingQuips(random.Random(138))
        self.assertEqual([first.pick(lake) for lake in route], [second.pick(lake) for lake in route])

    def test_picks_come_from_the_lake_pool_and_never_repeat_back_to_back(self):
        picker = LoadingQuips(random.Random(13))
        route = list(LAKES) * 60 + ["nebula"] * 200
        previous = None
        for lake_id in route:
            quip = picker.pick(lake_id)
            self.assertIn(quip, loading_quips(lake_id))
            self.assertNotEqual(quip, previous)
            self.assertEqual(picker.last, quip)
            previous = quip

    def test_every_quip_in_a_lake_pool_gets_its_turn(self):
        picker = LoadingQuips(random.Random(1))
        for lake_id in LAKES:
            with self.subTest(lake=lake_id):
                shown = {picker.pick(lake_id) for _ in range(1500)}
                self.assertEqual(shown, set(loading_quips(lake_id)))

    def test_a_single_quip_pool_may_repeat(self):
        with patch.object(lakes_module, "LOADING_QUIPS", ("Only one line...",)), \
                patch.dict(lakes_module.LAKE_LOADING_QUIPS, {}, clear=True):
            picker = LoadingQuips(random.Random(2))
            self.assertEqual([picker.pick("briar") for _ in range(3)], ["Only one line..."] * 3)


class LoadingCardText(unittest.TestCase):
    class _RecordingUI:
        """Records the card's draws in place of a real UI and font."""

        def __init__(self):
            self.drawn = []
            self.trims = []

        def _trim(self, s, size, width, family="mono"):
            self.trims.append((s, size, width, family))
            return s

        def _center(self, frame, s, x, y, size, color, family="sans"):
            self.drawn.append((s, x, y, size, family))
            return 0

    def test_travel_card_names_the_lake_above_the_quip(self):
        ui = self._RecordingUI()
        frame = np.zeros((270, 480, 3), np.uint8)
        _travel_card_text(ui, frame, "Starlight Nebula Lagoon", "Riding the astral current...")
        (heading, hx, hy, hsize, hfamily), (quip, qx, qy, qsize, qfamily) = ui.drawn
        self.assertEqual(heading, "Opening Starlight Nebula Lagoon...")
        self.assertEqual(hfamily, "serif")
        self.assertEqual(quip, "Riding the astral current...")
        self.assertEqual((hx, qx), (240, 240))
        self.assertGreaterEqual(qy, hy + hsize)
        self.assertEqual(qsize, SMALLEST_QUIP_SIZE)
        self.assertEqual(ui.trims, [(quip, SMALLEST_QUIP_SIZE, int(480 * 0.92), "sans")])

    def test_startup_quip_scales_with_the_window(self):
        ui = self._RecordingUI()
        _loading_quip(ui, np.zeros((720, 1280, 3), np.uint8), "Untangling the trotline...", 417)
        self.assertEqual(ui.drawn, [("Untangling the trotline...", 640, 417, 18, "sans")])


if __name__ == "__main__":
    unittest.main()
