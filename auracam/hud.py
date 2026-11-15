from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np

from .config import AuraConfig
from .frames import HudTelemetry, OverlayGeometry, ThermalFrame

_FONT = {
    " ": (0, 0, 0, 0, 0, 0, 0),
    "!": (4, 4, 4, 4, 4, 0, 4),
    "%": (17, 2, 4, 8, 17, 0, 0),
    "+": (0, 4, 4, 31, 4, 4, 0),
    ",": (0, 0, 0, 0, 0, 4, 8),
    "-": (0, 0, 0, 31, 0, 0, 0),
    ".": (0, 0, 0, 0, 0, 0, 4),
    "/": (1, 2, 4, 8, 16, 0, 0),
    "0": (14, 17, 19, 21, 25, 17, 14),
    "1": (4, 12, 4, 4, 4, 4, 14),
    "2": (14, 17, 1, 2, 4, 8, 31),
    "3": (30, 1, 1, 14, 1, 1, 30),
    "4": (2, 6, 10, 18, 31, 2, 2),
    "5": (31, 16, 16, 30, 1, 1, 30),
    "6": (14, 16, 16, 30, 17, 17, 14),
    "7": (31, 1, 2, 4, 8, 8, 8),
    "8": (14, 17, 17, 14, 17, 17, 14),
    "9": (14, 17, 17, 15, 1, 1, 14),
    ":": (0, 4, 0, 0, 4, 0, 0),
    "?": (14, 17, 1, 2, 4, 0, 4),
    "A": (14, 17, 17, 31, 17, 17, 17),
    "B": (30, 17, 17, 30, 17, 17, 30),
    "C": (14, 17, 16, 16, 16, 17, 14),
    "D": (30, 17, 17, 17, 17, 17, 30),
    "E": (31, 16, 16, 30, 16, 16, 31),
    "F": (31, 16, 16, 30, 16, 16, 16),
    "G": (14, 17, 16, 23, 17, 17, 15),
    "H": (17, 17, 17, 31, 17, 17, 17),
    "I": (14, 4, 4, 4, 4, 4, 14),
    "J": (7, 2, 2, 2, 2, 18, 12),
    "K": (17, 18, 20, 24, 20, 18, 17),
    "L": (16, 16, 16, 16, 16, 16, 31),
    "M": (17, 27, 21, 21, 17, 17, 17),
    "N": (17, 25, 21, 19, 17, 17, 17),
    "O": (14, 17, 17, 17, 17, 17, 14),
    "P": (30, 17, 17, 30, 16, 16, 16),
    "Q": (14, 17, 17, 17, 21, 18, 13),
    "R": (30, 17, 17, 30, 20, 18, 17),
    "S": (15, 16, 16, 14, 1, 1, 30),
    "T": (31, 4, 4, 4, 4, 4, 4),
    "U": (17, 17, 17, 17, 17, 17, 14),
    "V": (17, 17, 17, 17, 17, 10, 4),
    "W": (17, 17, 17, 21, 21, 21, 10),
    "X": (17, 17, 10, 4, 10, 17, 17),
    "Y": (17, 17, 10, 4, 4, 4, 4),
    "Z": (31, 1, 2, 4, 8, 16, 31),
}
_COLORS = {
    "green": (72, 255, 132),
    "amber": (0, 194, 255),
    "white": (228, 242, 234),
}
_CELL_WIDTH = 6
_CELL_HEIGHT = 8


@dataclass(frozen=True)
class ThermalPoints:
    probe: tuple[int, int]
    high: tuple[int, int]
    low: tuple[int, int]
    probe_value: float
    high_value: float
    low_value: float
    columns: int
    rows: int


class HudRenderer:
    def render(
        self,
        frame: np.ndarray,
        thermal: ThermalFrame | None,
        config: AuraConfig,
        telemetry: HudTelemetry,
        geometry: OverlayGeometry,
    ) -> np.ndarray:
        if config.hud_mode == "off":
            return frame
        color = _COLORS[config.hud_palette]
        scale = 2 if frame.shape[1] >= 560 else 1
        points = self._thermal_points(thermal, config)
        if config.hud_mode == "tactical":
            self._frame_marks(frame, color)
            self._tactical(frame, telemetry, points, config, color, scale)
        else:
            self._minimal(frame, telemetry, points, color, scale)
        if points is not None:
            self._markers(frame, points, geometry, color, scale)
        return frame

    def _minimal(
        self,
        frame: np.ndarray,
        data: HudTelemetry,
        points: ThermalPoints | None,
        color: tuple[int, int, int],
        scale: int,
    ) -> None:
        readings = "IR NO DATA"
        if points is not None:
            readings = (
                f"P{points.probe_value:04.1f} H{points.high_value:04.1f} "
                f"L{points.low_value:04.1f}C"
            )
        self._text(frame, readings, (12, 12), color, scale)
        rates = f"{data.source_label}{data.uv_fps:04.1f} IR{data.thermal_fps:04.1f} FPS"
        self._right_text(frame, rates, 12, color, scale)
        self._text(
            frame,
            f"{data.source_label} REL {round(data.uv_relative * 100):03d}%",
            (12, frame.shape[0] - 12 - 7 * scale),
            color,
            scale,
        )
        if data.recording_seconds is not None:
            rec = f"REC {self._clock(data.recording_seconds)} F{data.recording_frames:05d}"
            self._right_text(frame, rec, frame.shape[0] - 12 - 7 * scale, color, scale)

    def _tactical(
        self,
        frame: np.ndarray,
        data: HudTelemetry,
        points: ThermalPoints | None,
        config: AuraConfig,
        color: tuple[int, int, int],
        scale: int,
    ) -> None:
        y = 14
        for text in (
            f"{data.source_label}  {data.uv_fps:04.1f} FPS",
            f"IR  {data.thermal_fps:04.1f} FPS",
            f"OUT {data.output_fps:04.1f} FPS",
            f"{data.source_label} REL {round(data.uv_relative * 100):03d}%",
        ):
            self._text(frame, text, (18, y), color, scale)
            y += _CELL_HEIGHT * scale + 3
        readings = ("IR NO DATA",)
        if points is not None:
            readings = (
                f"PROBE {points.probe_value:04.1f}C",
                f"HIGH  {points.high_value:04.1f}C",
                f"LOW   {points.low_value:04.1f}C",
            )
        y = 14
        for text in readings:
            self._right_text(frame, text, y, color, scale)
            y += _CELL_HEIGHT * scale + 3
        footer = f"I2C {data.i2c_errors:03d}  PROBE {config.probe_x:02d},{config.probe_y:02d}"
        footer_y = frame.shape[0] - 18 - 7 * scale
        self._text(frame, footer, (18, footer_y), color, scale)
        if data.recording_seconds is not None:
            rec = f"REC {self._clock(data.recording_seconds)} F{data.recording_frames:05d}"
            self._right_text(frame, rec, footer_y, color, scale)

    def _markers(
        self,
        frame: np.ndarray,
        points: ThermalPoints,
        geometry: OverlayGeometry,
        color: tuple[int, int, int],
        scale: int,
    ) -> None:
        items = (
            ("P", points.probe, points.probe_value, cv2.MARKER_CROSS),
            ("H", points.high, points.high_value, cv2.MARKER_DIAMOND),
            ("L", points.low, points.low_value, cv2.MARKER_SQUARE),
        )
        for label, source, value, marker in items:
            point = self._map_point(source, points, geometry)
            if not self._visible(point, frame):
                continue
            size = 13 * scale
            cv2.drawMarker(frame, point, color, marker, size, max(1, scale))
            self._label(frame, f"{label}{value:04.1f}", point, color, scale)

    @staticmethod
    def _thermal_points(
        thermal: ThermalFrame | None, config: AuraConfig
    ) -> ThermalPoints | None:
        if thermal is None:
            return None
        field = thermal.temperatures.astype(np.float32, copy=False)
        if not np.isfinite(field).any():
            return None
        rotated = HudRenderer._rotate(field, config.thermal_rotation)
        if config.thermal_mirror_h:
            rotated = cv2.flip(rotated, 1)
        high_y, high_x = np.unravel_index(np.nanargmax(rotated), rotated.shape)
        low_y, low_x = np.unravel_index(np.nanargmin(rotated), rotated.shape)
        probe_x = min(field.shape[1] - 1, max(0, config.probe_x))
        probe_y = min(field.shape[0] - 1, max(0, config.probe_y))
        mapped_probe = HudRenderer._rotate_point(
            probe_x, probe_y, field.shape, config.thermal_rotation
        )
        if config.thermal_mirror_h:
            mapped_probe = (rotated.shape[1] - 1 - mapped_probe[0], mapped_probe[1])
        return ThermalPoints(
            probe=mapped_probe,
            high=(int(high_x), int(high_y)),
            low=(int(low_x), int(low_y)),
            probe_value=float(field[probe_y, probe_x]),
            high_value=float(rotated[high_y, high_x]),
            low_value=float(rotated[low_y, low_x]),
            columns=rotated.shape[1],
            rows=rotated.shape[0],
        )

    @staticmethod
    def _rotate(field: np.ndarray, rotation: int) -> np.ndarray:
        if rotation == 90:
            return cv2.rotate(field, cv2.ROTATE_90_CLOCKWISE)
        if rotation == 180:
            return cv2.rotate(field, cv2.ROTATE_180)
        if rotation == 270:
            return cv2.rotate(field, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return field

    @staticmethod
    def _rotate_point(
        x: int, y: int, shape: tuple[int, int], rotation: int
    ) -> tuple[int, int]:
        height, width = shape
        if rotation == 90:
            return height - 1 - y, x
        if rotation == 180:
            return width - 1 - x, height - 1 - y
        if rotation == 270:
            return y, width - 1 - x
        return x, y

    @staticmethod
    def _map_point(
        source: tuple[int, int],
        points: ThermalPoints,
        geometry: OverlayGeometry,
    ) -> tuple[int, int]:
        x = (source[0] + 0.5) * geometry.width / points.columns
        y = (source[1] + 0.5) * geometry.height / points.rows
        if geometry.rotation:
            matrix = cv2.getRotationMatrix2D(
                (geometry.width / 2, geometry.height / 2), geometry.rotation, 1.0
            )
            x, y = matrix @ np.array((x, y, 1.0))
        return round(geometry.left + x), round(geometry.top + y)

    @staticmethod
    def _visible(point: tuple[int, int], frame: np.ndarray) -> bool:
        x, y = point
        return 0 <= x < frame.shape[1] and 0 <= y < frame.shape[0]

    def _label(
        self,
        frame: np.ndarray,
        text: str,
        point: tuple[int, int],
        color: tuple[int, int, int],
        scale: int,
    ) -> None:
        width = self._text_width(text, scale)
        x = min(frame.shape[1] - width - 4, max(4, point[0] + 9 * scale))
        y = min(frame.shape[0] - 7 * scale - 4, max(4, point[1] - 9 * scale))
        self._text(frame, text, (x, y), color, scale)

    @staticmethod
    def _frame_marks(frame: np.ndarray, color: tuple[int, int, int]) -> None:
        height, width = frame.shape[:2]
        length = max(18, min(width, height) // 14)
        inset = 8
        for x, y, dx, dy in (
            (inset, inset, 1, 1),
            (width - inset - 1, inset, -1, 1),
            (inset, height - inset - 1, 1, -1),
            (width - inset - 1, height - inset - 1, -1, -1),
        ):
            cv2.line(frame, (x, y), (x + dx * length, y), color, 1)
            cv2.line(frame, (x, y), (x, y + dy * length), color, 1)

    def _right_text(
        self,
        frame: np.ndarray,
        text: str,
        y: int,
        color: tuple[int, int, int],
        scale: int,
    ) -> None:
        x = max(8, frame.shape[1] - self._text_width(text, scale) - 18)
        self._text(frame, text, (x, y), color, scale)

    def _text(
        self,
        frame: np.ndarray,
        text: str,
        origin: tuple[int, int],
        color: tuple[int, int, int],
        scale: int,
    ) -> None:
        mask = self._text_mask(text, scale)
        x, y = origin
        x0, y0 = max(0, x), max(0, y)
        x1 = min(frame.shape[1], x + mask.shape[1])
        y1 = min(frame.shape[0], y + mask.shape[0])
        if x0 >= x1 or y0 >= y1:
            return
        source = mask[y0 - y : y1 - y, x0 - x : x1 - x]
        target = frame[y0:y1, x0:x1]
        dark = source > 0
        target[dark] = (
            target[dark].astype(np.uint16) * 20 + np.array(color) * 80
        ) // 100

    @staticmethod
    @lru_cache(maxsize=256)
    def _text_mask(text: str, scale: int) -> np.ndarray:
        clean = text.upper()
        width = max(1, len(clean) * _CELL_WIDTH - 1)
        mask = np.zeros((7, width), dtype=np.uint8)
        for index, char in enumerate(clean):
            rows = _FONT.get(char, _FONT["?"])
            left = index * _CELL_WIDTH
            for y, row in enumerate(rows):
                for x in range(5):
                    mask[y, left + x] = 255 if row & (1 << (4 - x)) else 0
        if scale == 1:
            return mask
        return np.repeat(np.repeat(mask, scale, axis=0), scale, axis=1)

    @staticmethod
    def _text_width(text: str, scale: int) -> int:
        return max(1, len(text) * _CELL_WIDTH - 1) * scale

    @staticmethod
    def _clock(seconds: float) -> str:
        total = max(0, round(seconds))
        return f"{total // 60:02d}:{total % 60:02d}"
