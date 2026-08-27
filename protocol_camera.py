"""Stable app-local extensions for the proprietary useeplus camera protocol."""

import threading
import time

import usb.core
import usb.util
from supercamera import Camera as BaseCamera
from supercamera.camera import (
    CONNECT_CMD,
    EP_IAP_IN,
    EP_IAP_OUT,
    EP_IN,
    EP_OUT,
    HEADER_SIZE,
    JPEG_EOI,
    JPEG_SOI,
    MAGIC_INIT,
)

SWITCH_CAMERA_COMMAND = bytes([0xBB, 0xAA, 0x0B, 0x00, 0x02])


class Camera(BaseCamera):
    """Supercamera driver with stream/button metadata and lens switching."""

    def __init__(self, *args, **kwargs):
        self._io_lock = threading.Lock()
        self._active_camera = None
        self._button_press_count = 0
        self._last_button_frame = None
        super().__init__(*args, **kwargs)

    def _open(self):
        dev = self._find_device()
        self._dev = dev
        for interface in (0, 1):
            try:
                if dev.is_kernel_driver_active(interface):
                    dev.detach_kernel_driver(interface)
            except Exception:
                pass

        dev.set_configuration()
        usb.util.claim_interface(dev, 0)
        usb.util.claim_interface(dev, 1)
        for _ in range(30):
            try:
                dev.read(EP_IAP_IN, 512, timeout=100)
            except usb.core.USBError:
                break

        dev.set_interface_altsetting(interface=1, alternate_setting=1)
        try:
            dev.clear_halt(EP_OUT)
        except usb.core.USBError:
            # Some revision-1 firmware returns a harmless pipe error here.
            pass
        dev.write(EP_IAP_OUT, MAGIC_INIT, timeout=1000)
        dev.write(EP_OUT, CONNECT_CMD, timeout=1000)
        time.sleep(0.3)

        self._streaming = True
        self._frames_read = 0
        self._read_jpeg_internal()  # First frame after connect is incomplete.

    def _read_jpeg_internal(self):
        buf = bytearray()
        in_frame = False
        deadline = time.monotonic() + self._timeout

        while time.monotonic() < deadline:
            try:
                with self._io_lock:
                    data = bytes(self._dev.read(EP_IN, 65536, timeout=1000))
            except usb.core.USBError:
                continue

            payload = data
            if len(data) >= HEADER_SIZE and data[0:2] == bytes([0xAA, 0xBB]):
                # USB header (5 bytes), then frame id, stream number and flags.
                frame_id = data[5]
                self._active_camera = data[6]
                if data[7] & 0x02 and frame_id != self._last_button_frame:
                    self._button_press_count += 1
                    self._last_button_frame = frame_id
                payload = data[HEADER_SIZE:]

            start = payload.find(JPEG_SOI)
            if start >= 0 and not in_frame:
                in_frame = True
                buf = bytearray(payload[start:])
            elif in_frame:
                buf.extend(payload)

            if in_frame:
                end = buf.find(JPEG_EOI)
                if end >= 0:
                    self._frames_read += 1
                    return bytes(buf[:end + 2])
        return None

    def switch_camera(self, selector=1):
        """Issue the relative lens/stream switch used by dual-camera models."""
        if selector not in (1, 2):
            raise ValueError("Camera selector must be 1 or 2")
        if not self._streaming or self._dev is None:
            raise RuntimeError("Camera is not streaming")
        command = SWITCH_CAMERA_COMMAND + bytes([selector, 0x08, 0x00])
        with self._io_lock:
            self._dev.write(EP_OUT, command, timeout=1000)

    @property
    def active_camera(self):
        return self._active_camera

    @property
    def button_press_count(self):
        return self._button_press_count
