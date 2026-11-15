import time
import unittest

import cv2
import numpy as np

from auracam.compositor import AuraCompositor
from auracam.config import MODES, AuraConfig
from auracam.thermal import ThermalFrame


class CompositorTest(unittest.TestCase):
    def setUp(self):
        field = np.linspace(18, 42, 32 * 24, dtype=np.float32).reshape(24, 32)
        self.thermal = ThermalFrame(
            temperatures=field,
            image=field - 18,
            timestamp_ns=time.monotonic_ns(),
            subpage=1,
            ambient=22,
            vdd=3.3,
            complete=True,
            sequence=1,
        )
        self.base = np.full((480, 640, 3), 72, dtype=np.uint8)

    def test_all_modes_preserve_base_dimensions(self):
        compositor = AuraCompositor()
        for mode in MODES:
            with self.subTest(mode=mode):
                result = compositor.compose(
                    self.base, self.thermal, AuraConfig(mode=mode)
                )
                self.assertEqual(result.shape, self.base.shape)
                self.assertEqual(result.dtype, np.uint8)
                self.assertGreater(np.count_nonzero(result != self.base), 0)

    def test_partial_overlay_clips_without_cropping_base(self):
        result = AuraCompositor().compose(
            self.base,
            self.thermal,
            AuraConfig(
                mode="debug", scale_x=1.5, scale_y=1.5, offset_x=500, offset_y=-300
            ),
        )
        self.assertEqual(result.shape, (480, 640, 3))

    def test_jpeg_round_trip(self):
        result = AuraCompositor().compose(self.base, self.thermal, AuraConfig())
        ok, encoded = cv2.imencode(".jpg", result)
        self.assertTrue(ok)
        self.assertGreater(len(encoded), 1000)

    def test_thermal_preview_uses_public_renderer(self):
        result = AuraCompositor().render_thermal(
            self.thermal, AuraConfig(grid=True), size=(320, 240)
        )

        self.assertEqual(result.shape, (240, 320, 3))
        self.assertEqual(result.dtype, np.uint8)

    def test_camera_and_thermal_rotations_are_independent(self):
        compositor = AuraCompositor()
        rotated_base = compositor.compose(
            self.base,
            None,
            AuraConfig(camera_rotation=90, thermal_rotation=270),
        )
        self.assertEqual(rotated_base.shape, (640, 480, 3))

        source = np.arange(24 * 32, dtype=np.float32).reshape(24, 32)
        rotated_thermal = compositor._rotate_source(source, 270)
        self.assertEqual(rotated_thermal.shape, (32, 24))
        np.testing.assert_array_equal(rotated_thermal, np.rot90(source))

    def test_cold_background_is_transparent_and_hot_region_is_visible(self):
        cold = np.full((24, 32), 22.0, dtype=np.float32)
        cold_frame = ThermalFrame(
            temperatures=cold,
            image=cold,
            timestamp_ns=time.monotonic_ns(),
            subpage=0,
            ambient=22,
            vdd=3.3,
            complete=True,
            sequence=2,
        )
        compositor = AuraCompositor()
        cold_result = compositor.compose(
            self.base, cold_frame, AuraConfig(blur=0, smoothing=0)
        )
        np.testing.assert_array_equal(cold_result, self.base)

        hot = cold.copy()
        hot[8:16, 12:20] = 38.0
        hot_frame = ThermalFrame(
            temperatures=hot,
            image=hot,
            timestamp_ns=time.monotonic_ns(),
            subpage=1,
            ambient=22,
            vdd=3.3,
            complete=True,
            sequence=3,
        )
        hot_result = compositor.compose(
            self.base, hot_frame, AuraConfig(blur=4, smoothing=0)
        )
        self.assertGreater(np.count_nonzero(hot_result != self.base), 0)

    def test_grid_is_a_separate_toggle(self):
        compositor = AuraCompositor()
        plain = compositor.compose(
            self.base, self.thermal, AuraConfig(grid=False, blur=0, smoothing=0)
        )
        gridded = compositor.compose(
            self.base, self.thermal, AuraConfig(grid=True, blur=0, smoothing=0)
        )
        self.assertGreater(np.count_nonzero(plain != gridded), 0)

    def test_trail_decay_persists_at_thermal_resolution(self):
        hot = np.full((24, 32), 38.0, dtype=np.float32)
        cold = np.full((24, 32), 20.0, dtype=np.float32)

        def frame(field, sequence):
            return ThermalFrame(
                temperatures=field,
                image=field,
                timestamp_ns=time.monotonic_ns(),
                subpage=sequence & 1,
                ambient=22,
                vdd=3.3,
                complete=True,
                sequence=sequence,
            )

        config = AuraConfig(
            mode="trail", blur=0, smoothing=0, trail_decay=0.8, scale_x=0.5
        )
        compositor = AuraCompositor()
        compositor.compose(self.base, frame(hot, 1), config)
        result = compositor.compose(self.base, frame(cold, 2), config)
        self.assertGreater(np.count_nonzero(result != self.base), 0)
        self.assertEqual(compositor._trail.shape, (24, 32))

        disabled = AuraCompositor()
        no_trail = AuraConfig(
            mode="trail", blur=0, smoothing=0, trail_decay=0, scale_x=0.5
        )
        disabled.compose(self.base, frame(hot, 1), no_trail)
        result = disabled.compose(self.base, frame(cold, 2), no_trail)
        np.testing.assert_array_equal(result, self.base)

    def test_registered_overlay_is_cached_until_thermal_frame_changes(self):
        class CountingCompositor(AuraCompositor):
            def __init__(self):
                super().__init__()
                self.colorize_calls = 0

            def _colorize(self, norm, palette):
                self.colorize_calls += 1
                return super()._colorize(norm, palette)

        compositor = CountingCompositor()
        config = AuraConfig(blur=4)
        compositor.compose(self.base, self.thermal, config)
        compositor.compose(self.base, self.thermal, config)
        self.assertEqual(compositor.colorize_calls, 1)

        next_frame = ThermalFrame(
            temperatures=self.thermal.temperatures,
            image=self.thermal.image,
            timestamp_ns=self.thermal.timestamp_ns + 1,
            subpage=0,
            ambient=22,
            vdd=3.3,
            complete=True,
            sequence=2,
        )
        compositor.compose(self.base, next_frame, config)
        self.assertEqual(compositor.colorize_calls, 2)

    def test_neutral_base_adjustments_preserve_pixels(self):
        result = AuraCompositor().compose(self.base, None, AuraConfig())
        np.testing.assert_array_equal(result, self.base)


if __name__ == "__main__":
    unittest.main()
