import threading

from supercamera import Camera as BaseCamera
from supercamera.camera import EP_IN, EP_OUT

SWITCH_CAMERA_COMMAND = bytes([0xBB, 0xAA, 0x0B, 0x00, 0x02])


class Camera(BaseCamera):
    def __init__(self, *args, **kwargs):
        self._io_lock = threading.Lock()
        self._active_camera = None
        self._button_press_count = 0
        self._last_button_frame = None
        super().__init__(*args, **kwargs)

    def _read_chunk(self):
        with self._io_lock:
            return bytes(self._dev.read(EP_IN, 65536, timeout=1000))

    def _observe_header(self, data, frame_id):
        self._active_camera = data[6]
        if data[7] & 0x02 and frame_id != self._last_button_frame:
            self._button_press_count += 1
            self._last_button_frame = frame_id

    def switch_camera(self, selector=1):
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
