"""Value interpretation for the Nibe internal RS-485 bus.

The two-byte slots in the SLAVE 0x90/0x91 replies are **raw unsigned 10-bit NTC
thermistor ADC counts, not scaled temperatures**:

    x       = ln(adc / (1023 - adc))          # = ln(R_thermistor / R_fixed)
    1/T[K]  = c0 + c1*x + c2*x^2 + c3*x^3     # Steinhart-Hart style
    degC    = 1/T[K] - 273.15

adc == 1023 is a full-scale reading, i.e. an OPEN CIRCUIT (sensor not fitted).
adc == 1 is a digital flag, not a temperature. Both decode to None.
"""

from __future__ import annotations

import math

from .fields import FIELD_SPECS, NTC_COEFFICIENTS
from .protocol import Frame

ADC_MAX = 1023

# Anything outside this decodes to None: real sensors on this pump span roughly
# -30..+120 degC, and the out-of-band raw values (1, 1023) land far outside it.
MIN_CELSIUS = -60.0
MAX_CELSIUS = 160.0


def ntc_to_celsius(adc: int, coefficients: tuple[float, ...]) -> float | None:
    """Convert a raw 10-bit NTC divider reading to degrees Celsius."""
    if not 0 < adc < ADC_MAX:
        return None
    x = math.log(adc / (ADC_MAX - adc))
    inv_kelvin = sum(c * x**i for i, c in enumerate(coefficients))
    if inv_kelvin <= 0:
        return None
    celsius = 1.0 / inv_kelvin - 273.15
    if not MIN_CELSIUS <= celsius <= MAX_CELSIUS:
        return None
    return celsius


def decode_adc(data: bytes) -> list[int]:
    """Read a payload as consecutive little-endian 16-bit ADC slots."""
    return [data[i] | (data[i + 1] << 8) for i in range(0, len(data) - 1, 2)]


def decode_frame(frame: Frame) -> dict[str, float | int]:
    """Decode every field defined for this frame's address/direction/command.

    Fields whose sensor reads open-circuit, or whose value is otherwise out of
    range, are omitted rather than reported as a bogus number.
    """
    if frame.address is None or not frame.checksum_ok:
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

        if spec.kind == "ntc":
            if adc is None:
                adc = decode_adc(frame.data)
            if spec.index >= len(adc):
                continue
            celsius = ntc_to_celsius(adc[spec.index], NTC_COEFFICIENTS)
            if celsius is None:
                continue
            values[spec.field_id] = celsius
        else:
            if spec.index >= len(frame.data):
                continue
            raw = frame.data[spec.index]
            values[spec.field_id] = raw if spec.bit is None else (raw >> spec.bit) & 1

    return values
