import tempfile
import unittest
from pathlib import Path

from auracam.config import AuraConfig, ConfigStore


class ConfigStoreTest(unittest.TestCase):
    def test_persists_and_validates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            store = ConfigStore(path)
            store.update("mode", "trail")
            store.update("threshold", "27.5")
            store.update("hud_mode", "tactical")
            store.update("hud_palette", "amber")
            store.update("probe_x", 9)
            store.update("probe_y", 7)
            loaded = ConfigStore(path).get()
            self.assertEqual(loaded.mode, "trail")
            self.assertEqual(loaded.threshold, 27.5)
            self.assertEqual(loaded.hud_mode, "tactical")
            self.assertEqual(loaded.hud_palette, "amber")
            self.assertEqual((loaded.probe_x, loaded.probe_y), (9, 7))
            with self.assertRaises(ValueError):
                store.update("opacity", 2)
            with self.assertRaises(ValueError):
                store.update("no_such_setting", 1)
            with self.assertRaises(ValueError):
                store.update("probe_x", 32)
            with self.assertRaises(ValueError):
                store.update("hud_mode", "busy")

    def test_camera_look_and_fov_choices(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "config.json")
            self.assertEqual((store.get().camera_look, store.get().camera_fov), ("natural", "crop"))
            store.update("camera_look", "mono")
            store.update("camera_fov", "wide")
            self.assertEqual((store.get().camera_look, store.get().camera_fov), ("mono", "wide"))
            with self.assertRaises(ValueError):
                store.update("camera_look", "sepia")

    def test_thermal_range_remains_ordered(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "config.json")
            with self.assertRaises(ValueError):
                store.update("thermal_max", 10)

    def test_adjustment_clamps_at_valid_range(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "config.json")
            store.update("opacity", 0.03)
            self.assertEqual(store.adjust("opacity", -0.05).opacity, 0.0)

    def test_legacy_names_and_interpolation_migrate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text(
                '{"base_rotation": 90, "opacity": 0.4, "interpolation": "linear"}'
            )
            config = ConfigStore(path).get()
            self.assertEqual(config.camera_rotation, 90)
            self.assertEqual(config.max_alpha, 0.4)
            self.assertEqual(config.interpolation, "bilinear")

    def test_rotations_cycle_and_mode_profiles_are_persistent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            store = ConfigStore(path)
            for expected in (90, 180, 270, 0):
                config = store.cycle_rotation("thermal_rotation")
                self.assertEqual(config.thermal_rotation, expected)
            config = store.apply_mode("debug")
            self.assertTrue(config.grid)
            self.assertEqual(config.interpolation, "nearest")
            self.assertEqual(config.blur, 0)
            loaded = ConfigStore(path).get()
            self.assertEqual(loaded, config)

    def test_new_defaults_match_clean_aura(self):
        config = AuraConfig()
        self.assertEqual(config.interpolation, "bilinear")
        self.assertFalse(config.grid)
        self.assertEqual(config.trail_decay, 0)
        self.assertEqual(config.hud_mode, "off")


if __name__ == "__main__":
    unittest.main()
