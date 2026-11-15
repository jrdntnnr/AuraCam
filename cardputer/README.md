# AuraCam on Cardputer Zero

The device frontend follows M5's LVGL 9.5 application template: 320x170
framebuffer, keyboard input, five bottom actions on keys 4-8, and hold Esc to
exit to APPLaunch. The Python capture process exits with the app and finalizes
recording on normal exit.

| Key | Capture screen | Menu |
|---|---|---|
| 4 | Menu | Back |
| 5 | Snapshot | HUD palette |
| 6 | Record/stop | Threshold -0.5 C |
| 7 | Screen markers: tactical, off, minimal | Threshold +0.5 C |
| 8 | Aura mode | Rotate thermal |

The Cardputer always uses the onboard IMX219 through Picamera2 (the bridge
forces `image_source` to `rgb` at start); the USB UV driver remains for the
Pi Zero build. Both feed the existing compositor and H.264 recorder. Captures are in `~/Pictures/auracam` and device
settings in `~/.config/auracam/cardputer.json`. The screen uses the HUD's
5x7 pixel font and amber palette: a centered 192x144 preview with probe, high
and low markers, rates and mode on the left, temperatures on the right.
Telemetry is drawn beside the preview, so the bridge keeps `hud_mode` off and
captures stay clean at 640x480. Regenerate the font after editing the HUD
glyphs with `scripts/gen_pixel_font.py`.

Build on the Cardputer from the repository root:

```sh
sh scripts/build_native.sh
cmake -S cardputer -B cardputer/build -DCMAKE_BUILD_TYPE=Release
cmake --build cardputer/build -j2
sh cardputer/launch.sh
```

The provided launcher entry assumes installation at `/home/zero/auracam`.
Install it after building:

```sh
chmod +x cardputer/launch.sh
sudo install -m 644 cardputer/aura-cardputer.desktop /usr/share/APPLaunch/applications/
systemctl --user restart APPLaunch.service
```

APPLaunch reads the applications directory only at startup, so the restart (or
a reboot) is what makes the entry appear in the carousel.

The thermal module sits on the top EXT port, which carries I2C1 (`/dev/i2c-1`,
shared with the keyboard and the M5IOE1 expander) and a switched 5 V output.
`launch.sh` turns that output on through `/sys/class/leds/ext_5v_out`; without
it the sensor is unpowered and `aura doctor` reports no device at `0x33`. The
Grove port shares the same bus. Do not apply the Pi Zero installation script to
this device: it changes global I2C settings shared with the keyboard and onboard
peripherals.

The bus runs at the Pi default 100 kHz, which limits the MLX90640 to about
4 frames per second. For 16 Hz raise it to 400 kHz (every peer on bus 1
supports Fast-mode) and reboot:

```sh
sudo scripts/set_i2c_baud.sh 400000 && sudo reboot
```

A first run writes `refresh_hz` 16 and `host_fps_cap` 15 into
`~/.config/auracam/cardputer.json`; the preview is encoded at the panel's
192x144 so the daemon does not JPEG a 640x480 frame per preview.

Run the hardware smoke test from the repository root:

```sh
PYTHONPATH=. python3 cardputer/smoke.py
```

References: [M5 template](https://github.com/CardputerZero/Template),
[device specification](https://docs.m5stack.com/en/CardputerZero).
