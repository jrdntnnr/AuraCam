import unittest

from auracam.daemon import AuraDaemon


class ControlRequestTest(unittest.TestCase):
    def setUp(self):
        self.daemon = AuraDaemon.__new__(AuraDaemon)
        self.daemon.paused = False

    def test_pause_off_is_not_coerced_to_true(self):
        response = self.daemon._handle({"command": "pause", "action": "off"})

        self.assertFalse(response["paused"])

    def test_invalid_pause_action_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "pause action"):
            self.daemon._handle({"command": "pause", "action": "invalid"})

    def test_invalid_record_action_is_rejected_before_dispatch(self):
        with self.assertRaisesRegex(ValueError, "record action"):
            self.daemon._handle({"command": "record", "action": "invalid"})


if __name__ == "__main__":
    unittest.main()
