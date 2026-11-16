from __future__ import annotations

from .frames import OverlayTransform

FRAME_SIZE = (640, 480)
FRAME_RATE = 30
BUFFER_COUNT = 4
UPSIDE_DOWN = 180

# IMX219 sensor modes (rpicam-hello --list-cameras):
#   640x480   centre crop (1000, 752, 1280, 960) of the 3280x2464 array
#   1640x1232 full array, 2x2 binned
# The ISP scales either to FRAME_SIZE.
WIDE_SENSOR = {"output_size": (1640, 1232), "bit_depth": 10}

# The thermal overlay was registered in the crop mode; this is that crop in
# sensor pixels (x, y, width, height).
CALIBRATION_CROP = (1000, 752, 1280, 960)

# libcamera enum values.
AE_EXPOSURE_NORMAL = 0
AE_EXPOSURE_SHORT = 1
AE_CONSTRAINT_NORMAL = 0
AE_CONSTRAINT_HIGHLIGHT = 1

# Each look is a complete control set so switching never leaves residue.
_NATURAL = {
    "Saturation": 1.0,
    "Contrast": 1.0,
    "Sharpness": 1.0,
    "AeExposureMode": AE_EXPOSURE_NORMAL,
    "AeConstraintMode": AE_CONSTRAINT_NORMAL,
}
LOOK_CONTROLS = {
    "natural": _NATURAL,
    "mono": {**_NATURAL, "Saturation": 0.0},
    # Strong tone curve, crisp edges, exposure protects highlights.
    "hicon": {**_NATURAL, "Contrast": 1.8, "Sharpness": 2.0, "AeConstraintMode": AE_CONSTRAINT_HIGHLIGHT},
    # Short shutter with more gain: less motion blur, more noise.
    "fast": {**_NATURAL, "AeExposureMode": AE_EXPOSURE_SHORT},
}


class RgbCamera:
    button_press_count = 0

    def __init__(self, look: str, fov: str, exposure: float = 0.0):
        from libcamera import Transform
        from picamera2 import Picamera2

        self.look = look
        self.fov = fov
        self.exposure = exposure
        self._camera = Picamera2()
        try:
            flipped = self._camera.camera_properties.get("Rotation", 0) == UPSIDE_DOWN
            options = {"sensor": WIDE_SENSOR} if fov == "wide" else {}
            config = self._camera.create_video_configuration(
                main={"size": FRAME_SIZE, "format": "RGB888"},
                controls={"FrameRate": FRAME_RATE, **LOOK_CONTROLS[look], "ExposureValue": exposure},
                buffer_count=BUFFER_COUNT,
                transform=Transform(hflip=flipped, vflip=flipped),
                **options,
            )
            self._camera.configure(config)
            self._camera.start()
            self._crop = tuple(self._camera.capture_metadata().get("ScalerCrop", CALIBRATION_CROP))
        except Exception:
            self._camera.close()
            raise

    def set_look(self, look: str) -> None:
        self._camera.set_controls(LOOK_CONTROLS[look])
        self.look = look

    def set_exposure(self, exposure: float) -> None:
        """Auto-exposure bias in stops, e.g. -1.0 halves the target level."""
        self._camera.set_controls({"ExposureValue": exposure})
        self.exposure = exposure

    def overlay_transform(self, shape: tuple[int, ...]) -> OverlayTransform:
        """Map the calibrated overlay into the active crop.

        Example: wide crop 3280 px across vs calibration 1280 px -> the
        thermal field covers 1280/3280 = 0.39 of the frame width."""
        height, width = shape[:2]
        x, y, crop_w, crop_h = self._crop
        cal_x, cal_y, cal_w, cal_h = CALIBRATION_CROP
        shift_x = ((cal_x + cal_w / 2) - (x + crop_w / 2)) * width / crop_w
        shift_y = ((cal_y + cal_h / 2) - (y + crop_h / 2)) * height / crop_h
        return OverlayTransform(cal_w / crop_w, cal_h / crop_h, round(shift_x), round(shift_y))

    def read_frame(self):
        return self._camera.capture_array("main")

    def release(self):
        self._camera.stop()
        self._camera.close()

    def switch_camera(self, selector=1):
        raise RuntimeError("Lens switching is only available for the UV source")
