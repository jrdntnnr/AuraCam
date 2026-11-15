import unittest

import cv2
import numpy as np

from supercamera.validate import decode_jpeg, is_valid_jpeg


class JpegValidationTest(unittest.TestCase):
    def setUp(self):
        y, x = np.mgrid[0:240, 0:320]
        image = np.dstack((x / 2, y, (x + y) / 3)).astype(np.uint8)
        ok, encoded = cv2.imencode(".jpg", image)
        self.assertTrue(ok)
        self.jpeg = encoded.tobytes()

    def test_valid_frame_decodes(self):
        decoded = decode_jpeg(self.jpeg)
        self.assertIsNotNone(decoded)
        self.assertEqual(decoded.shape, (240, 320, 3))
        self.assertTrue(is_valid_jpeg(self.jpeg))

    def test_truncated_scan_is_rejected(self):
        start = self.jpeg.index(b"\xff\xda")
        length = int.from_bytes(self.jpeg[start + 2 : start + 4], "big")
        scan = start + 2 + length
        damaged = self.jpeg[: scan + 64] + b"\xff\xd9"
        self.assertIsNone(decode_jpeg(damaged))
        self.assertFalse(is_valid_jpeg(damaged))

    def test_invalid_markers_are_rejected(self):
        self.assertIsNone(decode_jpeg(b"not-jpeg"))

    def test_valid_neutral_frame_decodes(self):
        image = np.full((240, 320, 3), 128, dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", image)
        self.assertTrue(ok)
        self.assertIsNotNone(decode_jpeg(encoded.tobytes()))


if __name__ == "__main__":
    unittest.main()
