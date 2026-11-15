from __future__ import annotations

from enum import Enum

DEFAULT_SOCKET = "/run/auracam/control.sock"


class AuraMode(str, Enum):
    DEBUG = "debug"
    CLEAN = "clean"
    THRESHOLD = "threshold"
    TRAIL = "trail"
    PIXEL = "pixel"
    GHOST = "ghost"
    GLITCH = "glitch"


MODES = tuple(mode.value for mode in AuraMode)


class HudMode(str, Enum):
    OFF = "off"
    MINIMAL = "minimal"
    TACTICAL = "tactical"


HUD_MODES = tuple(mode.value for mode in HudMode)


class HudPalette(str, Enum):
    GREEN = "green"
    AMBER = "amber"
    WHITE = "white"


HUD_PALETTES = tuple(palette.value for palette in HudPalette)


class ControlCommand(str, Enum):
    STATUS = "status"
    CONFIG = "config"
    SET = "set"
    ADJUST = "adjust"
    MODE = "mode"
    ROTATE = "rotate"
    TOGGLE = "toggle"
    SNAPSHOT = "snapshot"
    RECORD = "record"
    PAUSE = "pause"
    LENS = "lens"
    PREVIEW = "preview"
    THERMAL_PREVIEW = "thermal_preview"


class RecordAction(str, Enum):
    START = "start"
    STOP = "stop"
    TOGGLE = "toggle"


class SwitchAction(str, Enum):
    ON = "on"
    OFF = "off"
    TOGGLE = "toggle"


class RotationSource(str, Enum):
    CAMERA = "camera"
    THERMAL = "thermal"


class CaptureSource(str, Enum):
    HARDWARE = "hardware"
    DEMO = "demo"
