#!/bin/sh
# Set up this clone to play from source: Python 3.10+, a .venv with the game's
# requirements, a check that SDL2, SDL2_ttf and a TTF font load, then the
# self-test. Safe to run again. For the offline package, see docs/RELEASE-CHECKLIST.md.
set -eu
cd "$(dirname "$0")/.."

PY_BOOT=""
for candidate in python3 python; do
  if command -v "$candidate" >/dev/null 2>&1 &&
     "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))' >/dev/null 2>&1; then
    PY_BOOT="$candidate"
    break
  fi
done
if [ -z "$PY_BOOT" ]; then
  echo "Python 3.10 or newer is needed. Install it, then run this script again:" >&2
  echo "  Debian, Ubuntu:  sudo apt install python3 python3-venv" >&2
  echo "  Fedora:          sudo dnf install python3" >&2
  echo "  Arch:            sudo pacman -S python" >&2
  echo "  macOS:           brew install python" >&2
  exit 1
fi

if [ ! -x .venv/bin/python ]; then
  echo "Creating .venv with $("$PY_BOOT" --version 2>&1) ..."
  if ! "$PY_BOOT" -m venv .venv; then
    echo "Could not create .venv. On Debian or Ubuntu, run: sudo apt install python3-venv" >&2
    exit 1
  fi
fi
echo "Installing the game's Python requirements ..."
.venv/bin/python -m pip install --quiet -r requirements.txt

# The same loaders the game uses, so this check matches what the game can open.
SDL_CHECK='
import sys
from fishing.platform import _load, find_font
try:
    _load("libSDL2-2.0.so.0")
    _load("libSDL2_ttf-2.0.so.0")
except OSError as error:
    print(error)
    sys.exit(3)
if sys.platform.startswith("linux"):  # the HUD fonts are system paths on Linux only
    try:
        find_font()
    except FileNotFoundError as error:
        print(error)
        sys.exit(4)
'
status=0
.venv/bin/python -c "$SDL_CHECK" || status=$?
case "$status" in
  0) ;;
  3)
    echo "SDL2 and SDL2_ttf must be installed. Run the command for your system:"
    case "$(uname -s)" in
      Linux)
        distro=$(. /etc/os-release 2>/dev/null; echo "${ID:-} ${ID_LIKE:-}")
        case " $distro " in
          *" debian "*|*" ubuntu "*)
            echo "  sudo apt install libsdl2-2.0-0 libsdl2-ttf-2.0-0 fonts-dejavu-core" ;;
          *" fedora "*|*" rhel "*)
            echo "  sudo dnf install SDL2 SDL2_ttf dejavu-sans-fonts" ;;
          *" arch "*)
            echo "  sudo pacman -S sdl2 sdl2_ttf ttf-dejavu" ;;
          *)
            echo "  Install the SDL2 and SDL2_ttf runtime libraries with your package manager" \
                 "(libSDL2-2.0.so.0 and libSDL2_ttf-2.0.so.0)." ;;
        esac ;;
      Darwin)
        echo "  brew install sdl2 sdl2_ttf"
        echo "  Playing from source is untested on macOS. The packaged build is the supported route" \
             "(docs/RELEASE-CHECKLIST.md)." ;;
      *)
        echo "  On Windows, run scripts\\setup.ps1 in PowerShell instead." ;;
    esac
    exit 1 ;;
  4)
    echo "No TTF font was found for the HUD. Install one, for example:"
    echo "  sudo apt install fonts-dejavu-core"
    exit 1 ;;
  *) exit "$status" ;;
esac

echo "Running the self-test ..."
.venv/bin/python -m fishing --selftest --software
echo "Setup complete. Start the game with ./play.sh"
