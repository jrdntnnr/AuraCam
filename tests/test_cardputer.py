import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from auracam.cardputer import CardputerBridge
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

    def test_recording_blocks_switch(self):
        client = MagicMock()
        client.request.return_value = {
            "config": {"image_source": "rgb"},
            "recording": {"active": True},
        }
        with self.assertRaisesRegex(RuntimeError, "Stop recording"):
            CardputerBridge(client).action("7")
        client.request.assert_called_once_with("status")

    def test_bottom_keys_change_context(self):
        client = MagicMock()
        client.request.return_value = {"config": {"hud_mode": "off"}}
        bridge = CardputerBridge(client)
        bridge.action("4")
        bridge.action("5")
        client.request.assert_called_with("set", name="hud_mode", value="minimal")
        bridge.action("4")
        bridge.action("6")
        client.request.assert_called_with("record", action="toggle")

    def test_rgb_start_failure_closes(self):
        camera = MagicMock()
        camera.start.side_effect = RuntimeError("unavailable")
        module = MagicMock()
        module.Picamera2.return_value = camera
        with patch.dict("sys.modules", {"picamera2": module}):
            with self.assertRaises(RuntimeError):
                RgbCamera()
        camera.close.assert_called_once()
