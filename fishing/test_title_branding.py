"""Guard the player-facing game name while preserving lake identity."""

import ast
from pathlib import Path
import unittest

from .savepaths import SDL_APPLICATION, SDL_ORGANIZATION
from .ui import FIELD_GUIDE_TITLE, GAME_TITLE


ROOT = Path(__file__).resolve().parents[1]


class TitleBrandingChecks(unittest.TestCase):
    def test_branding_surfaces_use_the_canonical_title(self):
        self.assertEqual(GAME_TITLE, "Trotline Purridise")
        self.assertEqual((ROOT / "README.md").read_text(encoding="utf-8").splitlines()[0],
                         f"# {GAME_TITLE}")
        ui_source = (ROOT / "fishing" / "ui.py").read_text(encoding="utf-8")
        game_source = (ROOT / "fishing" / "game.py").read_text(encoding="utf-8")
        self.assertIn("self._text(frame,GAME_TITLE", ui_source)
        self.assertIn("Platform(width, height, GAME_TITLE", game_source)
        self.assertIn("ui._center(loading,GAME_TITLE", game_source)
        # Beneath the title, startup shows a varied quip for the opening lake (issue #138).
        self.assertIn("_loading_quip(ui, loading, quips.pick(world.id)", game_source)
        self.assertNotIn("Opening the lake...", game_source)
        # The Field Guide's cover carries the name above its pages (#139).
        self.assertIn(GAME_TITLE, FIELD_GUIDE_TITLE)

    def test_ui_strings_only_use_little_briar_as_a_lake_name(self):
        ui_paths = (
            ROOT / "fishing" / "ui.py",
            ROOT / "fishing" / "bookview.py",
            ROOT / "fishing" / "game.py",
            ROOT / "fishing" / "verify.py",
        )
        little_briar_strings = set()
        for path in ui_paths:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            little_briar_strings.update(
                node.value for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and "Little Briar" in node.value
            )
        self.assertEqual(little_briar_strings, {
            "Little Briar Lake",
        })
        verify_source = (ROOT / "fishing" / "verify.py").read_text(encoding="utf-8")
        self.assertIn('Platform(1280,720,f"{GAME_TITLE} — visual check"',
                      verify_source)

    def test_platform_save_namespace_remains_stable(self):
        self.assertEqual(SDL_ORGANIZATION, "TrotLineSim")
        self.assertEqual(SDL_APPLICATION, "TrotlinePurridise")


if __name__ == "__main__":
    unittest.main()
