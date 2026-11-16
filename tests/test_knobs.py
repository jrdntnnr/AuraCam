import unittest
from unittest.mock import MagicMock

from auracam.angle8 import KnobPoller, Reading
from auracam.knobs import Binding, Knob, KnobDeck, Layer


def config(**values):
    base = {
        "threshold": 26.0, "max_alpha": 0.58, "thermal_min": 20.0, "thermal_max": 38.0,
        "blur": 9.0, "smoothing": 0.35, "exposure_ev": 0.0, "contrast": 1.0,
        "offset_x": 64, "offset_y": -60, "scale_x": 1.69, "scale_y": 1.69,
    }
    return {**base, **values}


class KnobTest(unittest.TestCase):
    def test_far_knob_waits_for_pickup(self):
        knob = Knob(Binding("threshold", 15.0, 45.0, 1))
        self.assertIsNone(knob.update(0.1, 26.0))  # 18.0
        self.assertIsNone(knob.update(0.2, 26.0))  # 21.0, not reached yet
        self.assertEqual(knob.update(0.5, 26.0), 30.0)  # crossed 26.0

    def test_near_knob_engages_without_jump(self):
        knob = Knob(Binding("threshold", 15.0, 45.0, 1))
        self.assertIsNone(knob.update(11 / 30, 26.0))  # at the value
        self.assertEqual(knob.update(0.4, 26.0), 27.0)

    def test_outside_change_releases(self):
        knob = Knob(Binding("threshold", 15.0, 45.0, 1))
        knob.update(11 / 30, 26.0)
        knob.update(0.4, 26.0)  # sent 27.0
        self.assertIsNone(knob.update(0.45, 40.0))  # preset jumped to 40
        self.assertFalse(knob.engaged)

    def test_jitter_ignored(self):
        knob = Knob(Binding("max_alpha", 0.0, 1.0, 2))
        knob.update(0.5, 0.5)
        self.assertIsNone(knob.update(0.502, 0.5))

    def test_integer_binding(self):
        knob = Knob(Binding("offset_x", -160, 160, 0))
        knob.update(0.7, 64)
        value = knob.update(0.75, 64)
        self.assertEqual(value, 80)
        self.assertIsInstance(value, int)


class DeckTest(unittest.TestCase):
    def test_capture_layer_sets_threshold(self):
        deck = KnobDeck()
        positions = [11 / 30, 0, 0, 0, 0, 0, 0, 0]
        deck.changes(positions, config(), Layer.CAPTURE)
        positions[0] = 0.5
        self.assertEqual(deck.changes(positions, config(), Layer.CAPTURE), [("threshold", 30.0)])

    def test_calibrate_zoom_sets_both_axes(self):
        deck = KnobDeck()
        positions = [0, 0, (1.69 - 0.5) / 2, 0, 0, 0, 0, 0]
        deck.changes(positions, config(), Layer.CALIBRATE)
        positions[2] = 0.7
        self.assertEqual(
            deck.changes(positions, config(), Layer.CALIBRATE),
            [("scale_x", 1.9), ("scale_y", 1.9)],
        )

    def test_layer_change_releases_rebound_knobs(self):
        deck = KnobDeck()
        positions = [11 / 30, 0, 0, (38 - 32) / 28, 0, 0, 0, 0]
        deck.changes(positions, config(), Layer.CAPTURE)
        deck.changes(positions, config(), Layer.CALIBRATE)
        self.assertFalse(deck.knobs[0].engaged)
        self.assertTrue(deck.knobs[3].engaged)


class PollerTest(unittest.TestCase):
    def test_reads_unit(self):
        unit = MagicMock()
        unit.firmware.return_value = 1
        reading = Reading((0.5,) * 8, False)
        poller = KnobPoller(open_unit=lambda: unit)

        def read():
            poller._stop.set()
            return reading

        unit.read.side_effect = read
        poller._run()
        unit.close.assert_called_once()
        self.assertIsNone(poller.latest)  # cleared on stop


if __name__ == "__main__":
    unittest.main()
