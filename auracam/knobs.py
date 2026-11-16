"""What the 8ANGLE knobs set, with soft pickup.

Knobs are absolute, settings are not: a knob only takes over once its
position reaches the current value, so nothing jumps at launch or after a
key or mode preset changed the setting.

    value 26.0, knob at 18.0  -> ignored
    knob turned through 26.0  -> engaged, follows the knob
    MODE key resets threshold -> released until reached again
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

ZOOM = "zoom"  # both scale axes together

PICKUP_SPAN = 0.02  # within 2 % of the range counts as reached
DEADBAND_SPAN = 0.005  # ignore ADC jitter


@dataclass(frozen=True)
class Binding:
    name: str
    low: float
    high: float
    digits: int  # rounding; 0 sends integers


class Layer(Enum):
    CAPTURE = "capture"
    CALIBRATE = "calibrate"


_CAPTURE = (
    Binding("threshold", 15.0, 45.0, 1),
    Binding("max_alpha", 0.0, 1.0, 2),
    Binding("thermal_min", 0.0, 30.0, 1),
    Binding("thermal_max", 32.0, 60.0, 1),
    Binding("blur", 0.0, 30.0, 1),
    Binding("smoothing", 0.0, 0.95, 2),
    Binding("exposure_ev", -2.0, 2.0, 1),
    Binding("contrast", 0.5, 2.0, 2),
)

# Switch up: knobs 1-3 align the thermal frame.
_CALIBRATE = (
    Binding("offset_x", -160, 160, 0),
    Binding("offset_y", -160, 160, 0),
    Binding(ZOOM, 0.5, 2.5, 3),
    *_CAPTURE[3:],
)

BINDINGS = {Layer.CAPTURE: _CAPTURE, Layer.CALIBRATE: _CALIBRATE}


class Knob:
    def __init__(self, binding: Binding):
        self.binding = binding
        self._previous: float | None = None
        self._sent: float | None = None
        self.engaged = False

    def update(self, position: float, current: float) -> float | None:
        """New value to send, or None."""
        low, high, digits = self.binding.low, self.binding.high, self.binding.digits
        span = high - low
        target = round(low + position * span, digits)
        current = min(high, max(low, current))

        # Changed elsewhere (keys, mode preset): wait to be reached again.
        if self.engaged and self._sent is not None and abs(current - self._sent) > PICKUP_SPAN * span:
            self.engaged = False
            self._sent = None

        previous, self._previous = self._previous, target
        if not self.engaged:
            near = abs(target - current) <= PICKUP_SPAN * span
            crossed = previous is not None and (previous - current) * (target - current) < 0
            if not (near or crossed):
                return None
            self.engaged = True

        if abs(target - current) < DEADBAND_SPAN * span:
            return None
        self._sent = target
        return int(target) if digits == 0 else target


class KnobDeck:
    def __init__(self):
        self._layer = Layer.CAPTURE
        self.knobs = [Knob(binding) for binding in BINDINGS[self._layer]]

    def changes(self, positions, config: dict[str, Any], layer: Layer) -> list[tuple[str, Any]]:
        """(setting, value) pairs to apply for these knob positions."""
        if layer is not self._layer:
            # Rebound knobs start released.
            self._layer = layer
            self.knobs = [
                knob if knob.binding == binding else Knob(binding)
                for knob, binding in zip(self.knobs, BINDINGS[layer])
            ]

        updates = []
        for knob, position in zip(self.knobs, positions):
            name = knob.binding.name
            current = config["scale_x"] if name == ZOOM else config[name]
            value = knob.update(position, current)
            if value is None:
                continue
            if name == ZOOM:
                updates += [("scale_x", value), ("scale_y", value)]
            else:
                updates.append((name, value))
        return updates
