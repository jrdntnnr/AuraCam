#!/bin/sh
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
TOP_PORT_5V=/sys/class/leds/ext_5v_out/brightness
cd "$PROJECT_DIR"
if [ -w "$TOP_PORT_5V" ]; then
  echo 255 > "$TOP_PORT_5V"
fi
exec "$PROJECT_DIR/cardputer/build/aura-cardputer"
