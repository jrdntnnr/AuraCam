import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import cv2
import numpy as np

from auracam.cardputer import PREVIEW_SIZE, TEXT_BYTES, CardputerBridge, Screen, boot
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

    def test_hud_key_sets_capture_hud(self):
        client = MagicMock()
        client.request.return_value = {"config": {"hud_mode": "off"}, "recording": {"active": True}}
        CardputerBridge(client).action("7")
        client.request.assert_called_with("set", name="hud_mode", value="minimal")

    def test_preview_asks_for_clean_layer(self):
        client = MagicMock()
        client.request.return_value = preview(fps=30.0, jpeg=tiny_jpeg())
        CardputerBridge(client).packet()
        client.request.assert_called_with("preview", width=192, height=144, layer="clean")

    def test_bottom_keys_change_context(self):
        client = MagicMock()
        client.request.return_value = {"config": {"hud_mode": "off", "camera_look": "natural"}}
        bridge = CardputerBridge(client)
        bridge.action("4")
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
                RgbCamera("natural", "crop")
        camera.close.assert_called_once()

    def test_rgb_flips_upside_down_sensor(self):
        camera = MagicMock()
        camera.camera_properties = {"Rotation": 180}
        module = MagicMock()
        module.Picamera2.return_value = camera
        libcamera = MagicMock()
        with patch.dict("sys.modules", {"picamera2": module, "libcamera": libcamera}):
            RgbCamera("natural", "crop")
        libcamera.Transform.assert_called_once_with(hflip=True, vflip=True)

    def test_rgb_look_sets_isp_controls(self):
        camera = rgb_camera_mock()
        with patch.dict("sys.modules", {"picamera2": camera.module, "libcamera": MagicMock()}):
            rgb = RgbCamera("mono", "crop")
            rgb.set_look("hicon")
        first = camera.instance.create_video_configuration.call_args.kwargs["controls"]
        self.assertEqual(first["Saturation"], 0.0)
        controls = camera.instance.set_controls.call_args.args[0]
        self.assertGreater(controls["Contrast"], 1.0)
        self.assertEqual(controls["Saturation"], 1.0)
        self.assertEqual(rgb.look, "hicon")

    def test_rgb_wide_uses_full_sensor_and_shrinks_overlay(self):
        camera = rgb_camera_mock(crop=(0, 2, 3280, 2460))
        with patch.dict("sys.modules", {"picamera2": camera.module, "libcamera": MagicMock()}):
            rgb = RgbCamera("natural", "wide")
        sensor = camera.instance.create_video_configuration.call_args.kwargs["sensor"]
        self.assertEqual(sensor["output_size"], (1640, 1232))
        transform = rgb.overlay_transform((480, 640))
        self.assertAlmostEqual(transform.scale_x, 1280 / 3280)
        self.assertAlmostEqual(transform.scale_y, 960 / 2460)
        self.assertEqual((transform.shift_x, transform.shift_y), (0, 0))

    def test_rgb_crop_overlay_is_identity(self):
        camera = rgb_camera_mock(crop=(1000, 752, 1280, 960))
        with patch.dict("sys.modules", {"picamera2": camera.module, "libcamera": MagicMock()}):
            rgb = RgbCamera("natural", "crop")
        transform = rgb.overlay_transform((480, 640))
        self.assertEqual((transform.scale_x, transform.scale_y, transform.shift_x, transform.shift_y), (1.0, 1.0, 0, 0))

    def test_calibration_moves_zooms_and_saves(self):
        client = FakeClient(offset_x=0, offset_y=0, scale_x=1.0, scale_y=0.9, grid=False)
        bridge = CardputerBridge(client)
        for key in "47":
            bridge.action(key)
        self.assertTrue(client.config["grid"])
        bridge.action("R")
        self.assertEqual(client.config["offset_x"], 2)
        bridge.action("7")
        bridge.action("U")
        self.assertEqual(client.config["offset_y"], -10)
        bridge.action("6")
        self.assertAlmostEqual(client.config["scale_x"], 1.05)
        self.assertAlmostEqual(client.config["scale_y"], 0.945)
        bridge.action("4")
        self.assertFalse(client.config["grid"])
        self.assertEqual((client.config["offset_x"], client.config["offset_y"]), (2, -10))
        self.assertEqual(bridge.screen, Screen.CAPTURE)

    def test_calibration_cancel_restores(self):
        client = FakeClient(offset_x=5, offset_y=-3, scale_x=1.0, scale_y=1.0, grid=False)
        bridge = CardputerBridge(client)
        for key in "47LLD5":
            bridge.action(key)
        self.assertNotEqual(client.config["offset_x"], 5)
        bridge.action("8")
        self.assertEqual(
            {k: client.config[k] for k in ("offset_x", "offset_y", "scale_x", "scale_y", "grid")},
            {"offset_x": 5, "offset_y": -3, "scale_x": 1.0, "scale_y": 1.0, "grid": False},
        )

    def test_threshold_screen_steps(self):
        client = FakeClient(threshold=26.0)
        bridge = CardputerBridge(client)
        for key in "485":
            bridge.action(key)
        self.assertEqual(client.config["threshold"], 25.0)
        bridge.action("4")
        self.assertEqual(bridge.screen, Screen.CAPTURE)

    def test_menu_keys_cycle_look_and_fov(self):
        client = MagicMock()
        client.request.return_value = {"config": {"camera_look": "natural", "camera_fov": "crop"}}
        bridge = CardputerBridge(client)
        bridge.action("4")
        bridge.action("5")
        client.request.assert_called_with("set", name="camera_look", value="mono")
        bridge.action("6")
        client.request.assert_called_with("set", name="camera_fov", value="wide")

    def test_packet_survives_missing_engine(self):
        client = MagicMock()
        client.request.side_effect = FileNotFoundError("no socket")
        packet = CardputerBridge(client).packet()
        self.assertIn(b"ENGINE OFFLINE", packet[:TEXT_BYTES])

    def test_boot_reports_engine_exit(self):
        process = MagicMock()
        process.poll.return_value = 1
        client = MagicMock()
        bridge = CardputerBridge(client)
        with patch("auracam.cardputer.emit"), patch("auracam.cardputer._read_keys", return_value=""):
            with self.assertRaisesRegex(RuntimeError, "exited"):
                boot(process, client, bridge)
        self.assertEqual(bridge.log.state("ENGINE"), "FAIL")

    def test_boot_steps_until_first_frame(self):
        process = MagicMock()
        process.poll.return_value = None
        client = MagicMock()
        client.request.side_effect = [OSError(), preview(fps=0.0, jpeg=""), preview(fps=30.0, jpeg=tiny_jpeg())]
        bridge = CardputerBridge(client)
        with patch("auracam.cardputer.emit") as emitted, \
                patch("auracam.cardputer._read_keys", return_value=""), \
                patch("auracam.cardputer.BOOT_DONE_HOLD_S", 0.0):
            self.assertTrue(boot(process, client, bridge))
        first = emitted.call_args_list[0].args[0][:TEXT_BYTES]
        last = emitted.call_args_list[-1].args[0][:TEXT_BYTES]
        self.assertTrue(first.startswith(b"BOOT\t"))
        self.assertIn(b"ENGINE|RUN", first)
        self.assertIn(b"ENGINE|OK", last)
        self.assertIn(b"CAMERA|30FPS", last)
        self.assertIn(b"THERMAL|16HZ", last)
        self.assertIn(b"FRAME|OK", last)

    def test_boot_stops_when_frontend_quits(self):
        client = MagicMock()
        with patch("auracam.cardputer.emit"), patch("auracam.cardputer._read_keys", return_value=None):
            self.assertFalse(boot(MagicMock(), client, CardputerBridge(client)))

    def test_live_packet_fields(self):
        client = MagicMock()
        client.request.return_value = preview(fps=30.0, jpeg=tiny_jpeg())
        packet = CardputerBridge(client).packet()
        kind, color, header, left, right, actions, _ = packet[:TEXT_BYTES].rstrip(b"\0").decode().split("\t")
        self.assertEqual((kind, color, header), ("LIVE", "84FF48", ""))
        self.assertIn("RGB 30", left.split("\n"))
        self.assertIn("MONO WIDE", left.split("\n"))
        self.assertEqual(right.split("\n"), ["P 24.0C", "H 30.0C", "L 20.0C"])
        self.assertEqual(actions, "MENU|SNAP|RECORD|HUD|MODE")
        self.assertEqual(len(packet), TEXT_BYTES + PREVIEW_SIZE[0] * PREVIEW_SIZE[1] * 4)

    def test_header_shows_saving(self):
        client = MagicMock()
        response = preview(fps=30.0, jpeg=tiny_jpeg())
        response["status"]["recording"]["saving"] = True
        client.request.return_value = response
        packet = CardputerBridge(client).packet()
        self.assertEqual(packet[:TEXT_BYTES].split(b"\t")[2], b"SAVING")

    def test_packet_before_first_thermal_frame(self):
        client = MagicMock()
        response = preview(fps=0.0, jpeg="")
        response["status"]["thermal"].update({"min": None, "max": None, "markers": []})
        client.request.return_value = response
        packet = CardputerBridge(client).packet()
        self.assertIn(b"WARMUP", packet[:TEXT_BYTES])


class FakeClient:
    """Control socket stand-in that applies set/adjust to a config dict."""

    def __init__(self, **config):
        self.config = config

    def request(self, command, **payload):
        if command == "set":
            self.config[payload["name"]] = payload["value"]
        elif command == "adjust":
            self.config[payload["name"]] += payload["delta"]
        return {"config": self.config}


def rgb_camera_mock(crop=(1000, 752, 1280, 960)):
    instance = MagicMock()
    instance.camera_properties = {"Rotation": 0}
    instance.capture_metadata.return_value = {"ScalerCrop": crop}
    module = MagicMock()
    module.Picamera2.return_value = instance
    return SimpleNamespace(instance=instance, module=module)


def tiny_jpeg():
    ok, encoded = cv2.imencode(".jpg", np.zeros((144, 192, 3), np.uint8))
    return base64.b64encode(encoded.tobytes()).decode()


def preview(fps, jpeg):
    return {
        "jpeg": jpeg,
        "status": {
            "config": {"image_source": "rgb", "mode": "clean", "threshold": 26.0, "hud_palette": "green",
                       "camera_look": "mono", "camera_fov": "wide"},
            "uv": {"connected": True, "fps": fps, "error": None, "relative": 0.4},
            "thermal": {
                "connected": True, "fps": 15.7, "refresh_hz": 16.0, "min": 20.0, "max": 30.0,
                "ambient": 22.0, "errors": 0, "error": None,
                "markers": [
                    {"label": "P", "x": 320, "y": 240, "value": 24.0},
                    {"label": "H", "x": 100, "y": 50, "value": 30.0},
                    {"label": "L", "x": 600, "y": 400, "value": 20.0},
                ],
            },
            "output": {"fps": 15.0, "width": 640, "height": 480},
            "recording": {"active": False, "seconds": 0.0},
        },
    }
