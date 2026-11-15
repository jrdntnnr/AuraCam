import threading
import unittest

from protocol_camera import Camera as ProtocolCamera
from supercamera.camera import Camera as BaseCamera


def packet(frame_id, payload, stream=1, flags=0):
    header = bytes([0xAA, 0xBB, 0x07, 0, 0, frame_id, stream, flags, 0, 0, 0, 0])
    return header + payload


class FakeDevice:
    def __init__(self, packets):
        self.packets = iter(packets)

    def read(self, *_args, **_kwargs):
        return next(self.packets)


def protocol_camera(packets):
    camera = ProtocolCamera.__new__(ProtocolCamera)
    camera._dev = FakeDevice(packets)
    camera._streaming = False
    camera._io_lock = threading.Lock()
    camera._timeout = 1.0
    camera._frames_read = 0
    camera._active_camera = None
    camera._button_press_count = 0
    camera._last_button_frame = None
    return camera


def base_camera(packets):
    camera = BaseCamera.__new__(BaseCamera)
    camera._dev = FakeDevice(packets)
    camera._streaming = False
    camera._timeout = 1.0
    camera._frames_read = 0
    return camera


class FrameResynchronizationTest(unittest.TestCase):
    def test_protocol_driver_drops_incomplete_previous_frame(self):
        expected = b"\xff\xd8new-frame\xff\xd9"
        camera = protocol_camera(
            [packet(8, b"\xff\xd8incomplete"), packet(9, expected)]
        )

        self.assertEqual(camera._read_jpeg_internal(), expected)
        self.assertEqual(camera.frames_read, 1)

    def test_base_driver_drops_incomplete_previous_frame(self):
        expected = b"\xff\xd8new-frame\xff\xd9"
        camera = base_camera(
            [packet(8, b"\xff\xd8incomplete"), packet(9, expected)]
        )

        self.assertEqual(camera._read_jpeg_internal(), expected)
        self.assertEqual(camera.frames_read, 1)

    def test_new_soi_resynchronizes_even_without_protocol_header(self):
        expected = b"\xff\xd8replacement\xff\xd9"
        camera = protocol_camera(
            [packet(4, b"\xff\xd8incomplete"), expected]
        )

        self.assertEqual(camera._read_jpeg_internal(), expected)

    def test_button_flag_counts_once_per_hardware_frame(self):
        camera = protocol_camera(
            [
                packet(20, b"\xff\xd8part", flags=2),
                packet(20, b"more", flags=2),
                packet(20, b"\xff\xd9", flags=2),
            ]
        )

        self.assertEqual(camera._read_jpeg_internal(), b"\xff\xd8partmore\xff\xd9")
        self.assertEqual(camera.button_press_count, 1)


if __name__ == "__main__":
    unittest.main()
