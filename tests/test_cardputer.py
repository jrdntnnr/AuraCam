import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from auracam.cardputer import CardputerBridge, TEXT_BYTES, wait_for_engine
from auracam.config import ConfigStore
from auracam.rgb import RgbCamera


class CardputerTest(unittest.TestCase):
    def test_source_persists(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            store = ConfigStore(path)
            store.update("image_source", "rgb")
            self.assertEqual(ConfigStore(path).get().image_source, "rgb")
            with self.assertRaises(ValueError):
                store.update("image_source", "invalid")

    def test_hud_key_cycles_on_capture_screen(self):
        client = MagicMock()
        client.request.return_value = {"config": {"hud_mode": "off"}, "recording": {"active": True}}
        CardputerBridge(client).action("7")
        client.request.assert_called_with("set", name="hud_mode", value="minimal")

    def test_bottom_keys_change_context(self):
        client = MagicMock()
        client.request.return_value = {"config": {"hud_mode": "off", "hud_palette": "green"}}
        bridge = CardputerBridge(client)
        bridge.action("4")
        bridge.action("5")
        client.request.assert_called_with("set", name="hud_palette", value="amber")
        bridge.action("4")
        bridge.action("6")
        client.request.assert_called_with("record", action="toggle")

    def test_rgb_start_failure_closes(self):
        camera = MagicMock()
        camera.start.side_effect = RuntimeError("unavailable")
        module = MagicMock()
        module.Picamera2.return_value = camera
        with patch.dict("sys.modules", {"picamera2": module, "libcamera": MagicMock()}):
            with self.assertRaises(RuntimeError):
                RgbCamera()
        camera.close.assert_called_once()

    def test_rgb_flips_upside_down_sensor(self):
        camera = MagicMock()
        camera.camera_properties = {"Rotation": 180}
        module = MagicMock()
        module.Picamera2.return_value = camera
        libcamera = MagicMock()
        with patch.dict("sys.modules", {"picamera2": module, "libcamera": libcamera}):
            RgbCamera()
        libcamera.Transform.assert_called_once_with(hflip=True, vflip=True)

    def test_packet_survives_missing_engine(self):
        client = MagicMock()
        client.request.side_effect = FileNotFoundError("no socket")
        packet = CardputerBridge(client).packet()
        self.assertIn(b"ENGINE OFFLINE", packet[:TEXT_BYTES])

    def test_engine_wait_reports_exit(self):
        process = MagicMock()
        process.poll.return_value = 1
        client = MagicMock()
        with patch("auracam.cardputer.emit"):
            with self.assertRaisesRegex(RuntimeError, "exited"):
                wait_for_engine(process, client, CardputerBridge(client))

    def test_engine_wait_returns_once_reachable(self):
        process = MagicMock()
        process.poll.return_value = None
        client = MagicMock()
        client.request.side_effect = [OSError(), {"ok": True}]
        with patch("auracam.cardputer.emit") as emitted, patch("auracam.cardputer.time.sleep"):
            wait_for_engine(process, client, CardputerBridge(client))
        self.assertEqual(emitted.call_count, 1)

    def test_packet_before_first_thermal_frame(self):
        client = MagicMock()
        client.request.return_value = {
            "jpeg": "",
            "status": {
                "config": {"image_source": "rgb", "mode": "clean", "threshold": 26.0},
                "thermal": {"connected": True, "fps": 0.0, "min": None, "max": None, "error": None},
                "uv": {"fps": 0.0, "error": None},
                "recording": {"active": False, "seconds": 0.0},
            },
        }
        packet = CardputerBridge(client).packet()
        self.assertIn(b"THERMAL WARMUP", packet[:TEXT_BYTES])
