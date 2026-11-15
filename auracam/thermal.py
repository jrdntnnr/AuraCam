from __future__ import annotations

import ctypes
import math
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

import numpy as np

from .frames import ThermalFrame

REFRESH_CODES = {0.5: 0, 1.0: 1, 2.0: 2, 4.0: 3, 8.0: 4, 16.0: 5, 32.0: 6, 64.0: 7}
NON_FATAL_PIXEL_WARNINGS = {-3, -4, -5, -6}


def nearest_refresh(value: float) -> tuple[float, int]:
    hz = min(REFRESH_CODES, key=lambda candidate: abs(candidate - value))
    return hz, REFRESH_CODES[hz]


class MLX90640:
    WIDTH = 32
    HEIGHT = 24

    def __init__(
        self, library: str | None = None, bus: str = "/dev/i2c-1", address: int = 0x33
    ):
        default = Path(__file__).with_name("native") / "libmlx90640.so"
        self.library_path = Path(library) if library else default
        self.bus = bus
        self.address = address
        self._lib: ctypes.CDLL | None = None
        self._sequence = 0

    def open(self, refresh_hz: float = 4.0) -> None:
        if not self.library_path.exists():
            raise RuntimeError(
                f"MLX90640 native library not found: {self.library_path}"
            )
        lib = ctypes.CDLL(str(self.library_path))
        float_pointer = ctypes.POINTER(ctypes.c_float)
        lib.auracam_mlx_init.argtypes = [ctypes.c_char_p, ctypes.c_uint8, ctypes.c_int]
        lib.auracam_mlx_init.restype = ctypes.c_int
        lib.auracam_mlx_read.argtypes = [
            ctypes.c_float,
            ctypes.c_float,
            float_pointer,
            float_pointer,
            float_pointer,
            float_pointer,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
        ]
        lib.auracam_mlx_read.restype = ctypes.c_int
        lib.auracam_mlx_set_refresh.argtypes = [ctypes.c_int]
        lib.auracam_mlx_set_refresh.restype = ctypes.c_int
        lib.auracam_mlx_error.restype = ctypes.c_char_p
        lib.auracam_mlx_close.restype = None
        _, code = nearest_refresh(refresh_hz)
        result = lib.auracam_mlx_init(str(self.bus).encode(), self.address, code)
        if result != 0 and result not in NON_FATAL_PIXEL_WARNINGS:
            error = lib.auracam_mlx_error().decode(errors="replace")
            lib.auracam_mlx_close()
            raise RuntimeError(error)
        self._lib = lib

    def set_refresh(self, refresh_hz: float) -> float:
        if self._lib is None:
            raise RuntimeError("sensor is not open")
        hz, code = nearest_refresh(refresh_hz)
        result = self._lib.auracam_mlx_set_refresh(code)
        if result != 0:
            raise RuntimeError(self.error)
        return hz

    @property
    def error(self) -> str:
        if self._lib is None:
            return "sensor is not open"
        return self._lib.auracam_mlx_error().decode(errors="replace")

    def read(
        self, emissivity: float = 0.95, reflected_offset: float = 8.0
    ) -> ThermalFrame:
        if self._lib is None:
            raise RuntimeError("sensor is not open")
        temperatures = np.empty(768, dtype=np.float32)
        image = np.empty(768, dtype=np.float32)
        ambient = ctypes.c_float()
        vdd = ctypes.c_float()
        subpage = ctypes.c_int()
        complete = ctypes.c_int()
        result = self._lib.auracam_mlx_read(
            emissivity,
            reflected_offset,
            temperatures.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
            image.ctypes.data_as(ctypes.POINTER(ctypes.c_float)),
            ctypes.byref(ambient),
            ctypes.byref(vdd),
            ctypes.byref(subpage),
            ctypes.byref(complete),
        )
        if result != 0:
            raise RuntimeError(self.error)
        self._sequence += 1
        return ThermalFrame(
            temperatures=temperatures.reshape(24, 32).copy(),
            image=image.reshape(24, 32).copy(),
            timestamp_ns=time.monotonic_ns(),
            subpage=subpage.value,
            ambient=float(ambient.value),
            vdd=float(vdd.value),
            complete=bool(complete.value),
            sequence=self._sequence,
        )

    def close(self) -> None:
        if self._lib is not None:
            self._lib.auracam_mlx_close()
            self._lib = None


class ThermalWorker:
    def __init__(
        self,
        config: Callable[[], object],
        sensor_factory: Callable[[], MLX90640] = MLX90640,
    ):
        self._config = config
        self._sensor_factory = sensor_factory
        self._sensor: MLX90640 | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._latest: ThermalFrame | None = None
        self._timestamps: deque[float] = deque(maxlen=64)
        self.error: str | None = None
        self.errors = 0
        self.connected = False
        self.actual_refresh_hz = 0.0
        self._configured_refresh = 0.0

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="mlx90640", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        if self._sensor:
            self._sensor.close()

    def latest(self) -> ThermalFrame | None:
        with self._lock:
            return self._latest

    @property
    def fps(self) -> float:
        with self._lock:
            stamps = tuple(self._timestamps)
        if len(stamps) < 2:
            return 0.0
        return (len(stamps) - 1) / max(0.001, stamps[-1] - stamps[0])

    def _connect(self) -> None:
        config = self._config()
        sensor = self._sensor_factory()
        sensor.open(config.refresh_hz)
        self._sensor = sensor
        self.actual_refresh_hz, _ = nearest_refresh(config.refresh_hz)
        self._configured_refresh = config.refresh_hz
        self.connected = True
        self.error = None

    def _run(self) -> None:
        retry_at = 0.0
        while not self._stop.is_set():
            if self._sensor is None:
                if time.monotonic() < retry_at:
                    self._stop.wait(0.25)
                    continue
                try:
                    self._connect()
                except Exception as exc:
                    self.errors += 1
                    self.error = str(exc)
                    self.connected = False
                    retry_at = time.monotonic() + 5.0
                    continue
            try:
                config = self._config()
                if not math.isclose(config.refresh_hz, self._configured_refresh):
                    self.actual_refresh_hz = self._sensor.set_refresh(config.refresh_hz)
                    self._configured_refresh = config.refresh_hz
                frame = self._sensor.read(config.emissivity, config.reflected_offset)
                if not frame.complete:
                    continue
                now = time.monotonic()
                with self._lock:
                    self._latest = frame
                    self._timestamps.append(now)
                self.error = None
            except Exception as exc:
                self.errors += 1
                self.error = str(exc)
                self.connected = False
                with self._lock:
                    self._latest = None
                    self._timestamps.clear()
                if self._sensor:
                    self._sensor.close()
                self._sensor = None
                retry_at = time.monotonic() + 2.0


class DemoMLX90640(MLX90640):
    def open(self, refresh_hz: float = 4.0) -> None:
        self._started = time.monotonic()
        self._refresh = refresh_hz

    def set_refresh(self, refresh_hz: float) -> float:
        self._refresh = refresh_hz
        return refresh_hz

    def read(
        self, emissivity: float = 0.95, reflected_offset: float = 8.0
    ) -> ThermalFrame:
        time.sleep(1.0 / max(1.0, self._refresh * 2.0))
        y, x = np.mgrid[0:24, 0:32]
        elapsed = time.monotonic() - self._started
        cx = 16 + math.sin(elapsed * 0.7) * 9
        cy = 12 + math.cos(elapsed * 0.9) * 6
        field = 21.0 + 17.0 * np.exp(-(((x - cx) / 5) ** 2 + ((y - cy) / 4) ** 2))
        self._sequence += 1
        return ThermalFrame(
            temperatures=field.astype(np.float32),
            image=(field - 21).astype(np.float32),
            timestamp_ns=time.monotonic_ns(),
            subpage=self._sequence & 1,
            ambient=22.1,
            vdd=3.3,
            complete=True,
            sequence=self._sequence,
        )

    def close(self) -> None:
        return None
