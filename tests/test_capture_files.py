import queue
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import cv2
import numpy as np

from auracam.compositor import AuraCompositor
from auracam.config import AuraConfig
from auracam.frames import OverlayTransform
from auracam.daemon import FrameLayer, overlay_config, _RECORD_END, AuraDaemon
from auracam.frames import HudTelemetry


class FakeStdin:
    def __init__(self):
        self.data = bytearray()
        self.closed = False

    def write(self, data):
        self.data.extend(data)
        return len(data)

    def close(self):
        self.closed = True


class FakeWriter:
    def __init__(self):
        self.released = False
        self.stdin = FakeStdin()

    def poll(self):
        return None

    def wait(self, timeout=None):
        self.released = True
        return 0

    def kill(self):
        pass


class SlowStdin(FakeStdin):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def write(self, data):
        self.started.set()
        self.release.wait(timeout=2)
        return super().write(data)


class SlowWriter(FakeWriter):
    def __init__(self):
        super().__init__()
        self.stdin = SlowStdin()


class ExitedWriter(FakeWriter):
    def poll(self):
        return 1


def capture_daemon(output_dir):
    daemon = AuraDaemon.__new__(AuraDaemon)
    daemon.output_dir = Path(output_dir)
    daemon._frame_lock = threading.Lock()
    daemon._jpeg_lock = threading.Lock()
    daemon._jpeg_size = None
    daemon._save_thread = None
    daemon._record_started = 0.0
    daemon._record_path = None
    daemon._record_writer = None
    daemon._jpeg_layer = FrameLayer.HUD
    daemon._latest_clean = None
    daemon._record_lock = threading.Lock()
    daemon._record_error = None
    daemon._record_frames = 0
    daemon._record_queue = None
    daemon._record_thread = None
    daemon._record_accepting = False
    daemon._record_dropped = 0
    daemon._latest_jpeg = b"\xff\xd8frame-data\xff\xd9"
    daemon._latest_frame = None
    daemon._frame_sequence = 0
    daemon._jpeg_sequence = 0
    daemon.last_snapshot = None
    return daemon


class CaptureFileTest(unittest.TestCase):
    def test_snapshot_is_published_only_after_full_write(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon = capture_daemon(directory)
            path = Path(daemon.snapshot())

            self.assertEqual(path.read_bytes(), daemon._latest_jpeg)
            self.assertFalse((Path(directory) / ".inprogress" / path.name).exists())

    def test_empty_snapshot_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon = capture_daemon(directory)
            daemon._latest_jpeg = b""

            with self.assertRaisesRegex(RuntimeError, "No composited frame"):
                daemon.snapshot()

    def test_preview_jpeg_is_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon = capture_daemon(directory)
            daemon._latest_jpeg = None
            daemon._jpeg_sequence = -1
            daemon._latest_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            daemon.config_store = mock.Mock()
            daemon.config_store.get.return_value = AuraConfig(jpeg_quality=88)

            first, first_sequence = daemon._frame_jpeg()
            second, second_sequence = daemon._frame_jpeg()

            self.assertIs(first, second)
            self.assertEqual(first_sequence, second_sequence)
            self.assertGreater(len(first), 1000)

    def test_preview_jpeg_is_encoded_at_requested_size(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon = capture_daemon(directory)
            daemon._latest_frame = np.zeros((480, 640, 3), dtype=np.uint8)
            daemon.config_store = mock.Mock()
            daemon.config_store.get.return_value = AuraConfig(jpeg_quality=88)

            small, _ = daemon._frame_jpeg((192, 144))
            full, _ = daemon._frame_jpeg()

            decoded = cv2.imdecode(np.frombuffer(small, np.uint8), cv2.IMREAD_COLOR)
            self.assertEqual(decoded.shape[:2], (144, 192))
            self.assertGreater(len(full), len(small))

    def test_preview_layers(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon = capture_daemon(directory)
            daemon._latest_jpeg = None
            daemon._jpeg_sequence = -1
            daemon._latest_frame = np.full((480, 640, 3), 255, dtype=np.uint8)
            daemon._latest_clean = np.zeros((480, 640, 3), dtype=np.uint8)
            daemon.config_store = mock.Mock()
            daemon.config_store.get.return_value = AuraConfig(jpeg_quality=88)

            clean, _ = daemon._frame_jpeg((192, 144), FrameLayer.CLEAN)
            hud, _ = daemon._frame_jpeg((192, 144), FrameLayer.HUD)
            snapshot, _ = daemon._frame_jpeg()

            def mean(jpeg):
                return cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR).mean()

            self.assertLess(mean(clean), 10)
            self.assertGreater(mean(hud), 245)
            self.assertGreater(mean(snapshot), 245)

    def test_overlay_config_follows_camera_crop(self):
        config = AuraConfig(scale_x=1.0, scale_y=0.9, offset_x=10, offset_y=-20)
        wide = OverlayTransform(scale_x=0.4, scale_y=0.5, shift_x=3, shift_y=-1)
        adjusted = overlay_config(config, wide)
        self.assertAlmostEqual(adjusted.scale_x, 0.4)
        self.assertAlmostEqual(adjusted.scale_y, 0.45)
        self.assertEqual((adjusted.offset_x, adjusted.offset_y), (7, -11))
        self.assertIs(overlay_config(config, OverlayTransform()), config)

    def test_client_hangup_does_not_kill_server(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon = capture_daemon(directory)
            daemon._handle = mock.Mock(return_value={"ok": True, "pad": "x" * 500_000})
            server_side, client_side = socket.socketpair()
            client_side.sendall(b'{"command":"status"}\n')
            client_side.close()
            with server_side:
                daemon._serve_connection(server_side)
            daemon._handle.assert_called_once()

    def test_record_stop_returns_while_saving(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon = capture_daemon(directory)
            daemon._record_writer = mock.Mock()
            daemon._record_path = "/tmp/aura_test.mp4"
            release = threading.Event()
            daemon._stop_recording = mock.Mock(side_effect=lambda: release.wait(5) and "/tmp/aura_test.mp4")

            response = daemon._handle({"command": "record", "action": "stop"})

            self.assertTrue(response["saving"])
            self.assertTrue(daemon.recording_status()["saving"])
            with self.assertRaisesRegex(RuntimeError, "Saving"):
                daemon._handle({"command": "record", "action": "toggle"})
            release.set()
            daemon._save_thread.join(5)
            self.assertFalse(daemon.recording_status()["saving"])

    def test_recording_is_published_after_writer_release(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon = capture_daemon(directory)
            final = Path(directory) / "aura_test.mp4"
            pending = daemon._pending_dir() / final.name
            pending.write_bytes(b"video-data")
            writer = FakeWriter()
            daemon._record_writer = writer
            daemon._record_path = str(final)
            daemon._record_temp_path = str(pending)
            daemon._record_frames = 3
            daemon._record_started = time.monotonic() - 0.1
            daemon._record_nominal_fps = 30.0
            daemon._record_size = (640, 480)

            self.assertEqual(daemon._stop_recording(), str(final))
            self.assertTrue(writer.released)
            self.assertTrue(writer.stdin.closed)
            self.assertEqual(final.read_bytes(), b"video-data")
            self.assertFalse(pending.exists())

    def test_zero_byte_recording_is_not_published(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon = capture_daemon(directory)
            final = Path(directory) / "aura_test.mp4"
            pending = daemon._pending_dir() / final.name
            pending.touch()
            daemon._record_writer = FakeWriter()
            daemon._record_path = str(final)
            daemon._record_temp_path = str(pending)
            daemon._record_frames = 3
            daemon._record_started = time.monotonic() - 0.1
            daemon._record_nominal_fps = 30.0
            daemon._record_size = (640, 480)

            with self.assertRaisesRegex(RuntimeError, "no video frames"):
                daemon._stop_recording()
            self.assertFalse(final.exists())
            self.assertFalse(pending.exists())

    def test_recording_keeps_hud(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon = capture_daemon(directory)
            writer = FakeWriter()
            daemon._record_writer = writer
            daemon._record_size = (640, 480)
            daemon._record_frames = 0
            daemon._record_queue = queue.Queue()
            daemon._record_accepting = True
            daemon._record_thread = threading.Thread(
                target=daemon._record_loop,
                args=(writer, daemon._record_queue),
            )
            daemon._record_thread.start()
            base = np.zeros((480, 640, 3), dtype=np.uint8)
            data = HudTelemetry(9.0, 31.8, 8.9, 0.5, 3.0, 27, 0)
            frame = AuraCompositor().compose(
                base, None, AuraConfig(hud_mode="tactical"), data
            )
            daemon._write_recording(frame)
            daemon._record_queue.put(_RECORD_END)
            daemon._record_thread.join(timeout=2)

            self.assertEqual(bytes(writer.stdin.data), frame.tobytes())
            self.assertEqual(daemon._record_frames, 1)
            recorded = np.frombuffer(writer.stdin.data, dtype=np.uint8).reshape(
                frame.shape
            )
            self.assertGreater(np.count_nonzero(recorded), 100)

    def test_exited_encoder_is_not_reported_as_active(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon = capture_daemon(directory)
            daemon._record_writer = ExitedWriter()
            daemon._record_path = str(Path(directory) / "failed.mp4")
            daemon._record_frames = 0
            daemon._record_started = time.monotonic()

            status = daemon.recording_status()

            self.assertFalse(status["active"])
            self.assertIn("exited", status["error"])

    def test_encoder_cannot_block_capture(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon = capture_daemon(directory)
            writer = SlowWriter()
            daemon._record_writer = writer
            daemon._record_size = (640, 480)
            daemon._record_queue = queue.Queue()
            daemon._record_accepting = True
            daemon._record_thread = threading.Thread(
                target=daemon._record_loop,
                args=(writer, daemon._record_queue),
            )
            daemon._record_thread.start()
            frame = np.zeros((480, 640, 3), dtype=np.uint8)

            first = np.zeros_like(frame)
            second = np.ones_like(frame)
            daemon._write_recording(first)
            self.assertTrue(writer.stdin.started.wait(timeout=1))
            started = time.monotonic()
            daemon._write_recording(second)
            elapsed = time.monotonic() - started

            writer.stdin.release.set()
            daemon._record_queue.put(_RECORD_END)
            daemon._record_thread.join(timeout=2)
            self.assertLess(elapsed, 0.05)
            self.assertEqual(
                bytes(writer.stdin.data), first.tobytes() + second.tobytes()
            )

    def test_exited_encoder_records_an_error(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon = capture_daemon(directory)
            daemon._record_writer = ExitedWriter()
            daemon._record_size = (640, 480)
            daemon._record_frames = 0
            daemon._record_queue = queue.Queue()
            daemon._record_accepting = True
            daemon._record_thread = threading.Thread(
                target=daemon._record_loop,
                args=(daemon._record_writer, daemon._record_queue),
            )
            daemon._record_thread.start()
            frame = __import__("numpy").zeros((480, 640, 3), dtype="uint8")

            daemon._write_recording(frame)
            daemon._record_thread.join(timeout=2)

            self.assertEqual(daemon._record_frames, 0)
            self.assertIn("exited", daemon._record_error)

    def test_recording_timestamps_are_scaled_to_elapsed_time(self):
        with tempfile.TemporaryDirectory() as directory:
            daemon = capture_daemon(directory)
            source = Path(directory) / "source.mp4"
            source.write_bytes(b"encoded-video")

            def fake_ffmpeg(command, **_kwargs):
                Path(command[-1]).write_bytes(b"retimed-video")
                return mock.Mock(returncode=0, stderr="")

            with mock.patch(
                "auracam.daemon.subprocess.run", side_effect=fake_ffmpeg
            ) as run:
                result = daemon._retime_recording(
                    source, elapsed=20.0, frames=100, nominal_fps=10.0
                )

            self.assertEqual(result.read_bytes(), b"retimed-video")
            command = run.call_args.args[0]
            scale = float(command[command.index("-itsscale") + 1])
            self.assertAlmostEqual(scale, 2.0)
            self.assertIn("copy", command)


if __name__ == "__main__":
    unittest.main()
