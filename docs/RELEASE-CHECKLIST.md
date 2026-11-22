# Release checklist

This is the checklist for an offline release of Trotline Purridise: a PyInstaller
build that runs without Python, plus the source clone's setup. The design is in
[02 §20](v1/02-GAMEPLAY-SPEC.md) (release and save promise) and
[06 §3](v1/06-IMPLEMENTATION-GUIDE.md) (saves). The packaging notes are at the end
of [06](v1/06-IMPLEMENTATION-GUIDE.md).

## Build the package

The build is one command, `python3 scripts/build_package.py`. It writes
`dist/trotline-purridise/` (run `trotline-purridise` inside it) and an archive:
`dist/trotline-purridise-<platform>-<arch>.tar.gz`, or `.zip` on Windows. `build/`
and `dist/` are git-ignored.

### Linux (x86_64)

1. `sudo apt install libsdl2-2.0-0 libsdl2-ttf-2.0-0 fonts-dejavu-core`
   (optionally `fonts-liberation`).
2. `python3 -m pip install -r requirements.txt -r requirements-build.txt`
3. `python3 scripts/build_package.py`
4. Output: `dist/trotline-purridise-linux-x86_64.tar.gz` (about 43 MB, built here).

The build gives every bundled library an `$ORIGIN` RUNPATH with patchelf, which
`requirements-build.txt` installs. Without it, the bundled SDL2 cannot find the
X11 and audio libraries beside it.

### Windows (build on Windows)

1. Install Python 3.12 from python.org.
2. `py -3.12 -m pip install -r requirements.txt -r requirements-build.txt`
3. Download the x64 runtime zips from the libsdl-org releases,
   `SDL2-<version>-win32-x64.zip` and `SDL2_ttf-<version>-win32-x64.zip`. Extract
   both into one folder, for example `C:\build\sdl`. Every DLL in that folder is
   bundled.
4. Download the DejaVu fonts zip (`dejavu-fonts-ttf-2.37.zip`) and extract it to
   `C:\build\fonts`.
5. `py -3.12 scripts\build_package.py --sdl-dir C:\build\sdl --font-dir C:\build\fonts`
6. Output: `dist\trotline-purridise-windows-x86_64.zip`.

### macOS (build on a Mac)

1. `brew install sdl2 sdl2_ttf`
2. `python3 -m pip install -r requirements.txt -r requirements-build.txt`
3. Extract the DejaVu fonts zip to `~/build/fonts`.
4. `python3 scripts/build_package.py --sdl-dir "$(brew --prefix)/lib" --font-dir ~/build/fonts`
5. Output: `dist/trotline-purridise-macos-arm64.tar.gz`. The build is not code-signed
   or notarized, and the release owner decides whether it will be.

The build fails rather than shipping a font without its license text, or without
SDL2 or SDL2_ttf.

## What CI proves

Workflow: `.github/workflows/package.yml`. It is separate from `validation.yml`, and
the required `gameplay-tests` job is unchanged.

- **package-linux** (every push and pull request): builds the Linux archive on
  ubuntu-24.04 with Python 3.12, and uploads it with the v1 save fixture.
- **package-smoke** (after package-linux): runs in a bare `ubuntu:24.04` container
  with no Python (the job asserts that `python3` is absent). It installs five
  libraries from apt (`libdrm2`, `libxcb1`, `libwayland-client0`,
  `libwayland-cursor0`, `libwayland-egl1`). The bundle carries SDL2, SDL2_ttf and
  their X11 and audio libraries, but PyInstaller leaves those five out, and without
  them SDL does not open. Desktop Linux normally has them. Then it unpacks the
  archive and runs:
  - runs `./trotline-purridise --selftest --software` and requires `selftest ok`;
  - with a fresh `HOME` and `XDG_DATA_HOME`, places a committed v1 save at
    `saves/briar.json` and runs `--check-save`. It requires `migrated=yes`, the
    v2 save in the user-data folder, and a byte-identical backup.
- **package-windows** and **package-macos** run only from `workflow_dispatch`, so
  they cannot turn a pull request red. Neither has run yet. Treat them as
  unverified until someone dispatches them and checks the artifact.

## What CI does not prove

- Windows and macOS builds, which are untested until dispatched and checked by hand.
- A real window, OpenGL, or audio output. The smoke job uses `--software` and the
  dummy SDL drivers.
- Feel, performance, or visuals on a real display.
- Gatekeeper, SmartScreen, or any code signing.
- Linux arm64. The package is built for x86_64 only.
- Upgrades from earlier packages. Only the v1 save migration is checked.
- The action pins in `package.yml`. The `upload-artifact` and `download-artifact`
  SHAs were not verified against GitHub when this was written. Check them before
  the first run.

## Manual checks before a release

Do these on each OS, on a machine without Python or developer tools:

1. Launch the package with a window. Linux: `./trotline-purridise`. Windows:
   `trotline-purridise.exe`. macOS: `./trotline-purridise` from the unpacked folder.
   The windowed build is a console program, so a console window appears on Windows.
2. Play for five minutes: set a line, anchor, check it, and sell at the landing.
3. Save, quit, relaunch, and confirm the money, the lines and the boats are still there.
4. Migrate a v1 save. Copy an old clone's `saves/` folder beside the package, run
   `./trotline-purridise --check-save`, then launch. The line should say
   `migrated=yes`, and the backup should be in the save folder below.
5. Licenses are included. Check `_internal/licenses/README.txt` and the
   `DejaVu-`, `Liberation-`, `SDL2-` and `SDL2_ttf-LICENSE.txt` files. Check that
   the numpy and moderngl `*.dist-info` folders are present. The Atkinson license
   is `_internal/fishing/assets/fonts/OFL.txt`.

Record each pass in a copy of the [QA note template](QA-NOTE-TEMPLATE.md).

## Where saves live

| OS | Save file | Backups |
| --- | --- | --- |
| Linux | `$XDG_DATA_HOME/TrotLineSim/TrotlinePurridise/save.json` (default `~/.local/share/...`) | `.../backup/briar.v1.<time>.json` |
| Windows | `%APPDATA%\TrotLineSim\TrotlinePurridise\save.json` | `...\backup\briar.v1.<time>.json` |
| macOS | `~/Library/Application Support/TrotLineSim/TrotlinePurridise/save.json` | `.../backup/briar.v1.<time>.json` |

Only the Linux paths were checked here. The Windows and macOS paths follow SDL's
pref-path rules. In manual check 3, find the `save.json` file after the first save to
confirm them. The save is never inside the package. The install-era save is `saves/briar.json`,
next to the executable in a package, or in the clone root from source. A
recovered save keeps the rejected bytes as `save.rejected.<time>.json`.

`--save PATH` selects a different save file, for tests and portable runs.

## Setting up a clone

- Linux and macOS: `sh scripts/setup.sh`. It checks for Python 3.10+, creates `.venv`,
  installs `requirements.txt`, checks that SDL2 and SDL2_ttf load, and runs the
  self-test. Then start the game with `./play.sh`.
- Windows: `powershell -ExecutionPolicy Bypass -File scripts\setup.ps1`. It
  does the same, and it also needs the SDL2 and SDL2_ttf DLLs in the clone folder.
  The script prints the download links. Windows was not run while writing this.
- Source play on macOS is untested. Use the packaged build.

## Version bump

1. Set `__version__` in `fishing/__init__.py`.
2. If the save format changes, bump `SAVE_VERSION` in `fishing/sim.py`, add the
   migration and its fixture, and update [06 §3](v1/06-IMPLEMENTATION-GUIDE.md).
3. Update the README status and the release notes.
4. Run `python3 -m unittest discover` and `python3 -m fishing --selftest --software`.
   Both must pass.
5. Build the packages for each OS, then run the manual checks above.
6. Record the archive sizes and SHA-256 sums in the release notes.
7. Tag the commit only after CI is green and the manual checks are done.
