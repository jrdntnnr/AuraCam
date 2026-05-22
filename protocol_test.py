#!/usr/bin/env python3
"""Test alternate protocol commands on the supercamera."""

import usb.core
import usb.util
import time
import sys
from PIL import Image
import io

EP_OUT = 0x01
EP_IN = 0x81
EP_IAP_OUT = 0x02
EP_IAP_IN = 0x82

MAGIC_INIT = bytes([0xFF, 0x55, 0xFF, 0x55, 0xEE, 0x10])
JPEG_SOI = bytes([0xFF, 0xD8])
JPEG_EOI = bytes([0xFF, 0xD9])

# Commands found in APK
CMDS = {
    "connect_type1":    bytes([0xBB, 0xAA, 0x05, 0x00, 0x00]),  # current
    "connect_type0":    bytes([0xBB, 0xAA, 0x06, 0x00, 0x00]),  # alternate
    "disconnect_type1": bytes([0xBB, 0xAA, 0x06, 0x00, 0x00]),
    "disconnect_type0": bytes([0xBB, 0xAA, 0x08, 0x00, 0x00]),
    "change_cam1":      bytes([0xBB, 0xAA, 0x0B, 0x00, 0x02, 0x01, 0x08, 0x00]),
    "change_cam2":      bytes([0xBB, 0xAA, 0x0B, 0x00, 0x02, 0x02, 0x08, 0x00]),
}


def open_device():
    dev = usb.core.find(idVendor=0x2ce3, idProduct=0x3828)
    if dev is None:
        print("Camera not found!")
        sys.exit(1)
    for intf in [0, 1]:
        try:
            if dev.is_kernel_driver_active(intf):
                dev.detach_kernel_driver(intf)
        except Exception:
            pass
    dev.set_configuration()
    usb.util.claim_interface(dev, 0)
    usb.util.claim_interface(dev, 1)
    # Drain iAP
    for _ in range(30):
        try:
            dev.read(EP_IAP_IN, 512, timeout=100)
        except usb.core.USBError:
            break
    dev.set_interface_altsetting(interface=1, alternate_setting=1)
    return dev


def send_init(dev):
    dev.write(EP_IAP_OUT, MAGIC_INIT, timeout=1000)


def send_cmd(dev, cmd_bytes, label=""):
    print(f"  Sending {label}: {cmd_bytes.hex()}")
    dev.write(EP_OUT, cmd_bytes, timeout=1000)


def read_frame(dev, timeout=5.0):
    """Read one JPEG frame. Returns (jpeg_bytes, raw_headers)."""
    buf = bytearray()
    in_frame = False
    deadline = time.monotonic() + timeout
    headers_seen = []

    while time.monotonic() < deadline:
        try:
            data = bytes(dev.read(EP_IN, 65536, timeout=1000))
        except usb.core.USBError:
            continue

        payload = data
        if len(data) >= 12 and data[0] == 0xAA and data[1] == 0xBB:
            headers_seen.append(data[:12])
            payload = data[12:]

        soi_pos = payload.find(JPEG_SOI)
        if soi_pos >= 0 and not in_frame:
            in_frame = True
            buf = bytearray(payload[soi_pos:])
        elif in_frame:
            buf.extend(payload)

        if in_frame:
            eoi_pos = buf.find(JPEG_EOI)
            if eoi_pos >= 0:
                return bytes(buf[:eoi_pos + 2]), headers_seen

    return None, headers_seen


def analyze_frame(jpeg, label):
    if jpeg is None:
        print(f"  {label}: No frame received")
        return
    try:
        img = Image.open(io.BytesIO(jpeg))
        w, h = img.size
        ratio = w / h
        print(f"  {label}: {w}x{h} (ratio {ratio:.2f}), {len(jpeg)} bytes")
        img.save(f"test_{label}.jpg")
        print(f"  Saved: test_{label}.jpg")
    except Exception as e:
        print(f"  {label}: Bad JPEG ({len(jpeg)} bytes) - {e}")


def release_device(dev):
    try:
        dev.set_interface_altsetting(interface=1, alternate_setting=0)
    except Exception:
        pass
    for intf in [1, 0]:
        try:
            usb.util.release_interface(dev, intf)
        except Exception:
            pass
    try:
        dev.reset()
    except Exception:
        pass


def test_connect_command(cmd_name, connect_cmd):
    """Full cycle: init, connect, read frames, disconnect, release."""
    print(f"\n{'='*60}")
    print(f"TEST: {cmd_name}")
    print(f"{'='*60}")

    dev = open_device()
    send_init(dev)
    send_cmd(dev, connect_cmd, cmd_name)
    time.sleep(0.3)

    # Skip first frame (known corrupt)
    print("  Skipping first frame...")
    read_frame(dev, timeout=3.0)

    # Read 3 frames
    for i in range(3):
        jpeg, headers = read_frame(dev, timeout=3.0)
        analyze_frame(jpeg, f"{cmd_name}_frame{i}")
        if headers:
            h = headers[0]
            print(f"  Header: {h.hex()}")

    release_device(dev)
    time.sleep(1)


def test_camera_switch():
    """Connect, then try changeCamera commands."""
    print(f"\n{'='*60}")
    print(f"TEST: Camera switch commands")
    print(f"{'='*60}")

    dev = open_device()
    send_init(dev)
    send_cmd(dev, CMDS["connect_type1"], "connect_type1")
    time.sleep(0.3)

    # Skip first frame
    read_frame(dev, timeout=3.0)

    # Read baseline frame
    jpeg, _ = read_frame(dev, timeout=3.0)
    analyze_frame(jpeg, "before_switch")

    # Try changeCamera command (cam2)
    print("\n  Switching to camera 2...")
    send_cmd(dev, CMDS["change_cam2"], "change_cam2")
    time.sleep(1.0)

    # Read frames after switch
    for i in range(3):
        jpeg, headers = read_frame(dev, timeout=3.0)
        analyze_frame(jpeg, f"after_switch_frame{i}")

    # Try switching back
    print("\n  Switching back to camera 1...")
    send_cmd(dev, CMDS["change_cam1"], "change_cam1")
    time.sleep(1.0)

    for i in range(3):
        jpeg, headers = read_frame(dev, timeout=3.0)
        analyze_frame(jpeg, f"back_to_cam1_frame{i}")

    release_device(dev)
    time.sleep(1)


if __name__ == "__main__":
    print("Supercamera Protocol Test")
    print("=" * 60)

    # Test 1: Standard connect (baseline)
    test_connect_command("connect_type1", CMDS["connect_type1"])

    # Test 2: Alternate connect command
    test_connect_command("connect_type0", CMDS["connect_type0"])

    # Test 3: Camera switch commands
    test_camera_switch()

    print("\n\nAll tests complete. Check test_*.jpg files.")
