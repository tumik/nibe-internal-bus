"""Circulation-pump PWM duty curves, from the display firmware (FUN_2010F25C).

The display converts a pump speed in percent to the duty byte it sends in
``0xA0 [GP1, GP2]``. For an "inverted" pump type (Grundfos UPM2 / UPM Geo, ...)::

    0 %   -> 100
    100 % -> 0
    else  -> A + trunc((p - 1) * (B - A) / 98)       # 1 % -> A, 99 % -> B

with (A, B) per pump type. This unit has GP1 = 0x0F (Grundfos UPM2 25-75,
A=77, B=13) and GP2 = 0x0E (Gfos UPM Geo 25-85, A=77, B=10). Duty bytes
78..99 and 1..12 are never sent, and about half of the duty values are shared
by two adjacent percentages, so the inverse has a resolution of +-1 %.
"""

from __future__ import annotations

# pump-type enum -> (A, B) of the inverted curve
INVERTED_CURVES: dict[int, tuple[int, int]] = {
    0x01: (66, 1),  # Grundfos UPM25-70
    0x0D: (77, 4),  # Gfos Magna Geo 25-100
    0x0E: (77, 10),  # Gfos UPM Geo 25-85        (GP2 of the F1226)
    0x0F: (77, 13),  # Grundfos UPM2 25-75       (GP1 of the F1226)
    0x10: (65, 1),  # Lowara E6 (ST2)
    0x11: (77, 13),  # Grundfos UPM2 25-70
    0x13: (65, 1),  # Xylem Lowara E6
    0x18: (78, 10),  # Gfos UPM2 15-70LF
    0x19: (76, 3),  # Gfos UPMXL Geo 25-125
    0x1A: (82, 5),  # Wilo Yonos Para 7.0
    0x1B: (82, 5),  # Wilo Yonos Para 7.5
    0x1C: (78, 10),  # Gfos UPM2 25-70LF
    0x1F: (77, 12),  # Grundfos UPM3 25-75
}

GP1_PUMP_TYPE = 0x0F
GP2_PUMP_TYPE = 0x0E

NO_PWM = 0xFF  # pump types without a curve send 0xFF (off-board speed control)


def duty_from_percent(percent: int, curve: tuple[int, int]) -> int:
    """The firmware's forward curve (C-style truncating division)."""
    if percent <= 0:
        return 100
    if percent >= 100:
        return 0
    a, b = curve
    numerator = (percent - 1) * (b - a)
    return a + int(numerator / 98)  # int() truncates toward zero like C


def percent_from_duty(duty: int, curve: tuple[int, int]) -> float | None:
    """Pump speed in percent for a duty byte (middle of the +-0.5 % ambiguity)."""
    if duty == NO_PWM:
        return None
    a, b = curve
    if duty >= 100:
        return 0.0
    if duty <= 0:
        return 100.0
    if duty >= a:
        return 1.0 if duty == a else 0.0
    if duty <= b:
        return 99.0 if duty == b else 100.0
    # forward: duty = a - floor((p - 1) * (a - b) / 98), so the percentages that
    # map to this duty are p - 1 in [(a-d)*98/(a-b), (a-d+1)*98/(a-b)).
    span = a - b
    low = 1 + -(-((a - duty) * 98) // span)  # ceil
    high = 1 + -(-((a - duty + 1) * 98) // span) - 1
    low = max(1, min(99, low))
    high = max(low, min(99, high))
    return (low + high) / 2


def gp1_percent(duty: int) -> float | None:
    """GP1 speed in percent."""
    return percent_from_duty(duty, INVERTED_CURVES[GP1_PUMP_TYPE])


def gp2_percent(duty: int) -> float | None:
    """GP2 speed in percent."""
    return percent_from_duty(duty, INVERTED_CURVES[GP2_PUMP_TYPE])
