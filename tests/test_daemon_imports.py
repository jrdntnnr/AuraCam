import subprocess
import sys
import unittest

# The Cardputer package ships without the USB UV driver and PyUSB; the
# daemon must load and serve the onboard camera without them.
WITHOUT_USB = """
import sys
sys.modules["usb"] = None
import auracam.daemon
assert "supercamera" not in sys.modules, "UV driver imported"
assert "protocol_camera" not in sys.modules, "UV camera imported"
"""

# The Cardputer entry spawns the engine before cv2 loads (~12 s on a CM0).
LAUNCH_IS_LIGHT = """
import sys
import auracam.launch
heavy = [name for name in ("cv2", "numpy") if name in sys.modules]
assert not heavy, f"launch imports {heavy}"
"""


class DaemonImportTest(unittest.TestCase):
    def test_loads_without_uv_driver(self):
        result = subprocess.run([sys.executable, "-c", WITHOUT_USB], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr[-400:])

    def test_launch_spawns_before_heavy_imports(self):
        result = subprocess.run([sys.executable, "-c", LAUNCH_IS_LIGHT], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr[-400:])


if __name__ == "__main__":
    unittest.main()
