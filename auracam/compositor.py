from __future__ import annotations

import math
import threading
import time
from functools import lru_cache

import cv2
import numpy as np

from .config import AuraConfig
from .frames import HudTelemetry, OverlayGeometry, ThermalFrame
from .hud import HudRenderer

_CV_PALETTES = {
    "inferno": cv2.COLORMAP_INFERNO,
    "turbo": cv2.COLORMAP_TURBO,
    "ocean": cv2.COLORMAP_OCEAN,
    "magma": cv2.COLORMAP_MAGMA,
}
_PREVIEW_SIZE = (640, 480)


def _palette_lut(stops: np.ndarray) -> np.ndarray:
    position = np.linspace(0.0, len(stops) - 1, 256, dtype=np.float32)
    low = np.floor(position).astype(np.int16)
    high = np.minimum(low + 1, len(stops) - 1)
    weight = (position - low)[:, None]
    return (
        stops[low] * (1.0 - weight) + stops[high] * weight
    ).astype(np.uint8).reshape(256, 1, 3)


_AURA_LUT = _palette_lut(
    np.array(
        [
            [42, 0, 70],
            [255, 20, 100],
            [190, 35, 255],
            [15, 165, 255],
            [210, 250, 255],
        ],
        dtype=np.float32,
    )
)


def _aura_palette(norm: np.ndarray) -> np.ndarray:
    gray = np.clip(norm * 255.0, 0, 255).astype(np.uint8)
    return cv2.applyColorMap(gray, _AURA_LUT)


class AuraCompositor:
    def __init__(self):
        self._lock = threading.Lock()
        self._smoothed: np.ndarray | None = None
        self._trail: np.ndarray | None = None
        self._last_sequence = -1
        self._temporal_signature: tuple[str, int] | None = None
        self._previous_base: np.ndarray | None = None
        self._overlay_cache_key: tuple | None = None
        self._overlay_cache: tuple[np.ndarray, np.ndarray] | None = None
        self._hud = HudRenderer()

    def reset_temporal(self) -> None:
        with self._lock:
            self._smoothed = None
            self._trail = None
            self._last_sequence = -1
            self._temporal_signature = None
            self._previous_base = None
            self._overlay_cache_key = None
            self._overlay_cache = None

    def compose(
        self,
        base_bgr: np.ndarray,
        thermal: ThermalFrame | None,
        config: AuraConfig,
        telemetry: HudTelemetry | None = None,
    ) -> np.ndarray:
        base = self._process_base(base_bgr, config)
        geometry = self._geometry(base.shape, config, time.monotonic())
        if thermal is None:
            if telemetry is None:
                return base
            return self._hud.render(base.copy(), None, config, telemetry, geometry)

        raw = (
            thermal.temperatures
            if config.representation == "temperature"
            else thermal.image
        )
        raw = np.nan_to_num(raw.astype(np.float32), nan=0.0, posinf=0.0, neginf=0.0)
        raw = self._orient_source(raw, config)
        with self._lock:
            signature = (config.representation, config.thermal_rotation, config.thermal_mirror_h)
            if signature != self._temporal_signature:
                self._smoothed = None
                self._trail = None
                self._last_sequence = -1
                self._temporal_signature = signature
            if thermal.sequence != self._last_sequence:
                if self._smoothed is None:
                    self._smoothed = raw.copy()
                else:
                    keep = config.smoothing
                    self._smoothed = self._smoothed * keep + raw * (1.0 - keep)
                normalized = self._normalize(self._smoothed, config)
                if self._trail is None:
                    self._trail = normalized.copy()
                else:
                    self._trail = np.maximum(
                        normalized, self._trail * config.trail_decay
                    )
                self._last_sequence = thermal.sequence
            field = self._smoothed.copy() if self._smoothed is not None else raw
            trail = self._trail.copy() if self._trail is not None else None

        norm = self._normalize(field, config)
        if config.mode == "trail" and trail is not None:
            norm = trail
        cache_key = (thermal.timestamp_ns, thermal.sequence, config, base.shape[:2])
        result = self._overlay(base, norm, config, geometry, cache_key)
        if telemetry is None:
            return result
        return self._hud.render(result, thermal, config, telemetry, geometry)

    def render_thermal(
        self,
        thermal: ThermalFrame,
        config: AuraConfig,
        size: tuple[int, int] = _PREVIEW_SIZE,
    ) -> np.ndarray:
        raw = (
            thermal.temperatures
            if config.representation == "temperature"
            else thermal.image
        )
        raw = self._orient_source(raw, config)
        norm = self._normalize(raw, config)
        rows, columns = norm.shape
        norm = cv2.resize(norm, size, interpolation=self._interpolation(config))
        if config.blur > 0 and config.mode != "pixel":
            norm = self._blur_field(norm, config.blur)
        color = self._colorize(norm, config.palette)
        if config.grid:
            self._draw_grid(color, rows, columns)
        return color

    @staticmethod
    def _orient_source(source: np.ndarray, config: AuraConfig) -> np.ndarray:
        rotated = AuraCompositor._rotate_source(source, config.thermal_rotation)
        if config.thermal_mirror_h:
            return cv2.flip(rotated, 1)
        return rotated

    @staticmethod
    def _rotate_source(source: np.ndarray, rotation: int) -> np.ndarray:
        if rotation == 90:
            return cv2.rotate(source, cv2.ROTATE_90_CLOCKWISE)
        if rotation == 180:
            return cv2.rotate(source, cv2.ROTATE_180)
        if rotation == 270:
            return cv2.rotate(source, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return source

    @staticmethod
    def _process_base(base: np.ndarray, config: AuraConfig) -> np.ndarray:
        output = base
        if config.camera_rotation == 90:
            output = cv2.rotate(output, cv2.ROTATE_90_CLOCKWISE)
        elif config.camera_rotation == 180:
            output = cv2.rotate(output, cv2.ROTATE_180)
        elif config.camera_rotation == 270:
            output = cv2.rotate(output, cv2.ROTATE_90_COUNTERCLOCKWISE)
        if config.mirror_h:
            output = cv2.flip(output, 1)
        if config.mirror_v:
            output = cv2.flip(output, 0)

        if (
            config.gamma == 1.0
            and config.contrast == 1.0
            and config.brightness == 1.0
            and config.saturation == 1.0
            and config.sharpness == 1.0
        ):
            return output

        work = output.astype(np.float32) / 255.0
        if config.gamma != 1.0:
            work = np.power(np.clip(work, 0, 1), 1.0 / config.gamma)
        work = (work - 0.5) * config.contrast + 0.5
        work *= config.brightness
        if config.saturation != 1.0:
            gray = cv2.cvtColor(
                np.clip(work * 255, 0, 255).astype(np.uint8), cv2.COLOR_BGR2GRAY
            )
            gray = gray.astype(np.float32)[..., None] / 255.0
            work = gray + (work - gray) * config.saturation
        output = np.clip(work * 255, 0, 255).astype(np.uint8)
        if config.sharpness != 1.0:
            blur = cv2.GaussianBlur(output, (0, 0), 1.2)
            output = cv2.addWeighted(
                output, config.sharpness, blur, 1.0 - config.sharpness, 0
            )
        return output

    @staticmethod
    def _normalize(field: np.ndarray, config: AuraConfig) -> np.ndarray:
        if config.representation == "image":
            finite = field[np.isfinite(field)]
            if finite.size:
                low, high = np.percentile(finite, (5, 98))
            else:
                low, high = 0.0, 1.0
            span = max(1e-6, float(high - low))
            return np.clip((field - low) / span * config.gain, 0.0, 1.0)
        span = max(0.1, config.thermal_max - config.thermal_min)
        return np.clip((field - config.thermal_min) / span * config.gain, 0.0, 1.0)

    def _alpha(self, norm: np.ndarray, config: AuraConfig) -> np.ndarray:
        if config.representation == "image":
            threshold = config.image_threshold * config.gain
        else:
            span = max(0.1, config.thermal_max - config.thermal_min)
            threshold = (config.threshold - config.thermal_min) / span * config.gain
        alpha = (norm - threshold) * config.alpha_gain
        return np.clip(alpha, 0.0, config.max_alpha)

    @staticmethod
    def _colorize(norm: np.ndarray, palette: str) -> np.ndarray:
        if palette == "aura":
            return _aura_palette(norm)
        gray = np.clip(norm * 255, 0, 255).astype(np.uint8)
        return cv2.applyColorMap(gray, _CV_PALETTES.get(palette, cv2.COLORMAP_INFERNO))

    @staticmethod
    def _interpolation(config: AuraConfig) -> int:
        if config.mode == "pixel" or config.interpolation == "nearest":
            return cv2.INTER_NEAREST
        if config.interpolation == "cubic":
            return cv2.INTER_CUBIC
        return cv2.INTER_LINEAR

    @staticmethod
    def _blur_field(field: np.ndarray, sigma: float) -> np.ndarray:
        if sigma <= 0:
            return field
        padding = max(1, math.ceil(sigma * 3.0))
        padded = cv2.copyMakeBorder(
            field,
            padding,
            padding,
            padding,
            padding,
            cv2.BORDER_CONSTANT,
            value=0,
        )
        blurred = cv2.GaussianBlur(padded, (0, 0), max(0.1, sigma))
        return blurred[padding:-padding, padding:-padding]

    @staticmethod
    @lru_cache(maxsize=32)
    def _edge_fade(width: int, height: int, cells_x: int, cells_y: int) -> np.ndarray:
        feather_x = max(1, round(width / max(1, cells_x)))
        feather_y = max(1, round(height / max(1, cells_y)))
        x_distance = np.minimum(np.arange(width), np.arange(width)[::-1])
        y_distance = np.minimum(np.arange(height), np.arange(height)[::-1])
        x_fade = np.clip(x_distance / feather_x, 0.0, 1.0)
        y_fade = np.clip(y_distance / feather_y, 0.0, 1.0)
        return np.minimum(y_fade[:, None], x_fade[None, :]).astype(np.float32)

    @classmethod
    def _registered_field(
        cls,
        norm: np.ndarray,
        width: int,
        height: int,
        interpolation: int,
        blur: float,
    ) -> np.ndarray:
        if blur <= 0:
            return cv2.resize(norm, (width, height), interpolation=interpolation)

        rows, columns = norm.shape
        scale = min(1.0, (columns * 5) / width, (rows * 5) / height)
        work_width = max(columns, round(width * scale))
        work_height = max(rows, round(height * scale))
        work = cv2.resize(
            norm, (work_width, work_height), interpolation=interpolation
        )
        work = cls._blur_field(work, max(0.1, blur * scale))
        if (work_width, work_height) == (width, height):
            return work
        return cv2.resize(work, (width, height), interpolation=cv2.INTER_LINEAR)

    @staticmethod
    def _draw_grid(color: np.ndarray, rows: int, columns: int) -> None:
        height, width = color.shape[:2]
        for column in range(columns + 1):
            x = min(width - 1, round(column * width / columns))
            cv2.line(color, (x, 0), (x, height - 1), (255, 255, 255), 1)
        for row in range(rows + 1):
            y = min(height - 1, round(row * height / rows))
            cv2.line(color, (0, y), (width - 1, y), (255, 255, 255), 1)
        cv2.drawMarker(
            color,
            (width // 2, height // 2),
            (0, 255, 255),
            cv2.MARKER_CROSS,
            max(12, min(width, height) // 5),
            2,
        )

    def _prepare_overlay(
        self, norm: np.ndarray, config: AuraConfig, width: int, height: int
    ) -> tuple[np.ndarray, np.ndarray]:
        source_rows, source_columns = norm.shape
        interpolation = self._interpolation(config)
        overlay_w = max(1, round(width * config.scale_x))
        overlay_h = max(1, round(height * config.scale_y))
        blur = config.blur if config.mode != "pixel" else 0.0
        resized = self._registered_field(
            norm, overlay_w, overlay_h, interpolation, blur
        )
        alpha = self._alpha(resized, config)
        color = self._colorize(resized, config.palette)

        if config.grid:
            self._draw_grid(color, source_rows, source_columns)
            alpha = np.maximum(alpha, config.max_alpha * 0.32)
        else:
            alpha *= self._edge_fade(overlay_w, overlay_h, source_columns, source_rows)

        if config.rotation:
            matrix = cv2.getRotationMatrix2D(
                (overlay_w / 2, overlay_h / 2), config.rotation, 1.0
            )
            color = cv2.warpAffine(
                color,
                matrix,
                (overlay_w, overlay_h),
                flags=interpolation,
                borderMode=cv2.BORDER_CONSTANT,
            )
            alpha = cv2.warpAffine(
                alpha,
                matrix,
                (overlay_w, overlay_h),
                flags=interpolation,
                borderMode=cv2.BORDER_CONSTANT,
            )
        return color, alpha.astype(np.float32, copy=False)

    def _overlay(
        self,
        base: np.ndarray,
        norm: np.ndarray,
        config: AuraConfig,
        geometry: OverlayGeometry,
        cache_key: tuple | None = None,
    ) -> np.ndarray:
        height, width = base.shape[:2]
        with self._lock:
            cached = self._overlay_cache if cache_key == self._overlay_cache_key else None
        if cached is None:
            color, alpha = self._prepare_overlay(norm, config, width, height)
            if cache_key is not None:
                with self._lock:
                    self._overlay_cache_key = cache_key
                    self._overlay_cache = (color, alpha)
        else:
            color, alpha = cached

        result = base.copy()
        self._blend_clipped(result, color, alpha, geometry.left, geometry.top)

        if config.mode == "glitch":
            mask = np.zeros((height, width), dtype=np.float32)
            self._paste_clipped(mask, alpha, geometry.left, geometry.top)
            shift = np.round(mask * 22).astype(np.float32)
            grid_x, grid_y = np.meshgrid(
                np.arange(width, dtype=np.float32), np.arange(height, dtype=np.float32)
            )
            displaced = cv2.remap(
                base,
                grid_x + shift,
                grid_y,
                cv2.INTER_LINEAR,
                borderMode=cv2.BORDER_REFLECT,
            )
            amount = np.clip(mask[..., None] * 0.55, 0.0, 1.0)
            result = (result * (1.0 - amount) + displaced * amount).astype(np.uint8)
        return result

    @staticmethod
    def _geometry(
        shape: tuple[int, ...], config: AuraConfig, now: float
    ) -> OverlayGeometry:
        height, width = shape[:2]
        overlay_w = max(1, round(width * config.scale_x))
        overlay_h = max(1, round(height * config.scale_y))
        offset_x, offset_y = config.offset_x, config.offset_y
        if config.mode == "ghost":
            offset_x += round(config.ghost_x * math.sin(now * 0.7))
            offset_y += round(config.ghost_y * math.cos(now * 0.53))
        return OverlayGeometry(
            left=(width - overlay_w) // 2 + offset_x,
            top=(height - overlay_h) // 2 + offset_y,
            width=overlay_w,
            height=overlay_h,
            rotation=config.rotation,
        )

    @staticmethod
    def _bounds(
        target_shape: tuple[int, ...],
        source_shape: tuple[int, ...],
        left: int,
        top: int,
    ):
        target_h, target_w = target_shape[:2]
        source_h, source_w = source_shape[:2]
        x0, y0 = max(0, left), max(0, top)
        x1, y1 = min(target_w, left + source_w), min(target_h, top + source_h)
        if x0 >= x1 or y0 >= y1:
            return None
        return x0, y0, x1, y1, x0 - left, y0 - top

    @classmethod
    def _blend_clipped(
        cls,
        target: np.ndarray,
        color: np.ndarray,
        alpha: np.ndarray,
        left: int,
        top: int,
    ) -> None:
        bounds = cls._bounds(target.shape, color.shape, left, top)
        if bounds is None:
            return
        x0, y0, x1, y1, sx, sy = bounds
        source = color[sy : sy + y1 - y0, sx : sx + x1 - x0]
        mask = alpha[sy : sy + y1 - y0, sx : sx + x1 - x0].astype(
            np.float32, copy=False
        )
        if not np.any(mask):
            return
        destination = target[y0:y1, x0:x1]
        target[y0:y1, x0:x1] = cv2.blendLinear(
            destination,
            source,
            1.0 - mask,
            mask,
        )

    @classmethod
    def _paste_clipped(
        cls, target: np.ndarray, source: np.ndarray, left: int, top: int
    ) -> None:
        bounds = cls._bounds(target.shape, source.shape, left, top)
        if bounds is None:
            return
        x0, y0, x1, y1, sx, sy = bounds
        target[y0:y1, x0:x1] = source[sy : sy + y1 - y0, sx : sx + x1 - x0]
