from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ThermalFrame:
    temperatures: np.ndarray
    image: np.ndarray
    timestamp_ns: int
    subpage: int
    ambient: float
    vdd: float
    complete: bool
    sequence: int

    @property
    def minimum(self) -> float:
        return float(np.nanmin(self.temperatures))

    @property
    def maximum(self) -> float:
        return float(np.nanmax(self.temperatures))


@dataclass(frozen=True)
class HudTelemetry:
    uv_fps: float
    thermal_fps: float
    output_fps: float
    uv_relative: float
    recording_seconds: float | None
    recording_frames: int
    i2c_errors: int
    source_label: str = "UV"


@dataclass(frozen=True)
class OverlayGeometry:
    left: int
    top: int
    width: int
    height: int
    rotation: float
