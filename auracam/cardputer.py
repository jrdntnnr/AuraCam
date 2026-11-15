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
from .control import HUD_MODES, HUD_PALETTES, MODES, HudMode
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
EXT_POWER = Path("/sys/class/leds/ext_5v_out/brightness")
I2C_CLOCK = Path("/proc/device-tree/soc/i2c@7e804000/clock-frequency")


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
        self.menu = False
        self.hud = HudMode.TACTICAL.value
        self.palette = PALETTE
        self.message = ""
        self.message_until = 0.0
        self.pixels = bytes(PREVIEW_SIZE[0] * PREVIEW_SIZE[1] * 4)
        self.log = BootLog()
        self._overlay = HudRenderer()

    # Keys 4-8 under the screen; key 4 swaps the capture and menu rows.
    def action(self, key):
        status = self.client.request("status")
        config = status["config"]
        if key == "4":
            self.menu = not self.menu
            return
        if self.menu:
            if key == "5":
                palette = HUD_PALETTES[(HUD_PALETTES.index(config["hud_palette"]) + 1) % len(HUD_PALETTES)]
                self.client.request("set", name="hud_palette", value=palette)
            elif key == "6":
                self.client.request("adjust", name="threshold", delta=-0.5)
            elif key == "7":
                self.client.request("adjust", name="threshold", delta=0.5)
            elif key == "8":
                self.client.request("rotate", source="thermal")
            return
        if key == "5":
            result = self.client.request("snapshot")
            self.say("SAVED " + Path(result["path"]).stem)
        elif key == "6":
            self.client.request("record", action="toggle")
        elif key == "7":
            self.hud = HUD_MODES[(HUD_MODES.index(self.hud) + 1) % len(HUD_MODES)]
        elif key == "8":
            mode = MODES[(MODES.index(config["mode"]) + 1) % len(MODES)]
            self.client.request("mode", mode=mode)

    def say(self, message: str, hold: float = MESSAGE_HOLD_S) -> None:
        self.message = message
        self.message_until = time.monotonic() + hold

    def boot_packet(self, log: BootLog, footer: str) -> bytes:
        return _fields(Kind.BOOT, palette_rgb(self.palette), "", log.text(), "", "", _clean(footer)) + self.pixels

    # One preview request per packet: it carries the JPEG and full status.
    def packet(self):
        try:
            response = self.client.request("preview", width=PREVIEW_SIZE[0], height=PREVIEW_SIZE[1])
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
        if self.hud != HudMode.OFF.value:
            corners = CornerMarks.SHOW if self.hud == HudMode.TACTICAL.value else CornerMarks.HIDE
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
        recording = status["recording"]
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
        uv = status["uv"]
        thermal = status["thermal"]
        source = config["image_source"].upper()
        return [
            f"{source} {uv['fps']:.0f}",
            f"IR  {thermal['fps']:.0f}",
            "",
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
        if self.menu:
            return "BACK|PALETTE|TEMP -|TEMP +|ROTATE"
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
            response = client.request("preview", width=PREVIEW_SIZE[0], height=PREVIEW_SIZE[1])
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
        store.update("scale_x", 1.0)
        store.update("scale_y", 1.0)
    store.update("image_source", "rgb")
    # The screen draws telemetry beside the preview; keep frames clean.
    store.update("hud_mode", HudMode.OFF.value)
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
