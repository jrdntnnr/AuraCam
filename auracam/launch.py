"""Cardputer entry point: start the capture engine, then the bridge.

Importing cv2 takes ~12 s on a CM0: Debian's OpenCV links ~380 shared
libraries. The engine and the bridge both need it, so the engine starts
first and the two loads run on separate cores instead of back to back.

    frontend ─▶ launch ──spawn──▶ daemon   (imports cv2, opens sensors)
                  └────import───▶ cardputer (imports cv2, draws boot log)

This module must stay free of numpy and cv2 imports.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .config import ConfigStore
from .control import CameraFov, HudMode

# MLX90640 subpages/s. A read takes ~37 ms at 400 kHz (scripts/set_i2c_baud.sh),
# longer than a 32 Hz frame: the driver then fails with -8 every few seconds.
THERMAL_REFRESH_HZ = 16.0
# Composite cap; a CM0 holds ~23 fps.
COMPOSITE_FPS = 24
# The Pi build's yellow-orange HUD.
PALETTE = "amber"

# Fresh installs start wide with the Cardputer's measured thermal alignment.
FIRST_RUN = {
    "refresh_hz": THERMAL_REFRESH_HZ,
    "host_fps_cap": COMPOSITE_FPS,
    "hud_palette": PALETTE,
    "hud_mode": HudMode.TACTICAL.value,
    "camera_fov": CameraFov.WIDE.value,
    "offset_x": 64,
    "offset_y": -60,
    "scale_x": 1.6941,
    "scale_y": 1.6941,
    "thermal_rotation": 180,
    "thermal_mirror_h": True,
}


def start_engine() -> tuple[subprocess.Popen, Path]:
    """Prepare the config and spawn the daemon; returns it and its socket."""
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
    socket_path = runtime / "auracam-cardputer.sock"
    config_path = Path.home() / ".config/auracam/cardputer.json"
    store = ConfigStore(config_path)
    if not config_path.exists():
        for name, value in FIRST_RUN.items():
            store.update(name, value)
    store.update("image_source", "rgb")
    # Leaving mid-calibration must not keep the alignment grid on.
    store.update("grid", False)

    process = subprocess.Popen(
        [sys.executable, "-m", "auracam.daemon", "--socket", str(socket_path), "--config", str(config_path)],
        stdout=sys.stderr,
    )
    return process, socket_path


def main():
    process, socket_path = start_engine()

    # Heavy imports start only now, while the engine loads its own.
    from .cardputer import run

    run(process, socket_path)


if __name__ == "__main__":
    main()
