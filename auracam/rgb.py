from __future__ import annotations


class RgbCamera:
    button_press_count = 0

    def __init__(self):
        from picamera2 import Picamera2

        self._camera = Picamera2()
        try:
            config = self._camera.create_video_configuration(
                main={"size": (640, 480), "format": "RGB888"},
                controls={"FrameRate": 30},
                buffer_count=4,
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
