# AuraCam on Cardputer Zero

The device frontend follows M5's LVGL 9.5 application template: 320x170
framebuffer, keyboard input, five bottom actions on keys 4-8, and hold Esc for
3 s to exit to APPLaunch. The Python capture process exits with the app and finalizes
recording on normal exit.

| Key | Capture screen | Menu |
|---|---|---|
| 4 | Menu | Back |
| 5 | Snapshot | Camera look: natural, mono, hicon, fast |
| 6 | Record/stop | Wide field of view on/off |
| 7 | HUD mode: off, minimal, tactical | Calibrate thermal frame |
| 8 | Aura mode | IR: thermal colors and threshold |

The Cardputer always uses the onboard IMX219 through Picamera2 (the bridge
forces `image_source` to `rgb` at start); the USB UV driver remains for the
Pi Zero build. Both feed the existing compositor and H.264 recorder. Captures are in `~/Pictures/auracam` and device
settings in `~/.config/auracam/cardputer.json`. The screen uses the HUD's
5x7 pixel font and amber palette: a centered 192x144 preview with probe, high
and low markers, rates and mode on the left, temperatures on the right.
Calibrate shows the thermal grid. F, Z, X, C (the Cardputer's arrows) move
the thermal frame, 5/6 zoom it out/in keeping its aspect, 7 switches fine (2 px,
1 %) and coarse (10 px, 5 %) steps, 4 saves and 8 restores the values from when
calibration began. Calibrate in the normal (not wide) view.

IR: 5 cycles the thermal gradient (aura, ironbow, amber, whitehot, turbo,
arctic; the name shows in the header), 6/7 lower/raise the threshold and 8
switches the step between 0.5 C and 2 C.

Camera looks are IMX219 ISP controls (no CPU cost): mono is zero
saturation, hicon raises contrast and sharpening with highlight-priority
exposure, fast prefers short shutters. Wide switches the sensor from the
640x480 centre crop to the full 1640x1232 binned array and shrinks the
thermal overlay by the crop ratio (about 0.39) so it stays registered; the
overlay calibration (`scale_*`, `offset_*`) is always stored for the crop.

Snapshots and recordings burn in the selected HUD mode at 640x480 (none when
off); the screen shows the same mode's markers on a clean preview. Regenerate the font after editing the HUD
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
sudo install -m 644 cardputer/auracam.png /usr/share/APPLaunch/share/images/
sudo install -m 644 cardputer/aura-cardputer.desktop /usr/share/APPLaunch/applications/
systemctl --user restart APPLaunch.service
```

APPLaunch reads the applications directory only at startup, so the restart (or
a reboot) is what makes the entry appear in the carousel.

The thermal module sits on the top EXT port, which carries I2C1 (`/dev/i2c-1`,
shared with the keyboard and the M5IOE1 expander) and a switched 5 V output.
`launch.sh` turns that output on through `/sys/class/leds/ext_5v_out`; without
it the sensor is unpowered and `aura doctor` reports no device at `0x33`. The
Grove port is routed to its UART pins (see 8ANGLE knobs). Do not apply the Pi Zero installation script to
this device: it changes global I2C settings shared with the keyboard and onboard
peripherals.

The bus runs at the Pi default 100 kHz, which limits the MLX90640 to about
4 frames per second. For 16 Hz raise it to 400 kHz (every peer on bus 1
supports Fast-mode) and reboot:

```sh
sudo scripts/set_i2c_baud.sh 400000 && sudo reboot
```

A first run writes `refresh_hz` 16 and `host_fps_cap` 24 into
`~/.config/auracam/cardputer.json`; the preview is encoded at the panel's
192x144 so the daemon does not JPEG a 640x480 frame per preview.

A first run also starts in the wide view with the Cardputer's thermal
alignment (offset 64, -60, zoom 1.69, thermal rotated 180 and mirrored).

## 8ANGLE knobs

Plug an M5Stack 8ANGLE into the 4-pin Grove port on the side of the device,
not the top EXT header. It stretches the I2C clock,
which locks the Pi's hardware bus, so it runs on its own bit-banged bus on
the port's UART pins (GPIO14/15). Once, then reboot:

```sh
sudo sed -i "s/^enable_uart=1/enable_uart=0/" /boot/firmware/config.txt
echo "dtoverlay=i2c-gpio,bus=3,i2c_gpio_sda=14,i2c_gpio_scl=15,i2c_gpio_delay_us=2" \
  | sudo tee -a /boot/firmware/config.txt
```

AuraCam powers the port and keeps it in UART mode. A knob takes over its
setting only once turned past the current value.

| Knob | Sets | Range |
|------|------|-------|
| 1 | threshold | 15-45 C |
| 2 | thermal opacity | 0-1 |
| 3 | range low | 0-30 C |
| 4 | range high | 32-60 C |
| 5 | blur | 0-30 |
| 6 | smoothing | 0-0.95 |
| 7 | camera exposure | -2 to +2 EV |
| 8 | contrast | 0.5-2 |

Switch up enters calibration: knobs 1-3 move X, Y and zoom with the grid
shown. Switch down saves. The unit's LEDs stay off; writing them hangs
firmware 1.

Run the hardware smoke test from the repository root:

```sh
PYTHONPATH=. python3 cardputer/smoke.py
```

References: [M5 template](https://github.com/CardputerZero/Template),
[device specification](https://docs.m5stack.com/en/CardputerZero).
