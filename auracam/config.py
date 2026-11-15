from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any

from .control import CAMERA_FOVS, CAMERA_LOOKS, HUD_MODES, HUD_PALETTES, MODES

PALETTES = ("aura", "inferno", "turbo", "ocean", "magma")
REPRESENTATIONS = ("temperature", "image")
INTERPOLATIONS = ("nearest", "bilinear", "cubic")

_ALIASES = {
    "base_rotation": "camera_rotation",
    "opacity": "max_alpha",
}


@dataclass(frozen=True)
class AuraConfig:
    image_source: str = "uv"
    mode: str = "clean"
    representation: str = "temperature"
    palette: str = "aura"
    interpolation: str = "bilinear"
    grid: bool = False
    thermal_min: float = 20.0
    thermal_max: float = 38.0
    threshold: float = 26.0
    image_threshold: float = 0.35
    gain: float = 1.0
    alpha_gain: float = 3.0
    max_alpha: float = 0.58
    feather: float = 3.0
    blur: float = 9.0
    smoothing: float = 0.35
    trail_decay: float = 0.0
    scale_x: float = 0.72
    scale_y: float = 0.72
    offset_x: int = 0
    offset_y: int = 0
    rotation: float = 0.0
    ghost_x: int = 24
    ghost_y: int = -8
    refresh_hz: float = 4.0
    emissivity: float = 0.95
    reflected_offset: float = 8.0
    camera_rotation: int = 0
    thermal_rotation: int = 0
    thermal_mirror_h: bool = False
    mirror_h: bool = False
    mirror_v: bool = False
    brightness: float = 1.0
    contrast: float = 1.0
    saturation: float = 1.0
    gamma: float = 1.0
    sharpness: float = 1.0
    host_fps_cap: int = 30
    jpeg_quality: int = 88
    hud_mode: str = "off"
    camera_look: str = "natural"
    camera_fov: str = "crop"
    hud_palette: str = "green"
    probe_x: int = 16
    probe_y: int = 12

    @property
    def base_rotation(self) -> int:
        return self.camera_rotation

    @property
    def opacity(self) -> float:
        return self.max_alpha


_RANGES: dict[str, tuple[float, float]] = {
    "thermal_min": (-40.0, 200.0),
    "thermal_max": (-39.0, 300.0),
    "threshold": (-40.0, 300.0),
    "image_threshold": (0.0, 1.0),
    "gain": (0.05, 10.0),
    "alpha_gain": (0.05, 20.0),
    "max_alpha": (0.0, 1.0),
    "feather": (0.05, 50.0),
    "blur": (0.0, 80.0),
    "smoothing": (0.0, 0.98),
    "trail_decay": (0.0, 0.995),
    "scale_x": (0.05, 2.5),
    "scale_y": (0.05, 2.5),
    "offset_x": (-4096, 4096),
    "offset_y": (-4096, 4096),
    "rotation": (-180.0, 180.0),
    "ghost_x": (-2048, 2048),
    "ghost_y": (-2048, 2048),
    "refresh_hz": (0.5, 64.0),
    "emissivity": (0.1, 1.0),
    "reflected_offset": (0.0, 50.0),
    "brightness": (0.1, 3.0),
    "contrast": (0.1, 3.0),
    "saturation": (0.0, 3.0),
    "gamma": (0.1, 4.0),
    "sharpness": (0.0, 4.0),
    "host_fps_cap": (1, 30),
    "jpeg_quality": (40, 100),
    "probe_x": (0, 31),
    "probe_y": (0, 23),
}

_CHOICES = {
    "image_source": ("uv", "rgb"),
    "mode": MODES,
    "representation": REPRESENTATIONS,
    "palette": PALETTES,
    "interpolation": INTERPOLATIONS,
    "camera_rotation": (0, 90, 180, 270),
    "thermal_rotation": (0, 90, 180, 270),
    "hud_mode": HUD_MODES,
    "hud_palette": HUD_PALETTES,
    "camera_look": CAMERA_LOOKS,
    "camera_fov": CAMERA_FOVS,
}


def canonical_name(name: str) -> str:
    return _ALIASES.get(name, name)


def _coerce(name: str, value: Any, current: AuraConfig) -> Any:
    name = canonical_name(name)
    if name == "interpolation" and str(value).lower() == "linear":
        value = "bilinear"
    names = {field.name: field.type for field in fields(AuraConfig)}
    if name not in names:
        raise ValueError(f"Unknown setting: {name}")
    old = getattr(current, name)
    if isinstance(old, bool):
        if isinstance(value, str):
            lowered = value.lower()
            if lowered not in ("1", "0", "true", "false", "yes", "no", "on", "off"):
                raise ValueError(f"{name} expects on/off")
            value = lowered in ("1", "true", "yes", "on")
        else:
            value = bool(value)
    elif isinstance(old, int) and not isinstance(old, bool):
        value = int(value)
    elif isinstance(old, float):
        value = float(value)
    else:
        value = str(value).lower()

    if name in _CHOICES and value not in _CHOICES[name]:
        allowed = ", ".join(map(str, _CHOICES[name]))
        raise ValueError(f"{name} must be one of: {allowed}")
    if name in _RANGES:
        low, high = _RANGES[name]
        if not low <= value <= high:
            raise ValueError(f"{name} must be between {low:g} and {high:g}")
    return value


class ConfigStore:
    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path).expanduser()
        self._lock = threading.RLock()
        self._config = AuraConfig()
        self.load()

    def load(self) -> AuraConfig:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("configuration root is not an object")
        except FileNotFoundError:
            return self._config
        except (OSError, json.JSONDecodeError, ValueError):
            return self._config
        config = AuraConfig()
        for name, value in payload.items():
            try:
                name = canonical_name(name)
                config = replace(config, **{name: _coerce(name, value, config)})
            except (TypeError, ValueError):
                continue
        with self._lock:
            self._config = config
        return config

    def get(self) -> AuraConfig:
        with self._lock:
            return self._config

    def update(self, name: str, value: Any) -> AuraConfig:
        with self._lock:
            name = canonical_name(name)
            value = _coerce(name, value, self._config)
            candidate = replace(self._config, **{name: value})
            if candidate.thermal_max <= candidate.thermal_min:
                raise ValueError("thermal_max must be greater than thermal_min")
            self._config = candidate
            self._save_locked()
            return candidate

    def adjust(self, name: str, delta: float) -> AuraConfig:
        name = canonical_name(name)
        current = getattr(self.get(), name)
        if not isinstance(current, (int, float)) or isinstance(current, bool):
            raise ValueError(f"{name} is not numeric")
        value = current + delta
        if name in _RANGES:
            low, high = _RANGES[name]
            value = max(low, min(high, value))
        return self.update(name, value)

    def cycle_rotation(self, name: str) -> AuraConfig:
        name = canonical_name(name)
        if name not in ("camera_rotation", "thermal_rotation"):
            raise ValueError(
                "rotation source must be camera_rotation or thermal_rotation"
            )
        return self.update(name, (getattr(self.get(), name) + 90) % 360)

    def toggle(self, name: str) -> AuraConfig:
        name = canonical_name(name)
        current = getattr(self.get(), name)
        if not isinstance(current, bool):
            raise ValueError(f"{name} is not on/off")
        return self.update(name, not current)

    def apply_mode(self, mode: str) -> AuraConfig:
        mode = str(mode).lower()
        if mode not in MODES:
            raise ValueError(f"mode must be one of: {', '.join(MODES)}")
        presets: dict[str, dict[str, Any]] = {
            "debug": {
                "grid": True,
                "interpolation": "nearest",
                "blur": 0.0,
                "alpha_gain": 3.0,
                "max_alpha": 0.72,
                "trail_decay": 0.0,
            },
            "clean": {
                "grid": False,
                "interpolation": "bilinear",
                "blur": 9.0,
                "alpha_gain": 3.0,
                "max_alpha": 0.58,
                "trail_decay": 0.0,
            },
            "threshold": {
                "grid": False,
                "interpolation": "bilinear",
                "blur": 6.0,
                "alpha_gain": 6.0,
                "max_alpha": 0.72,
                "trail_decay": 0.0,
            },
            "trail": {
                "grid": False,
                "interpolation": "bilinear",
                "blur": 9.0,
                "alpha_gain": 3.0,
                "max_alpha": 0.58,
                "trail_decay": 0.84,
            },
            "pixel": {
                "grid": True,
                "interpolation": "nearest",
                "blur": 0.0,
                "alpha_gain": 3.0,
                "max_alpha": 0.65,
                "trail_decay": 0.0,
            },
        }
        with self._lock:
            updates = {"mode": mode, **presets.get(mode, {})}
            candidate = self._config
            for name, value in updates.items():
                candidate = replace(
                    candidate, **{name: _coerce(name, value, candidate)}
                )
            self._config = candidate
            self._save_locked()
            return candidate

    def as_dict(self) -> dict[str, Any]:
        return asdict(self.get())

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(asdict(self._config), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
