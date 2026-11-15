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
from .control import HUD_MODES, MODES

PREVIEW_SIZE = (192, 144)
TEXT_BYTES = 512


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
                mode = HUD_MODES[(HUD_MODES.index(config["hud_mode"]) + 1) % len(HUD_MODES)]
                self.client.request("set", name="hud_mode", value=mode)
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
            if status["recording"]["active"]:
                raise RuntimeError("Stop recording before switching source")
            source = "uv" if config["image_source"] == "rgb" else "rgb"
            self.client.request("set", name="image_source", value=source)
        elif key == "8":
            mode = MODES[(MODES.index(config["mode"]) + 1) % len(MODES)]
            self.client.request("mode", mode=mode)

    def packet(self):
        response = self.client.request("preview")
        status = response["status"]
        if response["jpeg"]:
            data = np.frombuffer(base64.b64decode(response["jpeg"]), np.uint8)
            frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
            if frame is not None:
                frame = cv2.resize(frame, PREVIEW_SIZE, interpolation=cv2.INTER_AREA)
                self.pixels = cv2.cvtColor(frame, cv2.COLOR_BGR2BGRA).tobytes()
        config = status["config"]
        thermal = status["thermal"]
        recording = status["recording"]
        temperature = f"{thermal['min']:.1f}..{thermal['max']:.1f} C" if thermal["connected"] else "THERMAL OFFLINE"
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
        actions = "Back|HUD|Temp -|Temp +|Rotate" if self.menu else "Menu|Snap|Stop|Source|Mode"
        if not self.menu and not recording["active"]:
            actions = "Menu|Snap|Record|Source|Mode"
        text = ("\n".join(lines) + "\t" + actions).encode("ascii", "replace")[:TEXT_BYTES - 1]
        return text.ljust(TEXT_BYTES, b"\0") + self.pixels


def main():
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    socket_path = runtime / "auracam-cardputer.sock"
    config_path = Path.home() / ".config/auracam/cardputer.json"
    if not config_path.exists():
        store = ConfigStore(config_path)
        store.update("image_source", "rgb")
        store.update("refresh_hz", 8.0)
    process = subprocess.Popen(
        [sys.executable, "-m", "auracam.daemon", "--socket", str(socket_path), "--config", str(config_path)],
        stdout=sys.stderr,
    )
    client = AuraClient(str(socket_path))
    bridge = CardputerBridge(client)
    try:
        for _ in range(100):
            if process.poll() is not None:
                raise RuntimeError("Capture engine exited during startup")
            try:
                client.request("status")
                break
            except OSError:
                time.sleep(0.1)
        while process.poll() is None:
            ready, _, _ = select.select([sys.stdin], [], [], 0.1)
            if ready:
                keys = os.read(sys.stdin.fileno(), 32).decode("ascii")
                if not keys or "q" in keys:
                    break
                for key in keys:
                    try:
                        bridge.action(key)
                    except Exception as exc:
                        bridge.message = str(exc)
                        bridge.message_until = time.monotonic() + 4
            sys.stdout.buffer.write(bridge.packet())
            sys.stdout.buffer.flush()
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
