"""Cardputer Zero bridge between the capture daemon and the LVGL frontend.

The frontend (cardputer/main.cpp) owns the screen; this process feeds it
fixed-size packets on stdout and takes key characters on stdin.

    packet = TEXT_BYTES of tab-separated fields + 192x144 BGRA preview

    BOOT  color  header  steps  -      -        footer
    LIVE  color  header  left   right  actions  -

`steps` are "LABEL|STATE" lines (STATE "RUN" draws the spinner); `left`,
`right` are newline-separated side-panel lines; `actions` are the five
labels above keys 4-8.
"""

from __future__ import annotations

import base64
import os
import select
import subprocess
import sys
import time
from enum import Enum
from pathlib import Path

import cv2
import numpy as np

from .cli import AuraClient
from .config import ConfigStore
from .control import CAMERA_FOVS, CAMERA_LOOKS, HUD_MODES, MODES, CameraFov, CameraLook, HudMode
from .hud import CornerMarks, HudRenderer, Marker, palette_rgb

PREVIEW_SIZE = (192, 144)
TEXT_BYTES = 1024
ENGINE_START_TIMEOUT_S = 90.0
THERMAL_GRACE_S = 20.0
BOOT_POLL_S = 0.1
BOOT_DONE_HOLD_S = 0.8
ERROR_HOLD_S = 4.0
MESSAGE_HOLD_S = 3.0
EXIT_KEY = "q"
SIDE_CHARS = 10
HEADER_CHARS = 40
# MLX90640 at 16 Hz needs the I2C bus at 400 kHz (scripts/set_i2c_baud.sh).
THERMAL_REFRESH_HZ = 16.0
# Composite at the rate the 320x170 panel can show; the camera still runs at 30.
COMPOSITE_FPS = 15
# The Pi build's yellow-orange HUD.
PALETTE = "amber"
# Calibration: overlay geometry plus the grid shown while aligning.
CALIBRATION_FIELDS = ("offset_x", "offset_y", "scale_x", "scale_y", "grid")
ARROWS = {"U": (0, -1), "D": (0, 1), "L": (-1, 0), "R": (1, 0)}
# Index by coarse flag: (fine, coarse). Moves are output-frame pixels.
MOVE_STEPS = (2, 10)
ZOOM_STEPS = (0.01, 0.05)
# Threshold step in C, by coarse flag: (fine, coarse).
THRESHOLD_STEPS = (0.5, 2.0)
# Thermal gradients offered on the Cardputer, in cycle order.
GRADIENTS = ("aura", "ironbow", "amber", "whitehot", "turbo", "arctic")
GRADIENT_HOLD_S = 1.5
EXT_POWER = Path("/sys/class/leds/ext_5v_out/brightness")
I2C_CLOCK = Path("/proc/device-tree/soc/i2c@7e804000/clock-frequency")


class Screen(Enum):
    CAPTURE = "capture"
    MENU = "menu"
    CALIBRATE = "calibrate"
    IR = "ir"


class Kind(str, Enum):
    BOOT = "BOOT"
    LIVE = "LIVE"


class State(str, Enum):
    RUN = "RUN"
    OK = "OK"
    FAIL = "FAIL"
    OFF = "OFF"


def _clean(text: object) -> str:
    """Packets are ASCII; tabs and pipes are field separators."""
    return str(text).upper().replace("\t", " ").replace("|", "/")


def _fields(kind: Kind, color: int, *fields: str) -> bytes:
    text = "\t".join([kind.value, f"{color:06X}", *fields])
    data = text.encode("ascii", "replace")[: TEXT_BYTES - 1]
    return data.ljust(TEXT_BYTES, b"\0")


class BootLog:
    """Ordered startup steps shown as a terminal log."""

    def __init__(self):
        self.steps: list[list[str]] = []

    def set(self, label: str, state: State | str) -> None:
        value = state.value if isinstance(state, State) else _clean(state)
        for step in self.steps:
            if step[0] == label:
                step[1] = value
                return
        self.steps.append([label, value])

    def state(self, label: str) -> str | None:
        for name, value in self.steps:
            if name == label:
                return value
        return None

    def text(self) -> str:
        return "\n".join(f"{_clean(label)}|{value}" for label, value in self.steps)


class CardputerBridge:
    def __init__(self, client):
        self.client = client
        self.screen = Screen.CAPTURE
        self.coarse = False
        self.coarse_threshold = False
        self._calibration: dict = {}
        self.palette = PALETTE
        self.message = ""
        self.message_until = 0.0
        self.pixels = bytes(PREVIEW_SIZE[0] * PREVIEW_SIZE[1] * 4)
        self.log = BootLog()
        self._overlay = HudRenderer()

    # Keys 4-8 under the screen act on the current screen; U/D/L/R are the
    # arrow keys (F/Z/X/C on the Cardputer), used only while calibrating.
    def action(self, key):
        config = self.client.request("status")["config"]
        handlers = {
            Screen.CAPTURE: self._capture_key,
            Screen.MENU: self._menu_key,
            Screen.CALIBRATE: self._calibrate_key,
            Screen.IR: self._ir_key,
        }
        handlers[self.screen](key, config)

    def _capture_key(self, key, config):
        if key == "4":
            self.screen = Screen.MENU
        elif key == "5":
            result = self.client.request("snapshot")
            self.say("SAVED " + Path(result["path"]).stem)
        elif key == "6":
            self.client.request("record", action="toggle")
        elif key == "7":
            self._cycle(config, "hud_mode", HUD_MODES)
        elif key == "8":
            mode = MODES[(MODES.index(config["mode"]) + 1) % len(MODES)]
            self.client.request("mode", mode=mode)

    def _menu_key(self, key, config):
        if key == "4":
            self.screen = Screen.CAPTURE
        elif key == "5":
            self._cycle(config, "camera_look", CAMERA_LOOKS)
        elif key == "6":
            self._cycle(config, "camera_fov", CAMERA_FOVS)
        elif key == "7":
            # Remember the calibration to restore on cancel; the grid shows
            # the whole thermal frame while aligning it.
            self._calibration = {name: config[name] for name in CALIBRATION_FIELDS}
            self.coarse = False
            self._set("grid", True)
            self.screen = Screen.CALIBRATE
        elif key == "8":
            self.screen = Screen.IR

    def _calibrate_key(self, key, config):
        if key in ARROWS:
            dx, dy = ARROWS[key]
            step = MOVE_STEPS[self.coarse]
            if dx:
                self._set("offset_x", config["offset_x"] + dx * step)
            if dy:
                self._set("offset_y", config["offset_y"] + dy * step)
        elif key in ("5", "6"):
            # Zoom keeps the aspect: both axes scale by the same factor.
            factor = 1.0 + ZOOM_STEPS[self.coarse] * (1 if key == "6" else -1)
            self._set("scale_x", round(config["scale_x"] * factor, 4))
            self._set("scale_y", round(config["scale_y"] * factor, 4))
        elif key == "7":
            self.coarse = not self.coarse
        elif key == "4":
            self._set("grid", self._calibration["grid"])
            self.say("CALIBRATION SAVED")
            self.screen = Screen.CAPTURE
        elif key == "8":
            for name, value in self._calibration.items():
                self._set(name, value)
            self.screen = Screen.CAPTURE

    def _ir_key(self, key, config):
        if key == "4":
            self.screen = Screen.CAPTURE
        elif key == "5":
            # Unlisted palettes (set from the CLI) restart the cycle.
            current = config.get("palette")
            index = GRADIENTS.index(current) + 1 if current in GRADIENTS else 0
            palette = GRADIENTS[index % len(GRADIENTS)]
            self._set("palette", palette)
            self.say(palette.upper(), GRADIENT_HOLD_S)
        elif key in ("6", "7"):
            step = THRESHOLD_STEPS[self.coarse_threshold]
            self.client.request("adjust", name="threshold", delta=step if key == "7" else -step)
        elif key == "8":
            self.coarse_threshold = not self.coarse_threshold

    def _cycle(self, config, name, choices):
        self._set(name, choices[(choices.index(config[name]) + 1) % len(choices)])

    def _set(self, name, value):
        self.client.request("set", name=name, value=value)

    def say(self, message: str, hold: float = MESSAGE_HOLD_S) -> None:
        self.message = message
        self.message_until = time.monotonic() + hold

    def boot_packet(self, log: BootLog, footer: str) -> bytes:
        return _fields(Kind.BOOT, palette_rgb(self.palette), "", log.text(), "", "", _clean(footer)) + self.pixels

    # One preview request per packet: it carries the JPEG and full status.
    def packet(self):
        try:
            response = self.client.request("preview", width=PREVIEW_SIZE[0], height=PREVIEW_SIZE[1], layer="clean")
        except OSError as exc:
            log = BootLog()
            log.set("ENGINE", State.FAIL)
            return self.boot_packet(log, f"ENGINE OFFLINE {exc}"[:60])
        status = response["status"]
        self.palette = status["config"]["hud_palette"]
        self._update_pixels(response["jpeg"], status)
        header = self._header(status)
        left = "\n".join(line[:SIDE_CHARS] for line in self._left(status))
        right = "\n".join(line[:SIDE_CHARS] for line in self._right(status))
        return _fields(Kind.LIVE, palette_rgb(self.palette), header, left, right, self._actions(status), "") + self.pixels

    def _update_pixels(self, jpeg, status):
        if not jpeg:
            return
        data = np.frombuffer(base64.b64decode(jpeg), np.uint8)
        frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if frame is None:
            return
        if (frame.shape[1], frame.shape[0]) != PREVIEW_SIZE:
            frame = cv2.resize(frame, PREVIEW_SIZE, interpolation=cv2.INTER_AREA)
        # The screen mirrors the HUD mode that snapshots and recordings burn in.
        hud = status["config"].get("hud_mode", HudMode.OFF.value)
        if hud != HudMode.OFF.value:
            corners = CornerMarks.SHOW if hud == HudMode.TACTICAL.value else CornerMarks.HIDE
            self._overlay.overlay(frame, self._markers(status), self.palette, corners)
        self.pixels = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA).tobytes()

    @staticmethod
    def _markers(status) -> list[Marker]:
        """Daemon markers are in output-frame pixels; map them onto the preview."""
        output = status.get("output", {})
        sx = PREVIEW_SIZE[0] / output.get("width", PREVIEW_SIZE[0])
        sy = PREVIEW_SIZE[1] / output.get("height", PREVIEW_SIZE[1])
        return [
            Marker(item["label"], round(item["x"] * sx), round(item["y"] * sy), item["value"])
            for item in status["thermal"].get("markers", [])
        ]

    def _header(self, status) -> str:
        if time.monotonic() < self.message_until:
            return _clean(self.message)[:HEADER_CHARS]
        if self.screen is Screen.CALIBRATE:
            return "CALIBRATE"
        if self.screen is Screen.IR:
            return "IR"
        recording = status["recording"]
        if recording.get("saving"):
            return "SAVING"
        if recording["active"]:
            seconds = round(recording["seconds"])
            return f"REC {seconds // 60:02d}:{seconds % 60:02d}"
        error = status["uv"]["error"] or status["thermal"]["error"]
        if error:
            return _clean(error)[:HEADER_CHARS]
        return ""

    # Left column: stream rates and capture state, as in the tactical HUD.
    def _left(self, status) -> list[str]:
        config = status["config"]
        if self.screen is Screen.CALIBRATE:
            return [
                f"X {config['offset_x']:+d}",
                f"Y {config['offset_y']:+d}",
                f"Z {config['scale_x']:.2f}",
            ]
        uv = status["uv"]
        thermal = status["thermal"]
        source = config["image_source"].upper()
        # Natural crop is the default and shows nothing, e.g. "MONO WIDE".
        parts = [config.get("camera_look", CameraLook.NATURAL.value), config.get("camera_fov")]
        look = _clean(" ".join(p for p in parts if p not in (CameraLook.NATURAL.value, CameraFov.CROP.value, None)))
        return [
            f"{source} {uv['fps']:.0f}",
            f"IR  {thermal['fps']:.0f}",
            "",
            look,
            _clean(config["mode"]),
            f"{config['threshold']:.1f}C",
        ]

    # Right column: probe/high/low readings and sensor health.
    def _right(self, status) -> list[str]:
        thermal = status["thermal"]
        if not thermal["connected"]:
            return ["IR OFF"]
        if thermal["min"] is None:
            return ["WARMUP"]
        else:
            values = {item["label"]: item["value"] for item in thermal.get("markers", [])}
            high = values.get("H", thermal["max"])
            low = values.get("L", thermal["min"])
            probe = values.get("P")
        return [
            f"P {probe:4.1f}C" if probe is not None else "P  --.-C",
            f"H {high:4.1f}C",
            f"L {low:4.1f}C",
        ]

    def _actions(self, status) -> str:
        if self.screen is Screen.MENU:
            return "BACK|LOOK|WIDE|CAL|IR"
        if self.screen is Screen.CALIBRATE:
            step = "COARSE" if self.coarse else "FINE"
            return f"SAVE|ZOOM -|ZOOM +|{step}|CANCEL"
        if self.screen is Screen.IR:
            step = THRESHOLD_STEPS[self.coarse_threshold]
            return f"DONE|COLORS|TEMP -|TEMP +|{step:.1f}C"
        record = "STOP" if status["recording"]["active"] else "RECORD"
        return f"MENU|SNAP|{record}|HUD|MODE"


def emit(packet):
    sys.stdout.buffer.write(packet)
    sys.stdout.buffer.flush()


def _read_keys() -> str | None:
    """Pending key characters, or None once the frontend closed stdin."""
    ready, _, _ = select.select([sys.stdin], [], [], BOOT_POLL_S)
    if not ready:
        return ""
    keys = os.read(sys.stdin.fileno(), 32).decode("ascii", "replace")
    if not keys or EXIT_KEY in keys:
        return None
    return keys


def _hardware_steps(log: BootLog) -> None:
    """Static checks: port power and I2C clock (Cardputer device tree)."""
    try:
        powered = int(EXT_POWER.read_text().strip()) > 0
        log.set("5V", State.OK if powered else State.OFF)
    except (OSError, ValueError):
        log.set("5V", "N/A")
    try:
        hertz = int.from_bytes(I2C_CLOCK.read_bytes()[:4], "big")
    except OSError:
        hertz = 100_000
    log.set("I2C", f"{hertz // 1000}K")


def boot(process, client, bridge) -> bool:
    """Show startup as a terminal log until the first composite arrives.

    Returns False when the frontend asked to quit during startup."""
    log = bridge.log
    log.set("BRIDGE", State.OK)
    _hardware_steps(log)
    log.set("ENGINE", State.RUN)
    started = time.monotonic()
    engine_at = None
    done_at = None

    while True:
        keys = _read_keys()
        if keys is None:
            return False
        if process.poll() is not None:
            log.set("ENGINE", State.FAIL)
            raise RuntimeError("Capture engine exited during startup")
        elapsed = time.monotonic() - started
        if elapsed > ENGINE_START_TIMEOUT_S:
            raise RuntimeError("Capture engine did not start")

        # Engine socket up -> camera -> thermal -> first composite.
        try:
            response = client.request("preview", width=PREVIEW_SIZE[0], height=PREVIEW_SIZE[1], layer="clean")
        except OSError:
            emit(bridge.boot_packet(log, ""))
            continue
        status = response["status"]
        bridge.palette = status["config"]["hud_palette"]
        if engine_at is None:
            engine_at = time.monotonic()
            log.set("ENGINE", State.OK)
            log.set("CAMERA", State.RUN)
            log.set("THERMAL", State.RUN)
        _camera_step(log, status)
        _thermal_step(log, status, time.monotonic() - engine_at)
        footer = (status["uv"]["error"] or "")[:60]
        if response["jpeg"] and log.state("FRAME") is None:
            log.set("FRAME", State.RUN)
        if response["jpeg"] and _settled(log):
            log.set("FRAME", State.OK)
            done_at = done_at or time.monotonic()
        emit(bridge.boot_packet(log, footer))
        if done_at and time.monotonic() - done_at >= BOOT_DONE_HOLD_S:
            return True


def _camera_step(log: BootLog, status) -> None:
    uv = status["uv"]
    if uv["connected"] and uv["fps"] > 0:
        log.set("CAMERA", f"{uv['fps']:.0f}FPS")
    elif uv["error"]:
        log.set("CAMERA", State.FAIL)


def _thermal_step(log: BootLog, status, since_engine: float) -> None:
    thermal = status["thermal"]
    if thermal["connected"] and thermal["min"] is not None:
        log.set("THERMAL", f"{thermal['refresh_hz']:.0f}HZ")
    elif since_engine > THERMAL_GRACE_S:
        log.set("THERMAL", State.OFF)


def _settled(log: BootLog) -> bool:
    """Camera and thermal steps resolved (thermal may be offline)."""
    camera = log.state("CAMERA")
    thermal = log.state("THERMAL")
    return camera not in (None, State.RUN.value, State.FAIL.value) and thermal != State.RUN.value


def main():
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    socket_path = runtime / "auracam-cardputer.sock"
    config_path = Path.home() / ".config/auracam/cardputer.json"
    store = ConfigStore(config_path)
    if not config_path.exists():
        store.update("refresh_hz", THERMAL_REFRESH_HZ)
        store.update("host_fps_cap", COMPOSITE_FPS)
        store.update("hud_palette", PALETTE)
        store.update("hud_mode", HudMode.TACTICAL.value)
        store.update("scale_x", 1.0)
        store.update("scale_y", 1.0)
    store.update("image_source", "rgb")
    # Leaving mid-calibration must not keep the alignment grid on.
    store.update("grid", False)
    process = subprocess.Popen(
        [sys.executable, "-m", "auracam.daemon", "--socket", str(socket_path), "--config", str(config_path)],
        stdout=sys.stderr,
    )
    client = AuraClient(str(socket_path))
    bridge = CardputerBridge(client)
    try:
        if not boot(process, client, bridge):
            return
        while process.poll() is None:
            keys = _read_keys()
            if keys is None:
                break
            for key in keys:
                try:
                    bridge.action(key)
                except Exception as exc:
                    bridge.say(str(exc), ERROR_HOLD_S)
            emit(bridge.packet())
    except RuntimeError as exc:
        bridge.log.set("START", State.FAIL)
        emit(bridge.boot_packet(bridge.log, str(exc)[:60]))
        time.sleep(ERROR_HOLD_S)
    except BrokenPipeError:
        pass
    finally:
        process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


if __name__ == "__main__":
    main()
