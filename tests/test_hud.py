import time
import unittest

import numpy as np

from auracam.compositor import AuraCompositor
from auracam.config import AuraConfig
from auracam.frames import HudTelemetry, OverlayGeometry, ThermalFrame
from auracam.hud import CornerMarks, HudRenderer, Marker, glyph_rows, palette_rgb


class HudRendererTest(unittest.TestCase):
    def setUp(self):
        field = np.full((24, 32), 24.0, dtype=np.float32)
        field[3, 5] = 41.5
        field[20, 27] = 17.25
        field[12, 16] = 29.0
        self.thermal = ThermalFrame(
            temperatures=field,
            image=field - 17.25,
            timestamp_ns=time.monotonic_ns(),
            subpage=1,
            ambient=23.0,
            vdd=3.3,
            complete=True,
            sequence=1,
        )
        self.data = HudTelemetry(
            uv_fps=9.2,
            thermal_fps=31.7,
            output_fps=8.9,
            uv_relative=0.53,
            recording_seconds=65.0,
            recording_frames=579,
            i2c_errors=2,
        )
        self.base = np.full((480, 640, 3), 48, dtype=np.uint8)

    def test_tactical_hud_renders(self):
        config = AuraConfig(
            hud_mode="tactical",
            hud_palette="green",
            scale_x=1.0,
            scale_y=1.0,
            max_alpha=0.0,
        )
        result = AuraCompositor().compose(
            self.base, self.thermal, config, self.data
        )
        self.assertEqual(result.shape, self.base.shape)
        self.assertEqual(result.dtype, np.uint8)
        self.assertGreater(np.count_nonzero(result != self.base), 1500)
        self.assertGreater(int(result[..., 1].max()), int(result[..., 0].max()))

    def test_hud_off_preserves_output(self):
        config = AuraConfig(hud_mode="off", max_alpha=0.0)
        plain = AuraCompositor().compose(self.base, self.thermal, config)
        with_data = AuraCompositor().compose(
            self.base, self.thermal, config, self.data
        )
        np.testing.assert_array_equal(with_data, plain)

    def test_hud_without_thermal(self):
        result = AuraCompositor().compose(
            self.base,
            None,
            AuraConfig(hud_mode="minimal", hud_palette="amber"),
            self.data,
        )
        self.assertGreater(np.count_nonzero(result != self.base), 100)

    def test_hud_has_no_global_banding(self):
        result = AuraCompositor().compose(
            self.base,
            None,
            AuraConfig(hud_mode="tactical"),
            self.data,
        )
        np.testing.assert_array_equal(
            result[140:420, 120:520], self.base[140:420, 120:520]
        )

    def test_mirrored_thermal_points(self):
        renderer = HudRenderer()
        points = renderer._thermal_points(
            self.thermal,
            AuraConfig(thermal_mirror_h=True, probe_x=16, probe_y=12),
        )
        self.assertIsNotNone(points)
        self.assertEqual(points.probe, (15, 12))
        self.assertEqual(points.high, (26, 3))
        self.assertEqual(points.low, (4, 20))

    def test_markers_in_output_pixels(self):
        compositor = AuraCompositor()
        config = AuraConfig(scale_x=1.0, scale_y=1.0, offset_x=0, offset_y=0)
        markers = compositor.markers(self.thermal, config, (480, 640))
        self.assertEqual([m.label for m in markers], ["P", "H", "L"])
        probe, high, low = markers
        self.assertEqual((probe.x, probe.y, probe.value), (330, 250, 29.0))
        self.assertEqual((high.x, high.y, high.value), (110, 70, 41.5))
        self.assertEqual((low.x, low.y, low.value), (550, 410, 17.25))

    def test_panel_overlay_draws_markers(self):
        frame = np.zeros((144, 192, 3), dtype=np.uint8)
        HudRenderer().overlay(frame, [Marker("P", 96, 72, 29.0)], "green", CornerMarks.HIDE)
        self.assertTrue(frame[72, 96].any())
        self.assertFalse(frame[8, 8].any())
        HudRenderer().overlay(frame, [], "green", CornerMarks.SHOW)
        self.assertTrue(frame[8, 8].any())

    def test_font_and_palette_helpers(self):
        self.assertEqual(glyph_rows("a"), glyph_rows("A"))
        self.assertEqual(glyph_rows("\u00e9"), glyph_rows("?"))
        self.assertEqual(palette_rgb("green"), 0x84FF48)

    def test_rotated_thermal_points(self):
        renderer = HudRenderer()
        points = renderer._thermal_points(
            self.thermal,
            AuraConfig(thermal_rotation=90, probe_x=16, probe_y=12),
        )
        self.assertIsNotNone(points)
        self.assertEqual(points.probe, (11, 16))
        self.assertEqual(points.high, (20, 5))
        self.assertEqual(points.low, (3, 27))
        self.assertEqual((points.columns, points.rows), (24, 32))

    def test_full_overlay_mapping(self):
        renderer = HudRenderer()
        points = renderer._thermal_points(self.thermal, AuraConfig())
        geometry = OverlayGeometry(0, 0, 640, 480, 0.0)
        mapped = renderer._map_point((16, 12), points, geometry)
        self.assertEqual(mapped, (330, 250))


if __name__ == "__main__":
    unittest.main()
