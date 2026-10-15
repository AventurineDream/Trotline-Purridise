#!/bin/sh
cd "$(dirname "$0")"
PY=".venv/bin/python"
if [ ! -x "$PY" ]; then
  python3 -m venv .venv
fi
if ! "$PY" -c "import numpy, moderngl" >/dev/null 2>&1; then
  "$PY" -m pip install -r requirements.txt
fi
exec "$PY" -m fishing "$@"
