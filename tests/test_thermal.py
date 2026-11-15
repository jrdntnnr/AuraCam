import time
import unittest
from types import SimpleNamespace

import numpy as np

from auracam.thermal import ThermalFrame, ThermalWorker


class _OneFrameThenFailSensor:
    def __init__(self):
        self.reads = 0

    def open(self, refresh_hz):
        return None

    def set_refresh(self, refresh_hz):
        return refresh_hz

    def read(self, emissivity, reflected_offset):
        self.reads += 1
        if self.reads > 1:
            raise RuntimeError("simulated I2C disconnect")
        field = np.full((24, 32), 30.0, dtype=np.float32)
        return ThermalFrame(
            temperatures=field,
            image=field,
            timestamp_ns=time.monotonic_ns(),
            subpage=0,
            ambient=24.0,
            vdd=3.3,
            complete=True,
            sequence=1,
        )

    def close(self):
        return None


class ThermalWorkerTest(unittest.TestCase):
    def test_disconnect_clears_stale_frame_and_fps_history(self):
        sensor = _OneFrameThenFailSensor()
        config = SimpleNamespace(
            refresh_hz=4.0,
            emissivity=0.95,
            reflected_offset=8.0,
        )
        worker = ThermalWorker(lambda: config, sensor_factory=lambda: sensor)
        worker.start()
        deadline = time.monotonic() + 1.0
        while worker.errors == 0 and time.monotonic() < deadline:
            time.sleep(0.01)
        worker.stop()

        self.assertGreaterEqual(worker.errors, 1)
        self.assertFalse(worker.connected)
        self.assertIsNone(worker.latest())
        self.assertEqual(worker.fps, 0.0)


if __name__ == "__main__":
    unittest.main()
