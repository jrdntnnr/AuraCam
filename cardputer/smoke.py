import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from auracam.cli import AuraClient
from auracam.config import ConfigStore


def main():
    with tempfile.TemporaryDirectory(prefix="aura-smoke-") as directory:
        socket = str(Path(directory) / "control.sock")
        config = str(Path(directory) / "config.json")
        store = ConfigStore(config)
        store.update("image_source", "rgb")
        store.update("hud_mode", "tactical")
        output = str(Path.home() / "Pictures/auracam/smoke")
        process = subprocess.Popen([
            sys.executable, "-m", "auracam.daemon", "--socket", socket,
            "--config", config, "--output", output,
        ])
        client = AuraClient(socket)
        try:
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError("Daemon exited")
                if Path(socket).exists():
                    status = client.request("status")
                    if status["frame_sequence"] >= 5:
                        break
                time.sleep(0.5)
            else:
                raise RuntimeError("No live RGB frames")
            print(json.dumps(status), flush=True)
            image = client.request("snapshot")["path"]
            assert os.path.getsize(image) > 0
            client.request("record", action="start")
            time.sleep(5)
            video = client.request("record", action="stop")["path"]
            assert os.path.getsize(video) > 0
            subprocess.run([
                "ffprobe", "-v", "error", "-show_entries",
                "stream=codec_name,width,height,nb_frames:format=duration",
                "-of", "json", video,
            ], check=True)
            print(f"Snapshot: {image}\nVideo: {video}", flush=True)
        finally:
            process.terminate()
            process.wait(timeout=30)


if __name__ == "__main__":
    main()
