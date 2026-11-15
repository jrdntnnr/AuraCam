# Vendored Melexis MLX90640 library

`functions/MLX90640_API.c` and the headers in `headers/` are copied without
modification from the official
[Melexis mlx90640-library](https://github.com/melexis/mlx90640-library) at
commit `f6be7ca1d4a55146b705f3d347f84b773b29cc86`.

The upstream Apache-2.0 license is in `LICENSE`. AuraCam supplies its own Linux
I²C transport and a small stable C ABI in `auracam/native/`; the calibration,
temperature, image-mode, chess-mode, and bad-pixel calculations remain the
official Melexis implementation.

