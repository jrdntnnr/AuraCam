"""M5Stack 8ANGLE unit: eight 12-bit knobs and a toggle switch over I2C.

On the Cardputer Zero the unit sits on the Grove port in UART mode, where the
i2c-gpio overlay turns GPIO14/15 into /dev/i2c-3. It stretches the clock,
which the Pi's hardware I2C mishandles, so it must never share the main bus.

    reg 0x00-0x0F  knob 0-7, 12-bit little-endian
    reg 0x20       switch, 0 or 1
    reg 0xFE       firmware version

Writing the LED registers (0x30+) hangs firmware 1, so LEDs stay unused.
"""

from __future__ import annotations

import fcntl
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

BUS = Path("/dev/i2c-3")
ADDRESS = 0x43
I2C_SLAVE = 0x0703  # linux/i2c-dev.h
KNOB_COUNT = 8
KNOB_MAX = 4095
REG_SWITCH = 0x20
REG_FIRMWARE = 0xFE

# The unit drops transactions sent back to back; 1 ms apart is reliable.
SETTLE_S = 0.001
POLL_S = 0.05
RETRY_S = 2.0
FAILURES_BEFORE_RESET = 3

GROVE_POWER = Path("/sys/class/leds/grove_5v_out/brightness")
GROVE_FUNCTION = Path("/sys/class/leds/grove_fun/brightness")
GROVE_UART = "0"
POWER_OFF_S = 0.5
POWER_ON_S = 1.0


@dataclass(frozen=True)
class Reading:
    knobs: tuple[float, ...]  # 0.0-1.0, rising clockwise
    switch: bool


class Angle8:
    def __init__(self, bus: Path = BUS):
        self._fd = os.open(bus, os.O_RDWR)
        try:
            fcntl.ioctl(self._fd, I2C_SLAVE, ADDRESS)
        except OSError:
            os.close(self._fd)
            raise

    def _read(self, register: int, count: int) -> bytes:
        # Stop between the register write and the read: the unit hangs on a
        # repeated start.
        os.write(self._fd, bytes([register]))
        time.sleep(SETTLE_S)
        data = os.read(self._fd, count)
        time.sleep(SETTLE_S)
        return data

    def firmware(self) -> int:
        return self._read(REG_FIRMWARE, 1)[0]

    def read(self) -> Reading:
        # One knob per transaction: burst reads stall the unit.
        knobs = []
        for channel in range(KNOB_COUNT):
            raw = int.from_bytes(self._read(channel * 2, 2), "little")
            knobs.append(1.0 - min(raw, KNOB_MAX) / KNOB_MAX)
        return Reading(tuple(knobs), bool(self._read(REG_SWITCH, 1)[0]))

    def close(self) -> None:
        os.close(self._fd)


def _write(path: Path, value: str) -> None:
    try:
        path.write_text(value)
    except OSError:
        pass


def power_grove() -> None:
    """Grove 5 V on, port routed to the UART pins (keeps it off I2C1)."""
    _write(GROVE_FUNCTION, GROVE_UART)
    _write(GROVE_POWER, "1")


def reset_grove() -> None:
    """A hung unit holds SCL low until its power is cycled."""
    _write(GROVE_POWER, "0")
    time.sleep(POWER_OFF_S)
    _write(GROVE_POWER, "1")
    time.sleep(POWER_ON_S)


class KnobPoller:
    """Reads the unit on a thread; `latest` is None while it is absent."""

    def __init__(self, open_unit=Angle8):
        self._open_unit = open_unit
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="angle8", daemon=True)
        self.latest: Reading | None = None
        self.firmware: int | None = None

    def start(self) -> None:
        power_grove()
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)

    def _run(self) -> None:
        unit = None
        failures = 0
        while not self._stop.is_set():
            # Open (or reopen) the bus; absent overlay or unit retries slowly.
            if unit is None:
                try:
                    unit = self._open_unit()
                    self.firmware = unit.firmware()
                except OSError:
                    self._drop(unit)
                    unit = None
                    self._stop.wait(RETRY_S)
                    continue

            try:
                self.latest = unit.read()
                failures = 0
            except OSError:
                failures += 1
                if failures >= FAILURES_BEFORE_RESET:
                    self._drop(unit)
                    unit = None
                    failures = 0
                    reset_grove()
                    continue
            self._stop.wait(POLL_S)
        self._drop(unit)

    def _drop(self, unit) -> None:
        self.latest = None
        self.firmware = None
        if unit is not None:
            unit.close()
