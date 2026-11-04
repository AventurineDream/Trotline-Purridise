#!/usr/bin/env python3
"""One-command offline release build.

    python3 scripts/build_package.py [--sdl-dir DIR] [--font-dir DIR]

Writes dist/trotline-purridise/ (run ./trotline-purridise inside it) and
dist/trotline-purridise-<platform>-<arch>.tar.gz (a .zip on Windows).

SDL2 and SDL2_ttf are found with ldconfig on Linux. On Windows and macOS, pass
the folder that holds them with --sdl-dir or TROTLINE_SDL_DIR. On Windows that
folder must hold only the SDL runtime DLLs, since every DLL in it is bundled.
The DejaVu and Liberation fonts are copied from the system, or from --font-dir
or TROTLINE_FONT_DIR, at build time. No font binaries are committed to git.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = "trotline-purridise"
BUILD = ROOT / "build"
STAGE = BUILD / "stage"
DIST = ROOT / "dist"

# Library file names per platform. The Linux names are what the game loads.
SDL_FILES = {
    "linux": ("libSDL2-2.0.so.0", "libSDL2_ttf-2.0.so.0"),
    "windows": ("SDL2.dll", "SDL2_ttf.dll"),
    "macos": ("libSDL2-2.0.0.dylib", "libSDL2_ttf-2.0.0.dylib"),
}
PLATFORM_LABELS = {"linux": "linux", "win32": "windows", "darwin": "macos"}
ARCH_LABELS = {"amd64": "x86_64", "x86_64": "x86_64", "arm64": "arm64", "aarch64": "arm64"}
LINUX_SDL_DIRS = ("/usr/lib/x86_64-linux-gnu", "/usr/lib64", "/usr/lib", "/usr/local/lib")

# Fonts the HUD can use. The DejaVu family is required and the Liberation family is optional.
FONTS = {
    "DejaVu": ("DejaVuSans.ttf", "DejaVuSans-Bold.ttf", "DejaVuSerif.ttf", "DejaVuSansMono.ttf"),
    "Liberation": ("LiberationSans-Regular.ttf", "LiberationSerif-Regular.ttf",
                   "LiberationMono-Regular.ttf"),
}
REQUIRED_FONT_FAMILIES = ("DejaVu",)
FONT_SEARCH = (Path("/usr/share/fonts"), Path("/usr/local/share/fonts"),
               Path("/Library/Fonts"), Path("/System/Library/Fonts"))
# Debian and Ubuntu put each font's license text in /usr/share/doc.
DOC_LICENSES = {
    "DejaVu": ("/usr/share/doc/fonts-dejavu-core/copyright",),
    "Liberation": ("/usr/share/doc/fonts-liberation/copyright",
                   "/usr/share/doc/fonts-liberation2/copyright"),
    "SDL2": ("/usr/share/doc/libsdl2-2.0-0/copyright",),
    "SDL2_ttf": ("/usr/share/doc/libsdl2-ttf-2.0-0/copyright",),
}
LICENSE_NAMES = ("LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING", "COPYING.txt",
                 "copyright", "OFL.txt")

MANIFEST = """Trotline Purridise: offline release package

Third-party software in this folder and where its license text is:

- SDL2 and SDL2_ttf (zlib license): SDL2-LICENSE.txt and SDL2_ttf-LICENSE.txt
  when the build found them, otherwise https://www.libsdl.org/license.php
- DejaVu fonts (Bitstream Vera and public-domain terms): DejaVu-LICENSE.txt
- Liberation fonts: Liberation-LICENSE.txt, when the build included them
- Atkinson Hyperlegible (SIL Open Font License 1.1): assets/fonts/OFL.txt
- NumPy (BSD-3-Clause) and ModernGL (MIT): their metadata, with license files,
  sits in the bundle folder as *.dist-info
- PyInstaller bootloader: PyInstaller's own license (GPL-2.0 with the bootloader
  exception)
"""


def platform_label() -> str:
    try:
        return PLATFORM_LABELS[sys.platform]
    except KeyError:
        raise SystemExit(f"unsupported platform: {sys.platform}") from None


def arch_label() -> str:
    machine = platform.machine().lower()
    return ARCH_LABELS.get(machine, machine)


def _ldconfig_path(soname: str) -> Path | None:
    tool = shutil.which("ldconfig") or "/sbin/ldconfig"
    try:
        listing = subprocess.run([tool, "-p"], capture_output=True, text=True,
                                 check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return None
    for line in listing.splitlines():
        entry, _, target = line.strip().partition(" => ")
        if target and entry.split(" ", 1)[0] == soname:
            return Path(target)
    return None


def _find_in(folder: Path, filename: str) -> Path | None:
    """Find a file by name, ignoring case, so Windows DLL names match either way."""
    if not folder.is_dir():
        return None
    for path in folder.iterdir():
        if path.name.lower() == filename.lower() and path.is_file():
            return path
    return None


def find_sdl(label: str, sdl_dir: Path | None) -> list[tuple[Path, str]]:
    """Return (source, bundled name) for SDL2, SDL2_ttf and any Windows DLL they need."""
    found: list[tuple[Path, str]] = []
    for filename in SDL_FILES[label]:
        if sdl_dir is not None:
            source = _find_in(sdl_dir, filename)
        elif label == "linux":
            source = _ldconfig_path(filename)
            if source is None:
                source = next((p for p in (Path(d) / filename for d in LINUX_SDL_DIRS)
                               if p.exists()), None)
        else:
            source = None
        if source is None:
            if sdl_dir is not None:
                raise SystemExit(f"{filename} not found in {sdl_dir}")
            hint = ("install libsdl2-2.0-0 and libsdl2-ttf-2.0-0 (apt), or pass --sdl-dir"
                    if label == "linux" else "pass --sdl-dir with the SDL runtime DLLs or dylibs")
            raise SystemExit(f"{filename} not found: {hint}")
        found.append((source.resolve(), filename))
    if label == "windows" and sdl_dir is not None:
        named = {name.lower() for _, name in found}
        for dll in sorted(sdl_dir.glob("*.dll")):
            if dll.name.lower() not in named:
                found.append((dll.resolve(), dll.name))
    return found


def find_font_file(name: str, font_dir: Path | None) -> Path | None:
    folders = [font_dir] if font_dir is not None else list(FONT_SEARCH)
    for folder in folders:
        if folder.is_dir():
            for match in sorted(folder.rglob(name)):
                if match.is_file():
                    return match
    return None


def find_font_license(family: str, font_file: Path) -> Path | None:
    # A release zip keeps LICENSE beside the ttf/ folder; a system install uses /usr/share/doc.
    for folder in (font_file.parent, font_file.parent.parent):
        for name in LICENSE_NAMES:
            if (folder / name).is_file():
                return folder / name
    for doc in DOC_LICENSES.get(family, ()):
        if Path(doc).is_file():
            return Path(doc)
    return None


def stage_fonts(font_dir: Path | None) -> list[str]:
    fonts_out = STAGE / "fonts"
    licenses_out = STAGE / "licenses"
    fonts_out.mkdir(parents=True, exist_ok=True)
    licenses_out.mkdir(parents=True, exist_ok=True)
    included: list[str] = []
    for family, names in FONTS.items():
        located = {name: find_font_file(name, font_dir) for name in names}
        located = {name: path for name, path in located.items() if path is not None}
        if not located:
            if family in REQUIRED_FONT_FAMILIES:
                raise SystemExit(f"{family} fonts not found: install fonts-dejavu-core "
                                 "(apt) or pass --font-dir")
            continue
        license_path = None
        for name, path in located.items():
            shutil.copy2(path, fonts_out / name)
            license_path = license_path or find_font_license(family, path)
        if license_path is None:
            raise SystemExit(f"no license text found for the {family} fonts; "
                             "a font is not shipped without its license")
        shutil.copy2(license_path, licenses_out / f"{family}-LICENSE.txt")
        included.extend(sorted(located))
    return included


def _license_in(folder: Path) -> Path | None:
    for name in LICENSE_NAMES:
        if (folder / name).is_file():
            return folder / name
    return None


def stage_sdl_licenses(sdl_dir: Path | None) -> None:
    """Copy SDL's zlib license text when found. Otherwise the manifest points to it."""
    licenses_out = STAGE / "licenses"
    for component in ("SDL2", "SDL2_ttf"):
        source = None
        if sdl_dir is not None:
            source = _license_in(sdl_dir) or _license_in(sdl_dir.parent)
        if source is None:
            source = next((Path(d) for d in DOC_LICENSES[component] if Path(d).is_file()), None)
        if source is not None:
            shutil.copy2(source, licenses_out / f"{component}-LICENSE.txt")


def stage_libraries(label: str, sdl_dir: Path | None) -> list[Path]:
    lib_out = STAGE / "lib"
    lib_out.mkdir(parents=True, exist_ok=True)
    staged = []
    for source, name in find_sdl(label, sdl_dir):
        destination = lib_out / name
        shutil.copy2(source, destination)
        staged.append(destination)
    return staged


def set_linux_runpaths(folder: Path) -> None:
    """Point each bundled library at its own folder, so SDL2 finds the X11 and audio libraries beside it.

    PyInstaller copies those libraries into the bundle, but the dynamic linker only
    searches system folders for the libraries that SDL2 needs, so a clean system
    without them would fail to open SDL.
    """
    patchelf = shutil.which("patchelf") or str(Path(sys.executable).with_name("patchelf"))
    if not Path(patchelf).is_file():
        raise SystemExit("patchelf not found: run python3 -m pip install -r requirements-build.txt")
    for library in sorted(folder.glob("*.so*")):
        if library.is_file() and not library.is_symlink():
            subprocess.run([patchelf, "--set-rpath", "$ORIGIN", str(library)], check=True)


def pyinstaller_command(libraries: list[Path]) -> list[str]:
    sep = os.pathsep
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console",
        "--name", APP,
        "--distpath", str(DIST),
        "--workpath", str(BUILD / "pyinstaller"),
        "--specpath", str(BUILD),
        "--paths", str(ROOT),
        "--collect-submodules", "fishing",
        "--copy-metadata", "numpy",
        "--copy-metadata", "moderngl",
        "--add-data", f"{ROOT / 'fishing' / 'assets'}{sep}fishing/assets",
        "--add-data", f"{ROOT / 'fishing' / 'shaders'}{sep}fishing/shaders",
        "--add-data", f"{STAGE / 'fonts'}{sep}fishing/assets/fonts",
        "--add-data", f"{STAGE / 'licenses'}{sep}licenses",
    ]
    for library in libraries:
        command += ["--add-binary", f"{library}{sep}."]
    command.append(str(ROOT / "scripts" / "package_entry.py"))
    return command


def build_bundle(label: str, sdl_dir: Path | None, font_dir: Path | None) -> Path:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    libraries = stage_libraries(label, sdl_dir)
    fonts = stage_fonts(font_dir)
    stage_sdl_licenses(sdl_dir)
    (STAGE / "licenses" / "README.txt").write_text(MANIFEST, encoding="utf-8")
    print(f"staged SDL: {', '.join(p.name for p in libraries)}")
    print(f"staged fonts: {', '.join(fonts)}")
    subprocess.run(pyinstaller_command(libraries), cwd=ROOT, check=True)
    bundle = DIST / APP
    executable = bundle / (f"{APP}.exe" if label == "windows" else APP)
    if not executable.is_file():
        raise SystemExit(f"PyInstaller did not produce {executable}")
    if label == "linux":
        set_linux_runpaths(bundle / "_internal")
    return bundle


def archive_bundle(bundle: Path, label: str, arch: str) -> Path:
    stem = f"{APP}-{label}-{arch}"
    if label == "windows":
        target = DIST / f"{stem}.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(bundle.rglob("*")):
                archive.write(path, str(Path(APP) / path.relative_to(bundle)))
    else:
        target = DIST / f"{stem}.tar.gz"
        with tarfile.open(target, "w:gz") as archive:
            archive.add(bundle, arcname=APP)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sdl-dir", type=Path,
                        default=os.environ.get("TROTLINE_SDL_DIR") or None,
                        help="folder with SDL2 and SDL2_ttf (Windows and macOS)")
    parser.add_argument("--font-dir", type=Path,
                        default=os.environ.get("TROTLINE_FONT_DIR") or None,
                        help="folder with the DejaVu and Liberation TTF files and license")
    args = parser.parse_args(argv)
    label, arch = platform_label(), arch_label()
    bundle = build_bundle(label, args.sdl_dir, args.font_dir)
    archive = archive_bundle(bundle, label, arch)
    print(f"bundle:  {bundle}")
    print(f"archive: {archive} ({archive.stat().st_size / 1_000_000:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
