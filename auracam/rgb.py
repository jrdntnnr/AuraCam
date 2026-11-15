from __future__ import annotations

FRAME_SIZE = (640, 480)
FRAME_RATE = 30
BUFFER_COUNT = 4
UPSIDE_DOWN = 180


class RgbCamera:
    button_press_count = 0

    def __init__(self):
        from libcamera import Transform
        from picamera2 import Picamera2

        self._camera = Picamera2()
        try:
            flipped = self._camera.camera_properties.get("Rotation", 0) == UPSIDE_DOWN
            config = self._camera.create_video_configuration(
                main={"size": FRAME_SIZE, "format": "RGB888"},
                controls={"FrameRate": FRAME_RATE},
                buffer_count=BUFFER_COUNT,
                transform=Transform(hflip=flipped, vflip=flipped),
            )
            self._camera.configure(config)
            self._camera.start()
        except Exception:
            self._camera.close()
            raise

    def read_frame(self):
        return self._camera.capture_array("main")

    def release(self):
        self._camera.stop()
        self._camera.close()

    def switch_camera(self, selector=1):
        raise RuntimeError("Lens switching is only available for the UV source")
