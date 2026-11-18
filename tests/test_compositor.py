import time
import unittest

import cv2
import numpy as np

from auracam.compositor import AuraCompositor
from auracam.config import MODES, AuraConfig
from auracam.thermal import ThermalFrame


class CompositorTest(unittest.TestCase):
    def test_gradient_end_colours(self):
        # BGR at the cold (0) and hot (1) ends.
        expected = {
            "ironbow": ((0, 0, 0), (255, 255, 255)),
            "amber": ((0, 0, 0), (200, 240, 255)),
            "whitehot": ((0, 0, 0), (255, 255, 255)),
            "arctic": ((0, 0, 0), (255, 250, 230)),
        }
        field = np.array([[0.0, 1.0]], dtype=np.float32)
        for palette, (cold, hot) in expected.items():
            color = AuraCompositor._colorize(field, palette)
            self.assertEqual(tuple(int(v) for v in color[0, 0]), cold, palette)
            self.assertEqual(tuple(int(v) for v in color[0, 1]), hot, palette)

    def test_amber_gradient_passes_hud_amber(self):
        field = np.linspace(0.0, 1.0, 256, dtype=np.float32)[None, :]
        color = AuraCompositor._colorize(field, "amber").reshape(-1, 3).astype(int)
        distance = np.abs(color - np.array([0, 194, 255])).sum(axis=1).min()
        self.assertLess(distance, 12)

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


    def test_tone_adjust_matches_float_math(self):
        # Gamma, then contrast about mid-grey, then brightness; within one level.
        config = AuraConfig(gamma=1.4, contrast=1.3, brightness=1.1)
        frame = np.arange(256, dtype=np.uint8).reshape(16, 16, 1).repeat(3, axis=2)
        work = np.power(frame.astype(np.float32) / 255.0, 1.0 / config.gamma)
        work = ((work - 0.5) * config.contrast + 0.5) * config.brightness
        expected = np.clip(work * 255, 0, 255).astype(np.uint8)
        result = AuraCompositor._process_base(frame, config)
        diff = np.abs(result.astype(np.int16) - expected)
        self.assertLessEqual(int(diff.max()), 1)

    def test_tone_adjust_is_fast(self):
        # The float pass ran ~25x a frame copy: 7 fps on the Cardputer.
        frame = np.random.default_rng(0).integers(0, 256, (480, 640, 3), np.uint8)
        config = AuraConfig(contrast=1.3)

        def cost(work):
            work()
            started = time.perf_counter()
            for _ in range(50):
                work()
            return time.perf_counter() - started

        toned = cost(lambda: AuraCompositor._process_base(frame, config))
        copied = cost(frame.copy)
        self.assertLess(toned, 8 * copied)

    def test_zoomed_overlay_matches_full_render(self):
        # Zoomed past the frame, only the on-screen window is built.
        rng = np.random.default_rng(1)
        frame = rng.integers(0, 256, (480, 640, 3), np.uint8)
        temps = (24 + 12 * rng.random((24, 32))).astype(np.float32)
        thermal = ThermalFrame(temps, temps, 1, 0, 30.0, 3.3, True, 1)
        for mode in ("clean", "glitch"):
            config = AuraConfig(mode=mode, scale_x=1.69, scale_y=1.69, offset_x=64, offset_y=-60, blur=13.0)
            cropped = AuraCompositor().compose(frame, thermal, config)
            full = AuraCompositor()
            full._window = lambda *args: None
            np.testing.assert_array_equal(cropped, full.compose(frame, thermal, config), mode)

if __name__ == "__main__":
    unittest.main()
