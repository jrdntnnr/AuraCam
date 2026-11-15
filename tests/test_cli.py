import unittest

from auracam.cli import _handle_key, build_parser


class CliParserTest(unittest.TestCase):
    def test_new_aura_controls_parse(self):
        parser = build_parser()
        self.assertEqual(parser.parse_args(["rotate-camera"]).command, "rotate-camera")
        self.assertEqual(
            parser.parse_args(["rotate-thermal"]).command, "rotate-thermal"
        )
        self.assertEqual(parser.parse_args(["grid", "off"]).action, "off")
        self.assertEqual(parser.parse_args(["thermal-grid"]).action, "toggle")
        self.assertEqual(parser.parse_args(["interp", "bilinear"]).value, "bilinear")
        hud = parser.parse_args(["hud", "tactical", "--palette", "amber"])
        self.assertEqual(hud.mode, "tactical")
        self.assertEqual(hud.palette, "amber")
        probe = parser.parse_args(["probe", "16", "12"])
        self.assertEqual((probe.x, probe.y), ("16", "12"))

    def test_hud_key_cycles_mode(self):
        class Client:
            def __init__(self):
                self.mode = "minimal"

            def request(self, command, **payload):
                if command == "config":
                    return {"config": {"hud_mode": self.mode}}
                self.mode = payload["value"]
                return {"value": self.mode}

        client = Client()
        handled, message = _handle_key(client, "u")
        self.assertTrue(handled)
        self.assertEqual(client.mode, "tactical")
        self.assertEqual(message, "HUD → tactical")


if __name__ == "__main__":
    unittest.main()
