"""Which bytes on the internal bus mean what.

A field identifier encodes the rule's position on the bus, for example
``00F5_SLAVE_91_ntc4``: bus address 00F5, a slave reply to command 0x91, ADC
slot 4. Entity metadata is joined to these rules by that identifier.
"""

from __future__ import annotations

from dataclasses import dataclass

from .const import BUS_ADDRESS
from .protocol import MASTER, SLAVE

# The pump reads each temperature sensor as a resistive divider into a 10-bit
# ADC, so the count tracks the thermistor's resistance, not temperature. These
# are a Steinhart-Hart style polynomial in ln(adc / (1023 - adc)).
NTC_COEFFICIENTS: tuple[float, ...] = (
    0.003162333411,
    0.000251402068,
    1.485144801e-06,
    1.11796736e-07,
)


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One decoding rule: where a value sits on the bus and how to read it."""

    field_id: str
    address: int
    direction: str
    cmd: int
    kind: str  # "ntc" | "byte" | "bit"
    index: int
    bit: int | None = None


def _slave_ntc(cmd: int, index: int) -> FieldSpec:
    """A 2-byte thermistor ADC slot in a slave reply."""
    return FieldSpec(
        field_id=f"{BUS_ADDRESS:04X}_{SLAVE}_{cmd:02X}_ntc{index}",
        address=BUS_ADDRESS,
        direction=SLAVE,
        cmd=cmd,
        kind="ntc",
        index=index,
    )


def _master_byte(cmd: int, index: int) -> FieldSpec:
    """A whole raw byte of a master frame."""
    return FieldSpec(
        field_id=f"{BUS_ADDRESS:04X}_{MASTER}_{cmd:02X}_byte{index}",
        address=BUS_ADDRESS,
        direction=MASTER,
        cmd=cmd,
        kind="byte",
        index=index,
    )


def _master_bit(cmd: int, index: int, bit: int) -> FieldSpec:
    """A single bit of a master frame byte, 0 = LSB."""
    return FieldSpec(
        field_id=f"{BUS_ADDRESS:04X}_{MASTER}_{cmd:02X}_byte{index}bit{bit}",
        address=BUS_ADDRESS,
        direction=MASTER,
        cmd=cmd,
        kind="bit",
        index=index,
        bit=bit,
    )


FIELD_SPECS: tuple[FieldSpec, ...] = (
    # 0x55 byte 0 is the relay output bitmask driving the base board.
    _master_byte(0x55, 0),
    _master_bit(0x55, 0, 0),  # compressor
    _master_bit(0x55, 0, 1),  # heating circuit pump
    _master_bit(0x55, 0, 2),  # brine (collector) pump
    _master_bit(0x55, 0, 3),  # 3-way valve: 0 = heating, 1 = hot water
    # 0xA0 carries the two circulation pumps' PWM duty commands.
    _master_byte(0xA0, 0),  # GP1
    _master_byte(0xA0, 1),  # GP2
    # The main board's own sensors.
    _slave_ntc(0x90, 0),  # BT1 outdoor
    _slave_ntc(0x90, 1),  # BT7 hot water top
    _slave_ntc(0x90, 2),  # BT6 hot water bottom
    _slave_ntc(0x90, 3),  # BT2 supply
    # The EP14 cooling module's sensors.
    _slave_ntc(0x91, 0),  # BT12 condenser out
    _slave_ntc(0x91, 1),  # BT3 return
    _slave_ntc(0x91, 2),  # BT11 brine out
    _slave_ntc(0x91, 3),  # BT10 brine in
    _slave_ntc(0x91, 4),  # BT14 hot gas
    _slave_ntc(0x91, 5),  # BT17 suction gas
    _slave_ntc(0x91, 6),  # BT15 liquid line
)
