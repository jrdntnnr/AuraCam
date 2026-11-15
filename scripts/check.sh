#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

supports_project() {
  "$1" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' \
    >/dev/null 2>&1 &&
    "$1" -c 'import cv2, numpy, PIL, usb' >/dev/null 2>&1
}

run_checks() {
  "$1" -m unittest discover -v
  "$1" -m compileall -q auracam supercamera protocol_camera.py
}

cd "$PROJECT_DIR"

if [ -n "${AURACAM_PYTHON:-}" ]; then
  if ! supports_project "$AURACAM_PYTHON"; then
    echo "AURACAM_PYTHON must be Python 3.10+ with project dependencies" >&2
    exit 1
  fi
  run_checks "$AURACAM_PYTHON"
  exit 0
fi

if [ -x "$PROJECT_DIR/.venv/bin/python" ] && \
   supports_project "$PROJECT_DIR/.venv/bin/python"; then
  run_checks "$PROJECT_DIR/.venv/bin/python"
  exit 0
fi

if command -v uv >/dev/null 2>&1; then
  uv run --isolated --python 3.13 --project "$PROJECT_DIR" \
    python -m unittest discover -v
  uv run --isolated --python 3.13 --project "$PROJECT_DIR" \
    python -m compileall -q auracam supercamera protocol_camera.py
  exit 0
fi

echo "Install a supported project environment or uv" >&2
exit 1
