#!/bin/sh
set -eu

PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
OUTPUT="$PROJECT_DIR/auracam/native/libmlx90640.so"

cc -shared -fPIC -O3 -std=gnu11 -Wall -Wextra \
  -I"$PROJECT_DIR/vendor/melexis/headers" \
  "$PROJECT_DIR/vendor/melexis/functions/MLX90640_API.c" \
  "$PROJECT_DIR/auracam/native/mlx_linux_i2c.c" \
  "$PROJECT_DIR/auracam/native/mlx_bridge.c" \
  -lm -o "$OUTPUT"

echo "Built $OUTPUT"

