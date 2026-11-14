"""Tier selection rules for fishing.detail: the 3 GB cap's single decision point."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from . import detail
from .detail import AUTO_HEADROOM, GIB, TIERS


class SelectTests(unittest.TestCase):
    def test_software_rendering_always_gets_the_lightest_tier(self):
        chosen = detail.select(software=True, available_bytes=64 * GIB, override="ultra")
        self.assertEqual(chosen.name, "low")
        self.assertFalse(chosen.hdr)

    def test_auto_requires_headroom_beyond_the_tier_budget(self):
        need = int(TIERS["ultra"].budget_bytes * AUTO_HEADROOM)
        self.assertEqual(detail.select(available_bytes=need).name, "ultra")
        self.assertEqual(detail.select(available_bytes=need - 1).name, "high")

    def test_auto_steps_down_to_low_when_memory_is_scarce(self):
        scarce = int(TIERS["standard"].budget_bytes * AUTO_HEADROOM) - 1
        self.assertEqual(detail.select(available_bytes=scarce).name, "low")

    def test_unknown_memory_picks_the_tier_every_supported_machine_fits(self):
        self.assertEqual(detail.select(available_bytes=None).name, "standard")

    def test_explicit_tier_wins_over_memory_and_bad_names_mean_auto(self):
        self.assertEqual(detail.select(available_bytes=0, override="high").name, "high")
        self.assertEqual(detail.select(available_bytes=0, override="cinematic").name, "low")
        self.assertEqual(detail.select(available_bytes=0, override="auto").name, "low")

    def test_every_tier_stays_under_the_hard_cap(self):
        for tier in TIERS.values():
            self.assertLess(tier.budget_bytes, 3_000_000_000, tier.name)

    def test_tiers_scale_only_the_3d_target_and_keep_software_size_unchanged(self):
        sizes = [detail.render_dimensions(1200, 675, tier=TIERS[name])
                 for name in ("low", "standard", "high", "ultra")]
        self.assertEqual(sizes, [(660, 371), (720, 405), (1080, 607), (1200, 675)])
        self.assertEqual(detail.render_dimensions(1200, 675, software=True, tier=TIERS["low"]),
                         (1200, 675))
        self.assertEqual(detail.render_dimensions(1920, 1080, tier=TIERS["ultra"]),
                         (1440, 810))


class ConfigureTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(setattr, detail, "_current", detail._current)

    def test_environment_pins_the_tier_over_a_saved_setting(self):
        with mock.patch.dict(os.environ, {detail.ENV_OVERRIDE: "standard"}), \
                mock.patch.object(detail, "mem_available_bytes", return_value=64 * GIB):
            self.assertEqual(detail.configure(override="ultra").name, "standard")
            self.assertEqual(detail.current().name, "standard")

    def test_unconfigured_process_ignores_free_memory(self):
        detail._current = None
        with mock.patch.dict(os.environ, {}, clear=False), \
                mock.patch.object(detail, "mem_available_bytes", return_value=64 * GIB):
            os.environ.pop(detail.ENV_OVERRIDE, None)
            self.assertEqual(detail.current().name, detail.DEFAULT)
            os.environ[detail.ENV_OVERRIDE] = "high"
            self.assertEqual(detail.current().name, "high")


if __name__ == "__main__":
    unittest.main()
