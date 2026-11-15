# AuraCam on Cardputer Zero

The device frontend follows M5's LVGL 9.5 application template: 320x170
framebuffer, keyboard input, five bottom actions on keys 4-8, and hold Esc to
exit to APPLaunch. The Python capture process exits with the app and finalizes
recording on normal exit.

| Key | Capture screen | Menu |
|---|---|---|
| 4 | Menu | Back |
| 5 | Snapshot | Cycle recorded HUD |
| 6 | Record/stop | Threshold -0.5 C |
| 7 | RGB/UV source | Threshold +0.5 C |
| 8 | Aura mode | Rotate thermal |

Source switching requires stopping recording. RGB uses the onboard IMX219 via
Picamera2; UV retains the proprietary USB driver. Both feed the existing
compositor and H.264 recorder. Captures are in `~/Pictures/auracam` and device
settings in `~/.config/auracam/cardputer.json`. The preview is 192x144 with a
telemetry column and bottom action bar; captures retain 640x480 resolution.

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
peripherals. This port starts thermal refresh at 8 Hz and preserves the vendor's
bus clock.

Run the hardware smoke test from the repository root:

```sh
PYTHONPATH=. python3 cardputer/smoke.py
```

References: [M5 template](https://github.com/CardputerZero/Template),
[device specification](https://docs.m5stack.com/en/CardputerZero).
