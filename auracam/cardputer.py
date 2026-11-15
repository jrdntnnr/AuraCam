from __future__ import annotations

import base64
import os
import select
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

from .cli import AuraClient
from .config import ConfigStore
from .control import HUD_MODES, HUD_PALETTES, MODES

PREVIEW_SIZE = (192, 144)
TEXT_BYTES = 512
ENGINE_START_TIMEOUT_S = 90.0
ENGINE_POLL_S = 0.25
ERROR_HOLD_S = 4.0
EXIT_KEY = "q"
# MLX90640 at 16 Hz needs the I2C bus at 400 kHz (scripts/set_i2c_baud.sh).
THERMAL_REFRESH_HZ = 16.0
# Composite at the rate the 320x170 panel can show; the camera still runs at 30.
COMPOSITE_FPS = 15


class CardputerBridge:
    def __init__(self, client):
        self.client = client
        self.menu = False
        self.message = "Connecting"
        self.message_until = 0.0
        self.pixels = bytes(PREVIEW_SIZE[0] * PREVIEW_SIZE[1] * 4)

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
            self.message = "Saved " + Path(result["path"]).name
            self.message_until = time.monotonic() + 3
        elif key == "6":
            self.client.request("record", action="toggle")
        elif key == "7":
            mode = HUD_MODES[(HUD_MODES.index(config["hud_mode"]) + 1) % len(HUD_MODES)]
            self.client.request("set", name="hud_mode", value=mode)
        elif key == "8":
            mode = MODES[(MODES.index(config["mode"]) + 1) % len(MODES)]
            self.client.request("mode", mode=mode)

    def text_packet(self, lines, actions=""):
        text = ("\n".join(lines) + "\t" + actions).encode("ascii", "replace")[:TEXT_BYTES - 1]
        return text.ljust(TEXT_BYTES, b"\0") + self.pixels

    def packet(self):
        try:
            response = self.client.request("preview", width=PREVIEW_SIZE[0], height=PREVIEW_SIZE[1])
        except OSError as exc:
            return self.text_packet(["CAPTURE ENGINE OFFLINE", str(exc)[:60]])
        status = response["status"]
        if response["jpeg"]:
            data = np.frombuffer(base64.b64decode(response["jpeg"]), np.uint8)
            frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
            if frame is not None:
                if (frame.shape[1], frame.shape[0]) != PREVIEW_SIZE:
                    frame = cv2.resize(frame, PREVIEW_SIZE, interpolation=cv2.INTER_AREA)
                self.pixels = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA).tobytes()
        config = status["config"]
        thermal = status["thermal"]
        recording = status["recording"]
        if not thermal["connected"]:
            temperature = "THERMAL OFFLINE"
        elif thermal["min"] is None:
            temperature = "THERMAL WARMUP"
        else:
            temperature = f"{thermal['min']:.1f}..{thermal['max']:.1f} C"
        message = self.message if time.monotonic() < self.message_until else status["uv"]["error"] or thermal["error"] or ""
        lines = [
            f"{config['image_source'].upper()} {status['uv']['fps']:.1f} FPS",
            f"IR {thermal['fps']:.1f} FPS",
            temperature,
            config["mode"].upper(),
            f"THR {config['threshold']:.1f} C",
            f"REC {recording['seconds']:.0f}s" if recording["active"] else "READY",
            str(message)[:100],
        ]
        actions = "BACK|PALETTE|TEMP -|TEMP +|ROTATE" if self.menu else "MENU|SNAP|STOP|HUD|MODE"
        if not self.menu and not recording["active"]:
            actions = "MENU|SNAP|RECORD|HUD|MODE"
        return self.text_packet(lines, actions)


def emit(packet):
    sys.stdout.buffer.write(packet)
    sys.stdout.buffer.flush()


def wait_for_engine(process, client, bridge):
    started = time.monotonic()
    while time.monotonic() - started < ENGINE_START_TIMEOUT_S:
        if process.poll() is not None:
            raise RuntimeError("Capture engine exited during startup")
        try:
            client.request("status")
            return
        except OSError:
            pass
        elapsed = int(time.monotonic() - started)
        emit(bridge.text_packet(["INITIALIZING CAPTURE ENGINE", f"{elapsed:02d}s"]))
        time.sleep(ENGINE_POLL_S)
    raise RuntimeError("Capture engine did not start")


def main():
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    socket_path = runtime / "auracam-cardputer.sock"
    config_path = Path.home() / ".config/auracam/cardputer.json"
    store = ConfigStore(config_path)
    if not config_path.exists():
        store.update("refresh_hz", THERMAL_REFRESH_HZ)
        store.update("host_fps_cap", COMPOSITE_FPS)
        store.update("scale_x", 1.0)
        store.update("scale_y", 1.0)
    store.update("image_source", "rgb")
    process = subprocess.Popen(
        [sys.executable, "-m", "auracam.daemon", "--socket", str(socket_path), "--config", str(config_path)],
        stdout=sys.stderr,
    )
    client = AuraClient(str(socket_path))
    bridge = CardputerBridge(client)
    try:
        wait_for_engine(process, client, bridge)
        while process.poll() is None:
            ready, _, _ = select.select([sys.stdin], [], [], 0.1)
            if ready:
                keys = os.read(sys.stdin.fileno(), 32).decode("ascii")
                if not keys or EXIT_KEY in keys:
                    break
                for key in keys:
                    try:
                        bridge.action(key)
                    except Exception as exc:
                        bridge.message = str(exc)
                        bridge.message_until = time.monotonic() + ERROR_HOLD_S
            emit(bridge.packet())
    except RuntimeError as exc:
        emit(bridge.text_packet(["STARTUP FAILED", str(exc)[:60]]))
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
