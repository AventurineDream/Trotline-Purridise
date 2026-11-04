"""Where a PyInstaller build keeps its libraries. A source checkout never sees these paths."""

from __future__ import annotations

import sys
from pathlib import Path

# The game asks for SDL by its Linux name. These are the same libraries on each platform.
SDL_LIBRARIES = {
    "libSDL2-2.0.so.0": {"linux": "libSDL2-2.0.so.0", "win32": "SDL2.dll",
                         "darwin": "libSDL2-2.0.0.dylib"},
    "libSDL2_ttf-2.0.so.0": {"linux": "libSDL2_ttf-2.0.so.0", "win32": "SDL2_ttf.dll",
                             "darwin": "libSDL2_ttf-2.0.0.dylib"},
}


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path | None:
    """The folder PyInstaller unpacked the build into, or None outside a build."""
    if not is_frozen():
        return None
    return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))


def platform_library_name(name: str) -> str:
    """The file name of an SDL library on this platform (Linux names are unchanged)."""
    return SDL_LIBRARIES.get(name, {}).get(sys.platform, name)


def bundled_library(name: str) -> Path | None:
    """The packaged copy of an SDL library, when running from a build and it is there."""
    folder = bundle_dir()
    if folder is None:
        return None
    path = folder / platform_library_name(name)
    return path if path.is_file() else None
