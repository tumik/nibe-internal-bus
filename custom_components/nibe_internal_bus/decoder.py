"""Value interpretation for the Nibe internal RS-485 bus.

The two-byte slots in the SLAVE 0x90..0x93 replies are **raw unsigned 10-bit
ADC counts** (little-endian). Thermistor inputs are converted exactly like the
pump's display does it: ``NTC_X10[raw]`` (the firmware's own 1024-entry lookup
table, degC x 10), then a range check of -60.0 .. +170.0 degC. Outside that
range the firmware stores a "sensor fault" sentinel (0x8000 low / 0x8001 high);
here such a value simply decodes to nothing (the entity goes unavailable).

Three slots are digital protection inputs instead of thermistors, with the
firmware's thresholds ("raw > 300" / "raw < 300"):

* 0x93 slot 0, raw < 300 -> HP (high pressure) alarm input
* 0x91 slot 7, raw > 300 -> LP (low pressure) alarm input
* 0x92 slot 0, raw > 300 -> TB (temperature limiter) alarm input
"""

from __future__ import annotations

from .fields import FIELD_SPECS
from .ntc_table import NTC_X10
from .protocol import Frame

ADC_MAX = 1023

# Firmware range check (FUN_20117D04): lo = -600, hi = 1700 (x10).
MIN_X10 = -600
MAX_X10 = 1700

DIGITAL_THRESHOLD = 300


def ntc_to_celsius(adc: int) -> float | None:
    """Convert a raw 10-bit NTC divider reading to degrees Celsius.

    Table lookup, no fitting. ``None`` for a raw value outside 0..1023 or whose
    temperature is outside -60.0..+170.0 degC (the firmware's fault sentinels).
    """
    if not 0 <= adc <= ADC_MAX:
        return None
    x10 = NTC_X10[adc]
    if not MIN_X10 <= x10 <= MAX_X10:
        return None
    return x10 / 10


def decode_adc(data: bytes) -> list[int]:
    """Read a payload as consecutive little-endian 16-bit ADC slots."""
    return [data[i] | (data[i + 1] << 8) for i in range(0, len(data) - 1, 2)]


def decode_frame(frame: Frame) -> dict[str, float | int]:
    """Decode every field defined for this frame's address/direction/command.

    Fields whose sensor reads out of range are omitted rather than reported
    as a bogus number.
    """
    if frame.address is None or not frame.checksum_ok or frame.acked is False:
        return {}

    adc: list[int] | None = None
    values: dict[str, float | int] = {}

    for spec in FIELD_SPECS:
        if (
            spec.address != frame.address
            or spec.direction != frame.direction
            or spec.cmd != frame.cmd
        ):
            continue

        if spec.kind in ("ntc", "din_gt", "din_lt", "adc"):
            if adc is None:
                adc = decode_adc(frame.data)
            if spec.index >= len(adc):
                continue
            raw = adc[spec.index]
            if spec.kind == "ntc":
                celsius = ntc_to_celsius(raw)
                if celsius is None:
                    continue
                values[spec.field_id] = celsius
            elif spec.kind == "din_gt":
                values[spec.field_id] = int(raw > DIGITAL_THRESHOLD)
            elif spec.kind == "din_lt":
                values[spec.field_id] = int(raw < DIGITAL_THRESHOLD)
            else:
                values[spec.field_id] = raw
        else:
            if spec.index >= len(frame.data):
                continue
            raw = frame.data[spec.index]
            values[spec.field_id] = raw if spec.bit is None else (raw >> spec.bit) & 1

    return values
