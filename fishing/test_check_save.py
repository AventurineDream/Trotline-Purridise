"""--check-save migrates the install-era save with no window; build locations stay out of source runs."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from . import bundle, game, savepaths, saveslots
from . import platform as fishing_platform
from .__main__ import main

FIXTURE = Path(__file__).with_name("fixtures") / "save_v2" / "fresh.json"


class CheckSaveFlagTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="trotline-check-save-")
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        self.install = base / "install"
        self.legacy = self.install / "saves" / "briar.json"
        self.legacy.parent.mkdir(parents=True)
        shutil.copyfile(FIXTURE, self.legacy)
        self.platform_dir = base / "user-data" / "TrotlinePurridise"
        self.save = self.platform_dir / "save.json"
        for patcher in (patch.object(game, "app_root", return_value=self.install),
                        patch.object(savepaths, "sdl_pref_path", return_value=self.platform_dir)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def check(self):
        out, err = StringIO(), StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--check-save"])
        return code, out.getvalue(), err.getvalue()

    def test_first_run_migrates_the_install_save_and_keeps_a_backup(self):
        original = self.legacy.read_bytes()
        code, out, err = self.check()
        self.assertEqual(code, 0, err)
        lines = out.strip().splitlines()
        self.assertEqual(len(lines), 1)
        backups = savepaths.backup_candidates(self.save)
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        self.assertEqual(json.loads(self.save.read_text(encoding="utf-8"))["version"], 2)
        self.assertEqual(self.legacy.read_bytes(), original)
        self.assertEqual(
            lines[0],
            f"save={self.save} version=2 money=$46.00 boats=jon migrated=yes backup={backups[0]}")

    def test_a_second_run_reports_the_existing_save_without_migrating(self):
        self.check()
        code, out, err = self.check()
        self.assertEqual(code, 0, err)
        self.assertIn("migrated=no backup=none", out)
        self.assertEqual(len(savepaths.backup_candidates(self.save)), 1)

    def test_a_newer_save_exits_one_and_leaves_the_files_alone(self):
        self.platform_dir.mkdir(parents=True)
        newer = json.dumps({"version": 99, "lake_id": "briar"}).encode("utf-8")
        self.save.write_bytes(newer)
        code, out, err = self.check()
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertIn("newer than this game supports", err)
        self.assertEqual(self.save.read_bytes(), newer)

    def test_no_save_anywhere_is_a_new_game_not_a_failure(self):
        self.legacy.unlink()
        code, out, err = self.check()
        self.assertEqual(code, 0, err)
        self.assertIn("version=none", out)
        self.assertIn("migrated=no", out)
        self.assertFalse(self.save.exists())

    def test_a_retired_legacy_save_is_not_reimported(self):
        """The legacy-retired marker keeps a renamed-away v1 out of startup."""
        self.platform_dir.mkdir(parents=True)
        (self.platform_dir / saveslots.LEGACY_RETIRED_NAME).touch()
        code, out, err = self.check()
        self.assertEqual(code, 0, err)
        self.assertIn("version=none", out)
        self.assertFalse(self.save.exists())


class LegacySaveRootTests(unittest.TestCase):
    def test_a_source_checkout_looks_in_the_repository_root(self):
        self.assertEqual(game.app_root(), Path(game.__file__).resolve().parents[1])

    def test_a_build_looks_beside_its_executable(self):
        base = Path(tempfile.mkdtemp(prefix="trotline-frozen-root-"))
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        executable = base / "trotline" / "trotline-purridise"
        with patch.object(bundle.sys, "frozen", True, create=True), \
                patch.object(bundle.sys, "executable", str(executable)):
            self.assertEqual(game.app_root(), (base / "trotline").resolve())


class BundleLocationTests(unittest.TestCase):
    def test_a_source_checkout_has_no_packaged_libraries(self):
        self.assertIsNone(bundle.bundle_dir())
        self.assertIsNone(bundle.bundled_library("libSDL2-2.0.so.0"))

    def test_each_platform_names_its_sdl_libraries(self):
        expected = {
            "linux": ("libSDL2-2.0.so.0", "libSDL2_ttf-2.0.so.0"),
            "win32": ("SDL2.dll", "SDL2_ttf.dll"),
            "darwin": ("libSDL2-2.0.0.dylib", "libSDL2_ttf-2.0.0.dylib"),
        }
        for platform_name, (sdl, ttf) in expected.items():
            with self.subTest(platform=platform_name), \
                    patch.object(bundle.sys, "platform", platform_name):
                self.assertEqual(bundle.platform_library_name("libSDL2-2.0.so.0"), sdl)
                self.assertEqual(bundle.platform_library_name("libSDL2_ttf-2.0.so.0"), ttf)

    def test_a_frozen_load_tries_the_packaged_library_before_the_system(self):
        with tempfile.TemporaryDirectory(prefix="trotline-bundle-") as temp:
            folder = Path(temp)
            packaged = folder / "libSDL2-2.0.so.0"
            packaged.write_bytes(b"")
            with patch.object(bundle.sys, "frozen", True, create=True), \
                    patch.object(bundle.sys, "_MEIPASS", str(folder), create=True), \
                    patch.object(bundle.sys, "platform", "linux"), \
                    patch.object(fishing_platform.ctypes, "CDLL", return_value="packaged") as cdll:
                self.assertEqual(fishing_platform._load("libSDL2-2.0.so.0"), "packaged")
            cdll.assert_called_once_with(str(packaged))


if __name__ == "__main__":
    unittest.main()
