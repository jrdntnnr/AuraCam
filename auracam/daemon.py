from __future__ import annotations

import base64
import json
import os
import queue
import signal
import socket
import subprocess
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .compositor import AuraCompositor
from .config import ConfigStore, canonical_name
from .control import (
    DEFAULT_SOCKET,
    MODES,
    CaptureSource,
    ControlCommand,
    RecordAction,
    RotationSource,
    SwitchAction,
)
from .frames import HudTelemetry
from .thermal import MLX90640, DemoMLX90640, ThermalWorker
from supercamera.validate import decode_jpeg

_DEMO_CAMERA = object()
_RECORD_END = object()
_RECORD_QUEUE_SIZE = 24
_CONFIG_COMMANDS = frozenset(
    {
        ControlCommand.CONFIG,
        ControlCommand.SET,
        ControlCommand.ADJUST,
        ControlCommand.MODE,
        ControlCommand.ROTATE,
        ControlCommand.TOGGLE,
    }
)
_CAPTURE_COMMANDS = frozenset(
    {
        ControlCommand.SNAPSHOT,
        ControlCommand.RECORD,
        ControlCommand.PAUSE,
        ControlCommand.LENS,
    }
)
_PREVIEW_COMMANDS = frozenset(
    {ControlCommand.PREVIEW, ControlCommand.THERMAL_PREVIEW}
)


class RateCounter:
    def __init__(self, length: int = 120):
        self._times: deque[float] = deque(maxlen=length)
        self._lock = threading.Lock()

    def tick(self) -> None:
        with self._lock:
            self._times.append(time.monotonic())

    @property
    def fps(self) -> float:
        with self._lock:
            values = tuple(self._times)
        if len(values) < 2:
            return 0.0
        return (len(values) - 1) / max(0.001, values[-1] - values[0])


class AuraDaemon:
    def __init__(
        self,
        socket_path: str = DEFAULT_SOCKET,
        config_path: str | None = None,
        output_dir: str | None = None,
        source: CaptureSource = CaptureSource.HARDWARE,
    ):
        home = Path.home()
        self.socket_path = Path(socket_path)
        self.config_store = ConfigStore(
            config_path or home / ".config/auracam/config.json"
        )
        self.output_dir = Path(output_dir or home / "Pictures/auracam")
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.source = CaptureSource(source)
        factory = DemoMLX90640 if self.source is CaptureSource.DEMO else MLX90640
        self.thermal = ThermalWorker(self.config_store.get, sensor_factory=factory)
        self.compositor = AuraCompositor()
        self._stop = threading.Event()
        self._capture_thread: threading.Thread | None = None
        self._camera = None
        self._camera_lock = threading.Lock()
        self._frame_lock = threading.Lock()
        self._jpeg_lock = threading.Lock()
        self._latest_jpeg: bytes | None = None
        self._jpeg_sequence = -1
        self._latest_frame: np.ndarray | None = None
        self._frame_sequence = 0
        self._started = time.monotonic()
        self._uv_rate = RateCounter()
        self._output_rate = RateCounter()
        self.uv_connected = False
        self.uv_error: str | None = None
        self.uv_frames = 0
        self.dropped_uv_frames = 0
        self.paused = False
        self.last_snapshot: str | None = None
        self._last_button_count = 0
        self._record_lock = threading.Lock()
        self._record_writer = None
        self._record_path: str | None = None
        self._record_temp_path: str | None = None
        self._record_started = 0.0
        self._record_frames = 0
        self._record_nominal_fps = 0.0
        self._record_size: tuple[int, int] | None = None
        self._record_error: str | None = None
        self._record_queue: queue.Queue | None = None
        self._record_thread: threading.Thread | None = None
        self._record_accepting = False
        self._record_dropped = 0

    def start(self) -> None:
        self.thermal.start()
        self._capture_thread = threading.Thread(
            target=self._capture_loop, name="uv-capture", daemon=True
        )
        self._capture_thread.start()

    def close(self) -> None:
        self._stop.set()
        self.thermal.stop()
        camera = self._camera
        if camera:
            try:
                camera.release()
            except Exception:
                pass
        if self._capture_thread:
            self._capture_thread.join(timeout=3)
        self._stop_recording()
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass

    def _demo_frame(self) -> np.ndarray:
        height, width = 480, 640
        y, x = np.mgrid[0:height, 0:width]
        elapsed = time.monotonic() - self._started
        blue = ((x / width) * 190 + 35).astype(np.uint8)
        green = ((y / height) * 125 + 30).astype(np.uint8)
        red = (55 + 25 * np.sin(x / 45 + elapsed)).astype(np.uint8)
        frame = np.dstack((blue, green, np.broadcast_to(red, (height, width)))).copy()
        cv2.putText(
            frame,
            "AuraCam demo UV frame",
            (28, 55),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.0,
            (240, 240, 240),
            2,
            cv2.LINE_AA,
        )
        return frame

    def _connect_camera(self):
        if self.source is CaptureSource.DEMO:
            self.uv_connected = True
            self.uv_error = None
            return _DEMO_CAMERA
        from protocol_camera import Camera

        camera = Camera()
        with self._camera_lock:
            self._camera = camera
        self._last_button_count = camera.button_press_count
        self.uv_connected = True
        self.uv_error = None
        return camera

    def _release_camera(self, camera) -> None:
        if camera is not None and camera is not _DEMO_CAMERA:
            try:
                camera.release()
            except Exception:
                pass
        with self._camera_lock:
            if self._camera is camera:
                self._camera = None
        self.uv_connected = False

    def _capture_loop(self) -> None:
        camera = None
        retry_at = 0.0
        while not self._stop.is_set():
            if camera is None:
                if time.monotonic() < retry_at:
                    self._stop.wait(0.2)
                    continue
                try:
                    camera = self._connect_camera()
                except Exception as exc:
                    self.uv_error = str(exc)
                    self.uv_connected = False
                    retry_at = time.monotonic() + 5.0
                    continue
            if self.paused:
                self._stop.wait(0.05)
                continue
            config = self.config_store.get()
            started = time.monotonic()
            try:
                if camera is _DEMO_CAMERA:
                    frame = self._demo_frame()
                else:
                    jpeg = camera.read_jpeg()
                    if not jpeg:
                        self.dropped_uv_frames += 1
                        continue
                    frame = decode_jpeg(jpeg)
                    if frame is None:
                        self.dropped_uv_frames += 1
                        continue
                self.uv_frames += 1
                self._uv_rate.tick()
                thermal = self.thermal.latest()
                telemetry = self._hud_data(frame) if config.hud_mode != "off" else None
                composed = self.compositor.compose(frame, thermal, config, telemetry)
                with self._frame_lock:
                    self._latest_frame = composed
                    self._frame_sequence += 1
                    self._latest_jpeg = None
                    self._jpeg_sequence = -1
                self._write_recording(composed)
                self._output_rate.tick()
                if (
                    camera is not _DEMO_CAMERA
                    and camera.button_press_count > self._last_button_count
                ):
                    self._last_button_count = camera.button_press_count
                    self.snapshot(suffix="button")
                self.uv_error = None
            except Exception as exc:
                self.uv_error = str(exc)
                self.dropped_uv_frames += 1
                self._release_camera(camera)
                camera = None
                retry_at = time.monotonic() + 2.0
                continue
            delay = 1.0 / config.host_fps_cap - (time.monotonic() - started)
            if delay > 0:
                self._stop.wait(delay)
        self._release_camera(camera)

    def _hud_data(self, frame: np.ndarray) -> HudTelemetry:
        sample = frame[::16, ::16].astype(np.float32)
        relative = float(
            np.mean(
                sample[..., 0] * 0.114
                + sample[..., 1] * 0.587
                + sample[..., 2] * 0.299
            )
            / 255.0
        )
        recording = self.recording_status()
        seconds = recording["seconds"] if recording["active"] else None
        return HudTelemetry(
            uv_fps=self._uv_rate.fps,
            thermal_fps=self.thermal.fps,
            output_fps=self._output_rate.fps,
            uv_relative=min(1.0, max(0.0, relative)),
            recording_seconds=seconds,
            recording_frames=recording["frames"],
            i2c_errors=self.thermal.errors,
        )

    def _write_recording(self, frame: np.ndarray) -> None:
        with self._record_lock:
            writer = self._record_writer
            frame_queue = self._record_queue
            accepting = self._record_accepting
            record_size = self._record_size
            if writer is None or frame_queue is None or not accepting:
                return
        height, width = frame.shape[:2]
        if record_size != (width, height):
            target_w, target_h = record_size
            canvas = np.zeros((target_h, target_w, 3), dtype=np.uint8)
            scale = min(target_w / width, target_h / height)
            resized = cv2.resize(frame, (round(width * scale), round(height * scale)))
            y = (target_h - resized.shape[0]) // 2
            x = (target_w - resized.shape[1]) // 2
            canvas[y : y + resized.shape[0], x : x + resized.shape[1]] = resized
            frame = canvas
        raw = frame.tobytes()
        with self._record_lock:
            if self._record_writer is not writer or not self._record_accepting:
                return
            try:
                frame_queue.put_nowait(raw)
            except queue.Full:
                self._record_dropped += 1

    def _record_loop(self, writer, frame_queue: queue.Queue) -> None:
        try:
            while True:
                item = frame_queue.get()
                if item is _RECORD_END:
                    frame_queue.task_done()
                    break
                try:
                    returncode = writer.poll()
                    if returncode is not None:
                        raise RuntimeError(
                            f"video encoder exited with status {returncode}"
                        )
                    if writer.stdin is None:
                        raise RuntimeError("video encoder input is unavailable")
                    writer.stdin.write(item)
                    with self._record_lock:
                        self._record_frames += 1
                except (BrokenPipeError, OSError, RuntimeError) as exc:
                    with self._record_lock:
                        self._record_error = str(exc)
                        self._record_accepting = False
                    frame_queue.task_done()
                    break
                frame_queue.task_done()
        finally:
            if writer.stdin is not None and not writer.stdin.closed:
                try:
                    writer.stdin.close()
                except (BrokenPipeError, OSError):
                    pass

    def _pending_dir(self) -> Path:
        path = self.output_dir / ".inprogress"
        path.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _sync_path(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def _publish_file(self, pending: Path, final: Path) -> None:
        self._sync_path(pending)
        os.replace(pending, final)
        self._sync_path(final.parent)

    def _frame_jpeg(self) -> tuple[bytes | None, int]:
        with self._jpeg_lock:
            with self._frame_lock:
                sequence = self._frame_sequence
                if (
                    self._latest_jpeg is not None
                    and self._jpeg_sequence == sequence
                ):
                    return self._latest_jpeg, sequence
                frame = (
                    None
                    if self._latest_frame is None
                    else self._latest_frame.copy()
                )
            if frame is None:
                return None, sequence
            quality = self.config_store.get().jpeg_quality
            ok, encoded = cv2.imencode(
                ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality]
            )
            if not ok:
                raise RuntimeError("JPEG encoder failed")
            jpeg = encoded.tobytes()
            with self._frame_lock:
                if self._frame_sequence == sequence:
                    self._latest_jpeg = jpeg
                    self._jpeg_sequence = sequence
            return jpeg, sequence

    def snapshot(self, suffix: str = "cli") -> str:
        jpeg, _ = self._frame_jpeg()
        if not jpeg:
            raise RuntimeError("No composited frame is available yet")
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        path = self.output_dir / f"aura_{stamp}_{suffix}.jpg"
        pending = self._pending_dir() / path.name
        try:
            with pending.open("wb") as stream:
                written = stream.write(jpeg)
                stream.flush()
                os.fsync(stream.fileno())
            if written != len(jpeg) or pending.stat().st_size != len(jpeg):
                raise RuntimeError("Snapshot write was incomplete")
            self._publish_file(pending, path)
        except Exception:
            pending.unlink(missing_ok=True)
            raise
        self.last_snapshot = str(path)
        return str(path)

    def _start_recording(self) -> str:
        with self._frame_lock:
            frame = None if self._latest_frame is None else self._latest_frame.copy()
        if frame is None:
            raise RuntimeError("No composited frame is available yet")
        with self._record_lock:
            existing = self._record_writer
            if existing is not None and existing.poll() is None:
                return self._record_path

        if existing is not None:
            try:
                self._stop_recording()
            except RuntimeError:
                pass

        with self._record_lock:
            height, width = frame.shape[:2]
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            path = self.output_dir / f"aura_{stamp}.mp4"
            pending = self._pending_dir() / path.name
            nominal_fps = max(
                1.0, self._output_rate.fps or self.config_store.get().host_fps_cap
            )
            writer = subprocess.Popen(
                [
                    "ffmpeg",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-f",
                    "rawvideo",
                    "-pixel_format",
                    "bgr24",
                    "-video_size",
                    f"{width}x{height}",
                    "-framerate",
                    f"{nominal_fps:.6f}",
                    "-i",
                    "pipe:0",
                    "-an",
                    "-c:v",
                    "h264_v4l2m2m",
                    "-b:v",
                    "4000000",
                    "-pix_fmt",
                    "yuv420p",
                    "-fps_mode",
                    "passthrough",
                    str(pending),
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            if writer.stdin is None:
                writer.kill()
                pending.unlink(missing_ok=True)
                raise RuntimeError("Could not open hardware H.264 writer")
            self._record_writer = writer
            self._record_path = str(path)
            self._record_temp_path = str(pending)
            self._record_started = time.monotonic()
            self._record_frames = 0
            self._record_nominal_fps = nominal_fps
            self._record_size = (width, height)
            self._record_error = None
            self._record_dropped = 0
            self._record_queue = queue.Queue(maxsize=_RECORD_QUEUE_SIZE)
            self._record_accepting = True
            self._record_thread = threading.Thread(
                target=self._record_loop,
                args=(writer, self._record_queue),
                name="video-writer",
                daemon=True,
            )
            self._record_thread.start()
            return str(path)

    def _retime_recording(
        self,
        source: Path,
        elapsed: float,
        frames: int,
        nominal_fps: float,
    ) -> Path:
        encoded_duration = frames / max(1.0, nominal_fps)
        scale = elapsed / max(0.001, encoded_duration)
        if abs(scale - 1.0) < 0.005:
            return source

        retimed = source.with_name(f"{source.stem}.retimed.mp4")
        result = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-itsscale",
                f"{scale:.12f}",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(retimed),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode or not retimed.exists() or retimed.stat().st_size <= 0:
            retimed.unlink(missing_ok=True)
            detail = result.stderr.strip() or "ffmpeg produced no output"
            raise RuntimeError(f"Could not finalize recording timing: {detail}")
        return retimed

    def _stop_recording(self) -> str | None:
        with self._record_lock:
            path = self._record_path
            pending = self._record_temp_path
            writer = self._record_writer
            frame_queue = self._record_queue
            worker = self._record_thread
            self._record_accepting = False
            elapsed = time.monotonic() - self._record_started
            nominal_fps = self._record_nominal_fps
        if writer is None:
            return path
        if worker is not None and frame_queue is not None and worker.is_alive():
            try:
                frame_queue.put(_RECORD_END, timeout=10)
            except queue.Full:
                writer.kill()
            worker.join(timeout=30)
        elif writer.stdin is not None and not writer.stdin.closed:
            writer.stdin.close()
        if worker is not None and worker.is_alive():
            writer.kill()
            worker.join(timeout=5)
            self._record_error = "Hardware video encoder queue did not finish"
        try:
            returncode = writer.wait(timeout=30)
        except subprocess.TimeoutExpired:
            writer.kill()
            writer.wait(timeout=5)
            returncode = -1
            self._record_error = "Hardware video encoder did not finish"
        with self._record_lock:
            frames = self._record_frames
            self._record_writer = None
            self._record_path = None
            self._record_temp_path = None
            self._record_size = None
            self._record_nominal_fps = 0.0
            self._record_queue = None
            self._record_thread = None
        if returncode == -1:
            if pending:
                Path(pending).unlink(missing_ok=True)
            raise RuntimeError(self._record_error)
        pending_path = Path(pending) if pending else None
        if (
            returncode != 0
            or frames <= 0
            or pending_path is None
            or not pending_path.exists()
            or pending_path.stat().st_size <= 0
        ):
            if pending_path is not None:
                pending_path.unlink(missing_ok=True)
            self._record_error = "hardware encoder produced no video frames"
            raise RuntimeError(self._record_error)
        prepared = self._retime_recording(
            pending_path, elapsed, frames, nominal_fps
        )
        if prepared != pending_path:
            pending_path.unlink(missing_ok=True)
        final_path = Path(path)
        self._publish_file(prepared, final_path)
        self._record_error = None
        return str(final_path)

    def recording_status(self) -> dict[str, Any]:
        with self._record_lock:
            writer = self._record_writer
            returncode = writer.poll() if writer is not None else None
            if writer is not None and returncode is not None and self._record_error is None:
                self._record_error = f"video encoder exited with status {returncode}"
            worker = self._record_thread
            active = (
                writer is not None
                and returncode is None
                and self._record_accepting
                and self._record_error is None
                and (worker is None or worker.is_alive())
            )
            return {
                "active": active,
                "path": self._record_path,
                "frames": self._record_frames,
                "dropped": self._record_dropped,
                "seconds": time.monotonic() - self._record_started if active else 0.0,
                "error": self._record_error,
            }

    def status(self) -> dict[str, Any]:
        thermal = self.thermal.latest()
        try:
            load = os.getloadavg()[0]
        except OSError:
            load = 0.0
        return {
            "ok": True,
            "uptime": time.monotonic() - self._started,
            "paused": self.paused,
            "demo": self.source is CaptureSource.DEMO,
            "load_1m": load,
            "frame_sequence": self._frame_sequence,
            "uv": {
                "connected": self.uv_connected,
                "fps": self._uv_rate.fps,
                "frames": self.uv_frames,
                "dropped": self.dropped_uv_frames,
                "error": self.uv_error,
            },
            "thermal": {
                "connected": self.thermal.connected,
                "fps": self.thermal.fps,
                "refresh_hz": self.thermal.actual_refresh_hz,
                "subpage": thermal.subpage if thermal else None,
                "sequence": thermal.sequence if thermal else 0,
                "min": thermal.minimum if thermal else None,
                "max": thermal.maximum if thermal else None,
                "ambient": thermal.ambient if thermal else None,
                "vdd": thermal.vdd if thermal else None,
                "errors": self.thermal.errors,
                "error": self.thermal.error,
            },
            "output": {
                "fps": self._output_rate.fps,
                "directory": str(self.output_dir),
                "last_snapshot": self.last_snapshot,
            },
            "recording": self.recording_status(),
            "config": self.config_store.as_dict(),
        }

    def thermal_preview(self) -> tuple[bytes | None, int]:
        thermal = self.thermal.latest()
        if thermal is None:
            return None, 0
        config = self.config_store.get()
        color = self.compositor.render_thermal(thermal, config)
        ok, encoded = cv2.imencode(
            ".jpg", color, [cv2.IMWRITE_JPEG_QUALITY, config.jpeg_quality]
        )
        if not ok:
            raise RuntimeError("Thermal preview JPEG encoder failed")
        return encoded.tobytes(), thermal.sequence

    def _config_command(
        self, command: ControlCommand, request: dict[str, Any]
    ) -> dict[str, Any]:
        if command is ControlCommand.CONFIG:
            return {"ok": True, "config": self.config_store.as_dict()}
        if command is ControlCommand.SET:
            name = str(request["name"])
            config = self.config_store.update(name, request["value"])
            return {
                "ok": True,
                "config": self.config_store.as_dict(),
                "value": getattr(config, canonical_name(name)),
            }
        if command is ControlCommand.ADJUST:
            name = str(request["name"])
            config = self.config_store.adjust(name, float(request["delta"]))
            return {
                "ok": True,
                "config": self.config_store.as_dict(),
                "value": getattr(config, canonical_name(name)),
            }
        if command is ControlCommand.MODE:
            mode = str(request["mode"]).lower()
            if mode not in MODES:
                raise ValueError(f"mode must be one of: {', '.join(MODES)}")
            config = self.config_store.apply_mode(mode)
            return {"ok": True, "mode": mode, "config": self.config_store.as_dict()}
        if command is ControlCommand.ROTATE:
            source_value = str(
                request.get("source", RotationSource.THERMAL.value)
            ).lower()
            try:
                source = RotationSource(source_value)
            except ValueError:
                raise ValueError("rotation source must be camera or thermal") from None
            name = {
                RotationSource.CAMERA: "camera_rotation",
                RotationSource.THERMAL: "thermal_rotation",
            }[source]
            config = self.config_store.cycle_rotation(name)
            return {
                "ok": True,
                "source": source.value,
                "rotation": getattr(config, name),
            }
        if command is ControlCommand.TOGGLE:
            name = str(request["name"])
            config = self.config_store.toggle(name)
            return {
                "ok": True,
                "name": canonical_name(name),
                "value": getattr(config, canonical_name(name)),
            }

        raise ValueError(f"Unknown config command: {command.value}")

    def _capture_command(
        self, command: ControlCommand, request: dict[str, Any]
    ) -> dict[str, Any]:
        if command is ControlCommand.SNAPSHOT:
            return {"ok": True, "path": self.snapshot()}
        if command is ControlCommand.RECORD:
            action_value = str(request.get("action", RecordAction.TOGGLE.value))
            try:
                action = RecordAction(action_value)
            except ValueError:
                allowed = ", ".join(value.value for value in RecordAction)
                raise ValueError(f"record action must be one of: {allowed}") from None
            present = self._record_writer is not None
            if action is RecordAction.START or (
                action is RecordAction.TOGGLE and not present
            ):
                return {"ok": True, "active": True, "path": self._start_recording()}
            return {"ok": True, "active": False, "path": self._stop_recording()}
        if command is ControlCommand.PAUSE:
            action_value = request.get("action", SwitchAction.TOGGLE.value)
            if isinstance(action_value, bool):
                action = SwitchAction.ON if action_value else SwitchAction.OFF
            else:
                try:
                    action = SwitchAction(str(action_value))
                except ValueError:
                    allowed = ", ".join(value.value for value in SwitchAction)
                    raise ValueError(f"pause action must be one of: {allowed}") from None
            if action is SwitchAction.TOGGLE:
                self.paused = not self.paused
            else:
                self.paused = action is SwitchAction.ON
            return {"ok": True, "paused": self.paused}
        if command is ControlCommand.LENS:
            camera = self._camera
            if camera is None or camera is _DEMO_CAMERA:
                raise RuntimeError("UV camera is not connected")
            camera.switch_camera(int(request.get("selector", 1)))
            return {"ok": True}

        raise ValueError(f"Unknown capture command: {command.value}")

    def _preview_command(self, command: ControlCommand) -> dict[str, Any]:
        if command is ControlCommand.PREVIEW:
            jpeg, sequence = self._frame_jpeg()
            return {
                "ok": True,
                "sequence": sequence,
                "jpeg": base64.b64encode(jpeg).decode("ascii") if jpeg else None,
                "status": self.status(),
            }
        if command is ControlCommand.THERMAL_PREVIEW:
            jpeg, sequence = self.thermal_preview()
            return {
                "ok": True,
                "sequence": sequence,
                "jpeg": base64.b64encode(jpeg).decode("ascii") if jpeg else None,
                "status": self.status(),
            }

        raise ValueError(f"Unknown preview command: {command.value}")

    def _handle(self, request: dict[str, Any]) -> dict[str, Any]:
        command_value = str(request.get("command", ControlCommand.STATUS.value))
        try:
            command = ControlCommand(command_value)
        except ValueError:
            raise ValueError(f"Unknown command: {command_value}") from None

        if command is ControlCommand.STATUS:
            return self.status()
        if command in _CONFIG_COMMANDS:
            return self._config_command(command, request)
        if command in _CAPTURE_COMMANDS:
            return self._capture_command(command, request)
        if command in _PREVIEW_COMMANDS:
            return self._preview_command(command)

        raise ValueError(f"Unknown command: {command.value}")

    def serve_forever(self) -> None:
        self.start()
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.socket_path))
        os.chmod(self.socket_path, 0o660)
        server.listen(8)
        server.settimeout(0.5)
        try:
            while not self._stop.is_set():
                try:
                    connection, _ = server.accept()
                except socket.timeout:
                    continue
                with connection:
                    connection.settimeout(3.0)
                    try:
                        payload = b""
                        while b"\n" not in payload and len(payload) < 2_000_000:
                            chunk = connection.recv(65536)
                            if not chunk:
                                break
                            payload += chunk
                        request = json.loads(payload.split(b"\n", 1)[0].decode("utf-8"))
                        response = self._handle(request)
                    except Exception as exc:
                        response = {"ok": False, "error": str(exc)}
                    connection.sendall(
                        json.dumps(response, separators=(",", ":")).encode() + b"\n"
                    )
        finally:
            server.close()
            self.close()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="AuraCam background capture engine")
    parser.add_argument(
        "--socket", default=os.environ.get("AURACAM_SOCKET", DEFAULT_SOCKET)
    )
    parser.add_argument("--config")
    parser.add_argument("--output")
    parser.add_argument("--demo", action="store_true")
    args = parser.parse_args()
    source = CaptureSource.DEMO if args.demo else CaptureSource.HARDWARE
    daemon = AuraDaemon(args.socket, args.config, args.output, source)
    signal.signal(signal.SIGTERM, lambda *_: daemon._stop.set())
    signal.signal(signal.SIGINT, lambda *_: daemon._stop.set())
    daemon.serve_forever()


if __name__ == "__main__":
    main()
