from __future__ import annotations

import argparse
import base64
import io
import json
import os
import select
import shutil
import socket
import subprocess
import sys
import termios
import time
import tty
from pathlib import Path
from typing import Any

from PIL import Image

from .control import DEFAULT_SOCKET, HUD_MODES, HUD_PALETTES, MODES

MODE_KEYS = {str(index + 1): mode for index, mode in enumerate(MODES)}


class AuraClient:
    def __init__(self, socket_path: str | None = None):
        self.socket_path = socket_path or os.environ.get(
            "AURACAM_SOCKET", DEFAULT_SOCKET
        )

    def request(self, command: str, **payload) -> dict[str, Any]:
        request = {"command": command, **payload}
        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection.settimeout(4.0)
        try:
            connection.connect(self.socket_path)
            connection.sendall(json.dumps(request).encode() + b"\n")
            response = b""
            while b"\n" not in response and len(response) < 3_000_000:
                chunk = connection.recv(65536)
                if not chunk:
                    break
                response += chunk
        finally:
            connection.close()
        result = json.loads(response.split(b"\n", 1)[0].decode("utf-8"))
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "AuraCam request failed"))
        return result


def _systemctl(*arguments: str) -> subprocess.CompletedProcess:
    command = ["systemctl", *arguments]
    if os.geteuid() != 0:
        command = ["sudo", "-n", *command]
    return subprocess.run(command, text=True, capture_output=True, check=False)


def ensure_service(client: AuraClient, wait_seconds: float = 30.0) -> None:
    try:
        client.request("status")
        return
    except (OSError, RuntimeError, json.JSONDecodeError):
        pass
    result = _systemctl("start", "auracam.service")
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Could not start auracam.service")
    deadline = time.monotonic() + wait_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            client.request("status")
            return
        except Exception as exc:
            last_error = exc
            time.sleep(0.25)
    raise RuntimeError(f"AuraCam did not become ready: {last_error}")


def _number(value: Any, digits: int = 1) -> str:
    return "--" if value is None else f"{value:.{digits}f}"


def print_status(status: dict[str, Any]) -> None:
    uv, thermal, output = status["uv"], status["thermal"], status["output"]
    config = status["config"]
    state = "PAUSED" if status["paused"] else "RUNNING"
    print(f"AuraCam {state}  mode={config['mode']}  uptime={status['uptime']:.0f}s")
    print(
        f"UV      {'connected' if uv['connected'] else 'offline':9}  "
        f"{uv['fps']:.1f} fps  frames={uv['frames']}  dropped={uv['dropped']}"
    )
    print(
        f"Thermal {'connected' if thermal['connected'] else 'offline':9}  "
        f"{thermal['fps']:.1f} subpages/s  {_number(thermal['min'])}–"
        f"{_number(thermal['max'])}°C  ambient={_number(thermal['ambient'])}°C  "
        f"sp={thermal['subpage']} seq={thermal['sequence']}  "
        f"refresh={thermal['refresh_hz']:.1f} Hz  I²C errors={thermal['errors']}"
    )
    print(
        f"Output  {output['fps']:.1f} fps  load={status['load_1m']:.2f}  "
        f"CAM ROT={config['camera_rotation']}°  IR ROT={config['thermal_rotation']}°  "
        f"HUD={config['hud_mode']}:{config['hud_palette']}"
    )
    print(
        f"Aura    GRID={'on' if config['grid'] else 'off'}  "
        f"INTERP={config['interpolation']}  THRESHOLD={config['threshold']:.1f}°C  "
        f"ALPHA GAIN={config['alpha_gain']:.2f}  MAX ALPHA={config['max_alpha']:.2f}  "
        f"BLUR={config['blur']:.1f}  TRAIL DECAY={config['trail_decay']:.3f}"
    )
    print(
        f"Register OFFSET X={config['offset_x']:+d}  OFFSET Y={config['offset_y']:+d}  "
        f"SCALE X={config['scale_x']:.2f}  SCALE Y={config['scale_y']:.2f}  "
        f"fine rot={config['rotation']:+.1f}°"
    )
    recording = status["recording"]
    if recording["active"]:
        detail = (
            f"{recording['seconds']:.1f}s / {recording['frames']} frames"
            f" → {recording['path']}"
        )
        if recording.get("dropped"):
            detail += f"  queue drops={recording['dropped']}"
        print(f"Recording {detail}")
    if uv["error"]:
        print(f"UV error: {uv['error']}")
    if thermal["error"]:
        print(f"Thermal error: {thermal['error']}")


def _terminal_image(jpeg: bytes, columns: int, rows: int) -> list[str]:
    image = Image.open(io.BytesIO(jpeg)).convert("RGB")
    max_width = max(16, columns)
    max_pixel_height = max(4, rows * 2)
    image.thumbnail((max_width, max_pixel_height), Image.Resampling.BILINEAR)
    if image.height % 2:
        image = image.crop((0, 0, image.width, image.height - 1))
    pixels = image.load()
    padding = " " * max(0, (columns - image.width) // 2)
    lines = []
    for y in range(0, image.height, 2):
        pieces = [padding]
        for x in range(image.width):
            top = pixels[x, y]
            bottom = pixels[x, y + 1]
            pieces.append(
                f"\x1b[38;2;{top[0]};{top[1]};{top[2]}m"
                f"\x1b[48;2;{bottom[0]};{bottom[1]};{bottom[2]}m▀"
            )
        pieces.append("\x1b[0m")
        lines.append("".join(pieces))
    return lines


def _tui_header(status: dict[str, Any], message: str) -> list[str]:
    config = status["config"]
    thermal, uv = status["thermal"], status["uv"]
    rec = "● REC" if status["recording"]["active"] else ""
    return [
        f" AuraCam  {config['mode'].upper():9} {rec:6}  UV {uv['fps']:4.1f} fps  "
        f"THERM {thermal['fps']:4.1f} sp/s  OUT {status['output']['fps']:4.1f} fps",
        f" {_number(thermal['min'])}–{_number(thermal['max'])}°C  ambient "
        f"{_number(thermal['ambient'])}°C  threshold {config['threshold']:.1f}°C  "
        f"α gain {config['alpha_gain']:.2f} max {config['max_alpha']:.2f}  "
        f"blur {config['blur']:.1f}  "
        f"I²C err {thermal['errors']}",
        f" CAM ROT {config['camera_rotation']:3d}°  IR ROT "
        f"{config['thermal_rotation']:3d}°  GRID "
        f"{'ON' if config['grid'] else 'OFF'}  INTERP {config['interpolation']}  "
        f"TRAIL {config['trail_decay']:.2f}",
        f" x={config['offset_x']:+d} y={config['offset_y']:+d}  "
        f"scale={config['scale_x']:.2f}×{config['scale_y']:.2f}  "
        f"fine={config['rotation']:+.1f}°  "
        f"palette={config['palette']}  HUD={config['hud_mode']}  {message}",
    ]


def _handle_key(client: AuraClient, key: str) -> tuple[bool, str]:
    try:
        if key in MODE_KEYS:
            mode = MODE_KEYS[key]
            client.request("mode", mode=mode)
            return True, f"mode → {mode}"
        commands = {
            "+": ("threshold", 0.5),
            "=": ("threshold", 0.5),
            "-": ("threshold", -0.5),
            "]": ("max_alpha", 0.05),
            "[": ("max_alpha", -0.05),
            "}": ("alpha_gain", 0.25),
            "{": ("alpha_gain", -0.25),
            ".": ("blur", 1.0),
            ",": ("blur", -1.0),
            "h": ("offset_x", -4),
            "l": ("offset_x", 4),
            "k": ("offset_y", -4),
            "j": ("offset_y", 4),
            "H": ("scale_x", -0.02),
            "L": ("scale_x", 0.02),
            "K": ("scale_y", -0.02),
            "J": ("scale_y", 0.02),
            "d": ("trail_decay", -0.02),
            "D": ("trail_decay", 0.02),
        }
        if key in commands:
            name, delta = commands[key]
            response = client.request("adjust", name=name, delta=delta)
            return True, f"{name} → {response['value']}"
        if key in ("o", "O"):
            source = "thermal" if key == "O" else "camera"
            response = client.request("rotate", source=source)
            return True, f"{source} rotation → {response['rotation']}°"
        if key == "g":
            response = client.request("toggle", name="grid")
            return True, f"grid → {'on' if response['value'] else 'off'}"
        if key == "b":
            config = client.request("config")["config"]
            interpolation = (
                "nearest" if config["interpolation"] == "bilinear" else "bilinear"
            )
            client.request("set", name="interpolation", value=interpolation)
            return True, f"interpolation → {interpolation}"
        if key == "s":
            return True, f"saved {client.request('snapshot')['path']}"
        if key == "r":
            response = client.request("record", action="toggle")
            return True, "recording" if response[
                "active"
            ] else f"saved {response['path']}"
        if key == " ":
            response = client.request("pause", action="toggle")
            return True, "paused" if response["paused"] else "resumed"
        if key == "c":
            client.request("lens", selector=1)
            return True, "lens switch requested"
        if key == "v":
            config = client.request("config")["config"]
            representation = (
                "image" if config["representation"] == "temperature" else "temperature"
            )
            client.request("set", name="representation", value=representation)
            return True, f"representation → {representation}"
        if key == "u":
            config = client.request("config")["config"]
            index = HUD_MODES.index(config["hud_mode"])
            hud_mode = HUD_MODES[(index + 1) % len(HUD_MODES)]
            client.request("set", name="hud_mode", value=hud_mode)
            return True, f"HUD → {hud_mode}"
    except Exception as exc:
        return True, f"error: {exc}"
    return False, ""


def interactive(client: AuraClient, preview_command: str = "preview") -> int:
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print_status(client.request("status"))
        return 0
    descriptor = sys.stdin.fileno()
    previous = termios.tcgetattr(descriptor)
    message = "q quit • 1–7 modes • +/- threshold • [] max α • {} α gain"
    last_sequence = -1
    try:
        tty.setcbreak(descriptor)
        sys.stdout.write("\x1b[?1049h\x1b[?25l")
        sys.stdout.flush()
        while True:
            if select.select([sys.stdin], [], [], 0)[0]:
                key = os.read(descriptor, 1).decode(errors="ignore")
                if key in ("q", "\x03"):
                    break
                handled, new_message = _handle_key(client, key)
                if handled:
                    message = new_message
            try:
                response = client.request(preview_command)
                status = response["status"]
                size = shutil.get_terminal_size((80, 32))
                lines = _tui_header(status, message)
                lines = [line[: size.columns] for line in lines]
                jpeg_text = response.get("jpeg")
                if jpeg_text:
                    available_rows = max(4, size.lines - len(lines) - 4)
                    lines.extend(
                        _terminal_image(
                            base64.b64decode(jpeg_text), size.columns, available_rows
                        )
                    )
                    last_sequence = response["sequence"]
                else:
                    source = "thermal" if preview_command == "thermal_preview" else "UV"
                    lines.extend(["", f" Waiting for the first {source} frame…"])
                label = (
                    "THERMAL ONLY"
                    if preview_command == "thermal_preview"
                    else "UV + AURA"
                )
                footer = [
                    f" {label} • 1 debug  2 clean  3 threshold  4 trail  5 pixel",
                    " 6 ghost  7 glitch • h/j/k/l move • H/J/K/L scale • ,/. blur",
                    " o CAM rotate • O IR rotate • g grid • b interp • d/D trail",
                    " s snapshot • r record • c lens • v values • u HUD • space pause • q quit",
                ]
                lines.extend(line[: size.columns] for line in footer)
                sys.stdout.write("\x1b[H\x1b[2J" + "\n".join(lines[: size.lines]))
                sys.stdout.flush()
            except Exception as exc:
                message = f"connection error: {exc}"
            time.sleep(0.22 if last_sequence >= 0 else 0.5)
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, previous)
        sys.stdout.write("\x1b[0m\x1b[?25h\x1b[?1049l")
        sys.stdout.flush()
    return 0


def doctor(client: AuraClient) -> int:
    checks: list[tuple[str, bool, str]] = []
    native = Path(__file__).with_name("native") / "libmlx90640.so"
    checks.append(("native Melexis library", native.exists(), str(native)))
    checks.append(("I²C bus", Path("/dev/i2c-1").exists(), "/dev/i2c-1"))
    checks.append(
        (
            "USB camera udev rules",
            Path("/etc/udev/rules.d/99-supercamera.rules").exists(),
            "/etc/udev/rules.d/99-supercamera.rules",
        )
    )
    try:
        status = client.request("status")
        checks.append(("AuraCam service", True, "control socket responding"))
        checks.append(
            (
                "UV camera",
                bool(status["uv"]["connected"]),
                status["uv"]["error"] or "connected",
            )
        )
        checks.append(
            (
                "MLX90640 0x33",
                bool(status["thermal"]["connected"]),
                status["thermal"]["error"] or "connected",
            )
        )
    except Exception as exc:
        checks.append(("AuraCam service", False, str(exc)))
    for name, ok, detail in checks:
        print(f"{'✓' if ok else '✗'} {name:24} {detail}")
    return 0 if all(ok for _, ok, _ in checks) else 1


def _print_config(config: dict[str, Any]) -> None:
    for name in sorted(config):
        print(f"{name:18} {config[name]}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aura",
        description=(
            "Control and preview AuraCam over SSH. With no command, open the "
            "live terminal UI."
        ),
    )
    parser.add_argument(
        "--socket",
        default=os.environ.get("AURACAM_SOCKET", DEFAULT_SOCKET),
        help=argparse.SUPPRESS,
    )
    sub = parser.add_subparsers(dest="command")
    for name in (
        "start",
        "stop",
        "restart",
        "status",
        "config",
        "snapshot",
        "doctor",
        "preview",
        "thermal",
        "rotate-camera",
        "rotate-thermal",
    ):
        sub.add_parser(name)
    mode = sub.add_parser("mode", help="set aura mode")
    mode.add_argument("name", choices=MODES)
    setting = sub.add_parser("set", help="change one persistent setting")
    setting.add_argument("name")
    setting.add_argument("value")
    adjust = sub.add_parser("adjust", help="adjust one numeric setting")
    adjust.add_argument("name")
    adjust.add_argument("delta", type=float)
    nudge = sub.add_parser("nudge", help="move overlay by pixels")
    nudge.add_argument("x", type=int)
    nudge.add_argument("y", type=int)
    scale = sub.add_parser("scale", help="set overlay width/height scale")
    scale.add_argument("x", type=float)
    scale.add_argument("y", type=float)
    grid = sub.add_parser("grid", aliases=["thermal-grid"], help="toggle thermal grid")
    grid.add_argument(
        "action", choices=("on", "off", "toggle"), default="toggle", nargs="?"
    )
    interpolation = sub.add_parser("interp", help="set or toggle interpolation")
    interpolation.add_argument(
        "value", choices=("nearest", "bilinear", "toggle"), default="toggle", nargs="?"
    )
    record = sub.add_parser("record", help="start or stop MP4 recording")
    record.add_argument(
        "action", choices=("start", "stop", "toggle"), default="toggle", nargs="?"
    )
    pause = sub.add_parser("pause")
    pause.add_argument(
        "action", choices=("on", "off", "toggle"), default="toggle", nargs="?"
    )
    lens = sub.add_parser("lens", help="switch physical UV lens/stream")
    lens.add_argument("selector", type=int, choices=(1, 2), default=1, nargs="?")
    hud = sub.add_parser("hud", help="set the composited telemetry HUD")
    hud.add_argument(
        "mode", choices=(*HUD_MODES, "toggle"), default="toggle", nargs="?"
    )
    hud.add_argument("--palette", choices=HUD_PALETTES)
    probe = sub.add_parser("probe", help="set the thermal probe cell")
    probe.add_argument("x", help="sensor x coordinate or center")
    probe.add_argument("y", nargs="?", help="sensor y coordinate")
    logs = sub.add_parser("logs", help="follow service logs")
    logs.add_argument("--no-follow", action="store_true")
    demo = sub.add_parser("demo", help="run synthetic camera and thermal sources")
    demo.add_argument("--socket", dest="demo_socket", default="/tmp/auracam-demo.sock")
    return parser


def _run_service(command: str) -> int:
    result = _systemctl(command, "auracam.service")
    if result.returncode:
        raise RuntimeError(result.stderr.strip())
    print(
        {
            "start": "AuraCam started",
            "stop": "AuraCam stopped",
            "restart": "AuraCam restarted",
        }[command]
    )
    return 0


def _run_demo(args: argparse.Namespace) -> int:
    demo_client = AuraClient(args.demo_socket)
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "auracam.daemon",
            "--demo",
            "--socket",
            args.demo_socket,
            "--config",
            "/tmp/auracam-demo-config.json",
            "--output",
            "/tmp/auracam-demo-captures",
        ]
    )
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try:
                status = demo_client.request("status")
                if status["frame_sequence"] >= 4 and status["thermal"]["sequence"] > 0:
                    break
            except Exception:
                pass
            time.sleep(0.2)
        return interactive(demo_client)
    finally:
        process.terminate()
        process.wait(timeout=5)


def _run_remote(args: argparse.Namespace, client: AuraClient) -> int:
    command = args.command
    if command in (None, "preview"):
        return interactive(client)
    if command == "thermal":
        return interactive(client, "thermal_preview")
    if command == "status":
        print_status(client.request("status"))
        return 0
    if command == "config":
        _print_config(client.request("config")["config"])
        return 0
    if command == "mode":
        print(f"mode → {client.request('mode', mode=args.name)['mode']}")
        return 0
    if command in ("set", "adjust"):
        payload = {"name": args.name, "value": args.value}
        if command == "adjust":
            payload = {"name": args.name, "delta": args.delta}
        result = client.request(command, **payload)
        print(f"{args.name} → {result['value']}")
        return 0
    if command == "nudge":
        x = client.request("adjust", name="offset_x", delta=args.x)["value"]
        y = client.request("adjust", name="offset_y", delta=args.y)["value"]
        print(f"overlay → ({x:+d}, {y:+d})")
        return 0
    if command == "scale":
        x = client.request("set", name="scale_x", value=args.x)["value"]
        y = client.request("set", name="scale_y", value=args.y)["value"]
        print(f"scale → {x:.2f} × {y:.2f}")
        return 0
    if command in ("rotate-camera", "rotate-thermal"):
        source = "camera" if command == "rotate-camera" else "thermal"
        response = client.request("rotate", source=source)
        print(f"{source} rotation → {response['rotation']}°")
        return 0
    if command in ("grid", "thermal-grid"):
        if args.action == "toggle":
            value = client.request("toggle", name="grid")["value"]
        else:
            value = client.request("set", name="grid", value=args.action)["value"]
        print(f"thermal grid → {'on' if value else 'off'}")
        return 0
    if command == "interp":
        value = args.value
        if value == "toggle":
            current = client.request("config")["config"]["interpolation"]
            value = "nearest" if current == "bilinear" else "bilinear"
        value = client.request("set", name="interpolation", value=value)["value"]
        print(f"interpolation → {value}")
        return 0
    if command == "snapshot":
        print(client.request("snapshot")["path"])
        return 0
    if command == "record":
        response = client.request("record", action=args.action)
        label = "recording → " if response["active"] else "saved → "
        print(label + str(response["path"]))
        return 0
    if command == "pause":
        paused = client.request("pause", action=args.action)["paused"]
        print("paused" if paused else "running")
        return 0
    if command == "lens":
        client.request("lens", selector=args.selector)
        print("lens switch requested")
        return 0
    if command == "hud":
        mode = args.mode
        if mode == "toggle":
            current = client.request("config")["config"]["hud_mode"]
            mode = HUD_MODES[(HUD_MODES.index(current) + 1) % len(HUD_MODES)]
        mode = client.request("set", name="hud_mode", value=mode)["value"]
        palette = None
        if args.palette is not None:
            palette = client.request(
                "set", name="hud_palette", value=args.palette
            )["value"]
        suffix = f" ({palette})" if palette else ""
        print(f"HUD → {mode}{suffix}")
        return 0
    if command == "probe":
        if args.x.lower() == "center" and args.y is None:
            x, y = 16, 12
        else:
            if args.y is None:
                raise ValueError("probe requires X Y or center")
            x, y = int(args.x), int(args.y)
        x = client.request("set", name="probe_x", value=x)["value"]
        y = client.request("set", name="probe_y", value=y)["value"]
        print(f"probe → ({x}, {y})")
        return 0

    raise ValueError(f"Unknown command: {command}")


def _dispatch(args: argparse.Namespace, client: AuraClient) -> int:
    if args.command in ("start", "stop", "restart"):
        return _run_service(args.command)
    if args.command == "logs":
        command = ["journalctl", "-u", "auracam.service", "-n", "100"]
        if not args.no_follow:
            command.append("-f")
        return subprocess.run(command).returncode
    if args.command == "demo":
        return _run_demo(args)
    if args.command == "doctor":
        return doctor(client)

    ensure_service(client)
    return _run_remote(args, client)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    client = AuraClient(args.socket)
    try:
        return _dispatch(args, client)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"aura: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
