"""PyInstaller entry point for the offline release build.

It runs the same code as `python -m fishing`, with the same exit codes.
"""

import sys

from fishing.__main__ import main

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
