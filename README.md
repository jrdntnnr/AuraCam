# Supercamera GUI

A Linux GUI for cheap USB endoscope cameras that use the proprietary "UseeePlus" protocol (vendor ID `2ce3:3828`, branded as "Geek szitman supercamera", Oasis, Depstech, and others).

These cameras are sold claiming 1080p but actually output 640x480. They don't present as standard UVC devices and only officially work with the "Usee Plus" Android/iOS app. This project provides a native Linux viewer with image filters, snapshots, and video recording.

## Features

- Live preview at configurable frame rate (1-30 FPS)
- 9 image filters: Sharpen, Sharp Plus, Detail, Edge Enhance, Hi Contrast, B&W, Warm, Cool
- Snapshot capture (JPEG)
- Video recording (MP4)
- Optional 1080p LANCZOS upscaling for saved images/video
- Horizontal mirror to match real-world view
- Filter name embedded in saved filenames

## Requirements

- Linux (tested on Ubuntu 22.04)
- Python 3.10+
- USB endoscope with vendor ID `2ce3:3828`

## Setup

### udev rule (required for non-root access)

```bash
echo 'SUBSYSTEM=="usb", ATTR{idVendor}=="2ce3", ATTR{idProduct}=="3828", MODE="0666"' | sudo tee /etc/udev/rules.d/99-supercamera.rules
sudo udevadm control --reload-rules
```

Unplug and replug the camera after adding the rule.

### Install dependencies

```bash
pipenv install
```

### Patch the supercamera library

The `supercamera` pip package has a bug where `clear_halt` crashes on some firmware variants. Apply this one-line fix:

```bash
# Find the installed camera.py
CAMPY=$(pipenv run python -c "import supercamera; import os; print(os.path.join(os.path.dirname(supercamera.__file__), 'camera.py'))")

# Patch clear_halt to catch errors
sed -i 's/dev.clear_halt(EP_OUT)/try:\n            dev.clear_halt(EP_OUT)\n        except usb.core.USBError:\n            pass/' "$CAMPY"
```

Or manually edit the file and wrap the `dev.clear_halt(EP_OUT)` call in a try/except.

## Usage

```bash
pipenv run python camera_gui.py
```

### Keyboard Shortcuts

| Key | Action |
|-----|--------|
| S | Save snapshot |
| R | Start/stop video recording |
| Space | Pause/resume preview |
| U | Toggle 1080p upscale for saves |
| F | Cycle through filters |
| Q | Quit |

### Output

All captures are saved to `~/Pictures/supercamera/`:
- Snapshots: `snap_YYYYMMDD_HHMMSS_480p.jpg` (or `1080p` with upscale)
- Videos: `rec_YYYYMMDD_HHMMSS_640x480.mp4` (or `1920x1080`)
- Filter name appended when active: `snap_20260402_153012_480p_Sharp_Plus.jpg`

## Protocol Details

The camera uses the `com.useeplus.protocol` over USB vendor-specific bulk endpoints:

| Endpoint | Direction | Purpose |
|----------|-----------|---------|
| 0x01 | OUT | Commands |
| 0x81 | IN | Video stream |
| 0x02 | OUT | Init (iAP) |
| 0x82 | IN | iAP data |

**Init sequence:**
1. Drain iAP endpoint
2. Set interface 1 alternate setting 1
3. Send `FF 55 FF 55 EE 10` to EP 0x02 (magic init)
4. Send `BB AA 05 00 00` to EP 0x01 (connect)
5. Skip first frame (always corrupt)

Frames are JPEG wrapped in 12-byte headers starting with `AA BB`.

## Protocol Test Tool

`protocol_test.py` exercises alternate protocol commands for research purposes. It tests the standard connect, alternate connect (`BB AA 06`), and camera switch commands.

## Compatible Devices

Any USB endoscope with:
- Vendor ID: `2ce3`, Product ID: `3828`
- Or Vendor ID: `0329`, Product ID: `2022`
- Product string containing "supercamera"
- Interface class 255, subclass 240 (vendor-specific)

Commonly sold under brands: Oasis, Depstech, and various unbranded Chinese endoscopes.

## License

MIT
