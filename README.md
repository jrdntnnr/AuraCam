# UV Camera / Supercamera GUI

A touch-friendly Linux viewer and capture application for USB cameras that use
the proprietary `com.useeplus.protocol`, including devices identified as
`2ce3:3828` ("Geek szitman supercamera") and `0329:2022`.

These devices are not standard UVC cameras, so applications such as guvcview
and qv4l2 cannot open them directly. This project talks to their vendor-specific
USB bulk endpoints and provides a native desktop interface.

## Features

- Live preview with a configurable host-side FPS cap
- Portrait-first operation with correct 0°, 90°, 180° and 270° transforms
- Lossless rotation and mirroring of the camera's original JPEG stream
- Brightness, contrast, saturation, sharpness, gamma, zoom and image effects
- Native JPEG snapshots and processed/upscaled JPEG output
- Portrait-aware MP4 recording without cropping
- Timelapse capture with interval, shot limit, duration and output-FPS controls
- Optional automatic MP4 construction after a timelapse
- Dual-stream/lens switching and physical capture-button events
- Automatic, atomic persistence of every editable setting
- Compact fullscreen interface suitable for a Raspberry Pi touchscreen

Settings are stored in `~/.config/uv-camera/settings.json`. Captures are stored
in `~/Pictures/supercamera/`.

## Camera limitations

The tested hardware sends baseline JPEG frames at a native resolution of
640×480, at up to approximately 30 frames per second. The known protocol does
not expose sensor exposure, gain, focus, white balance, LED or true sensor-FPS
controls. The FPS setting in the GUI is therefore a host-side processing cap,
not a sensor command.

"Maximum: preserve device JPEG" is the highest-fidelity snapshot mode. It keeps
the camera's original JPEG coefficients and uses `jpegtran` for lossless
portrait rotation/mirroring. Upscaling cannot add sensor detail.

## Requirements

- Linux and Python 3.10+
- Tkinter
- libusb access through PyUSB
- `jpegtran` from libjpeg-turbo
- A compatible `com.useeplus.protocol` camera

On Debian, Ubuntu or Raspberry Pi OS:

```bash
sudo apt install python3-venv python3-tk libjpeg-turbo-progs
python3 -m venv .venv
.venv/bin/pip install supercamera pillow numpy opencv-python-headless
```

On Raspberry Pi OS, using the distribution OpenCV build can be quicker:

```bash
sudo apt install python3-opencv python3-numpy
python3 -m venv --system-site-packages .venv
.venv/bin/pip install supercamera pillow
```

## Device permissions

Install the included udev rules, reload them, then reconnect the camera:

```bash
sudo install -m 0644 99-supercamera.rules /etc/udev/rules.d/99-supercamera.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
```

The rules grant the active desktop user access through the `video` group and
`uaccess`; they do not make the device world-writable.

## Run

```bash
.venv/bin/python camera_gui.py
```

Keyboard shortcuts:

| Key | Action |
| --- | --- |
| `S` | Save a snapshot |
| `R` | Start or stop MP4 recording |
| `T` | Start or stop a timelapse |
| `Space` | Pause or resume preview |
| `F11` | Toggle fullscreen |
| `Esc` | Leave fullscreen |
| `Q` | Quit |

## Output

- Snapshots: `~/Pictures/supercamera/snap_<timestamp>_<size>.jpg`
- Recordings: `~/Pictures/supercamera/rec_<timestamp>_<size>.mp4`
- Timelapses: one `timelapse_<timestamp>/` directory per run, containing the
  source JPEG frames and optionally `timelapse.mp4`

The Full HD option letterboxes aspect-ratio differences instead of cropping the
4:3 sensor image. Native portrait output is 480×640.

## Protocol notes

The camera uses vendor-specific bulk endpoints:

| Endpoint | Direction | Purpose |
| --- | --- | --- |
| `0x01` | OUT | Stream commands |
| `0x81` | IN | Wrapped JPEG stream |
| `0x02` | OUT | iAP-style initialization |
| `0x82` | IN | iAP-style data |

Known initialization sequence:

1. Drain endpoint `0x82`.
2. Select alternate setting 1 on interface 1.
3. Send `FF 55 FF 55 EE 10` to endpoint `0x02`.
4. Send `BB AA 05 00 00` to endpoint `0x01`.
5. Discard the first incomplete frame.

Image packets begin with a 12-byte wrapper whose first bytes are `AA BB`. The
wrapper carries frame, stream and physical-button metadata. `protocol_camera.py`
contains the application-facing implementation. `protocol_test.py` contains
research commands and may interrupt streaming; it is not needed to run the GUI.

## Credits

This project builds on the original
[supercamera-gui](https://github.com/JimmieDB/supercamera-gui), the
[Python supercamera driver](https://github.com/Revise-Robotics/supercamera-endoscope),
and the
[Geek Szitman C++ proof of concept](https://github.com/hbens/geek-szitman-supercamera).

## License

MIT. See `LICENSE`.
