"""Which bytes on the internal bus mean what.

A field identifier encodes the rule's position on the bus, for example
``00F5_SLAVE_91_ntc4``: bus address 00F5, a slave reply to command 0x91, ADC
slot 4. Entity metadata is joined to these rules by that identifier.
"""

from __future__ import annotations

from dataclasses import dataclass

from .const import BUS_ADDRESS, FIELD_STATUS_CODE
from .protocol import MASTER, SLAVE


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One decoding rule: where a value sits on the bus and how to read it."""

    field_id: str
    address: int
    direction: str
    cmd: int
    kind: str  # "ntc" | "byte" | "bit" | "din_gt" | "din_lt" | "adc"
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


def _slave_word(kind: str, cmd: int, index: int, suffix: str) -> FieldSpec:
    """A 2-byte ADC slot used as a digital input ("din_gt"/"din_lt") or raw ("adc")."""
    return FieldSpec(
        field_id=f"{BUS_ADDRESS:04X}_{SLAVE}_{cmd:02X}_{suffix}{index}",
        address=BUS_ADDRESS,
        direction=SLAVE,
        cmd=cmd,
        kind=kind,
        index=index,
    )


def _slave_byte(cmd: int, index: int) -> FieldSpec:
    """A whole raw byte of a slave reply."""
    return FieldSpec(
        field_id=f"{BUS_ADDRESS:04X}_{SLAVE}_{cmd:02X}_byte{index}",
        address=BUS_ADDRESS,
        direction=SLAVE,
        cmd=cmd,
        kind="byte",
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
    _master_bit(0x55, 0, 4),  # electrical addition, 2 kW (third step)
    _master_bit(0x55, 0, 5),  # AA1-K5 relay output (function not identified)
    _master_bit(0x55, 0, 6),  # electrical addition, 2 kW (first step)
    _master_bit(0x55, 0, 7),  # AA1-K7 relay output (function not identified)
    # 0x55 byte 1 holds the rest of the electrical addition relays.
    _master_byte(0x55, 1),
    _master_bit(0x55, 1, 0),  # electrical addition, 2 kW (second step)
    _master_bit(0x55, 1, 1),  # electrical addition, 1 kW
    _master_bit(0x55, 1, 2),  # inverted alarm output (inferred), set while no alarm
    _master_bit(0x55, 1, 3),  # "GP2 speed != 0", i.e. a copy of byte 0 bit 2
    _master_bit(0x55, 1, 4),  # hot water circulation requested (register 43180)
    # 0xA0 carries the two circulation pumps' PWM duty commands.
    _master_byte(0xA0, 0),  # GP1
    _master_byte(0xA0, 1),  # GP2
    # One-byte status replies that flip briefly around compressor starts/stops.
    _slave_byte(0x96, 0),
    _slave_byte(0x99, 0),
    # Both replies carry the same PCA-Base status code (REG 43443); this merged
    # id is what the status entities read.
    FieldSpec(FIELD_STATUS_CODE, BUS_ADDRESS, SLAVE, 0x96, "byte", 0),
    FieldSpec(FIELD_STATUS_CODE, BUS_ADDRESS, SLAVE, 0x99, "byte", 0),
    # Protection inputs (firmware regs 40052/40053/40054), 1 = alarm.
    _slave_word("din_lt", 0x93, 0, "din_lt"),  # HP: raw < 300
    _slave_word("din_gt", 0x91, 7, "din_gt"),  # LP: raw > 300
    _slave_word("din_gt", 0x92, 0, "din_gt"),  # TB: raw > 300
    # Remaining raw words that no firmware converter consumes (diagnostics).
    _slave_word("adc", 0x92, 3, "adc"),
    _slave_word("adc", 0x93, 1, "adc"),
    # The main board's own sensors.
    _slave_ntc(0x90, 0),  # BT1 outdoor
    _slave_ntc(0x90, 1),  # BT7 hot water top
    _slave_ntc(0x90, 2),  # BT6 hot water bottom
    _slave_ntc(0x90, 3),  # BT2 supply
    # The second PCA-Base input block (the same board answers 0x90..0x93).
    _slave_ntc(0x91, 0),  # BT12 condenser out
    _slave_ntc(0x91, 1),  # BT3 return
    _slave_ntc(0x91, 2),  # BT11 brine out
    _slave_ntc(0x91, 3),  # BT10 brine in
    _slave_ntc(0x91, 4),  # BT14 hot gas
    _slave_ntc(0x91, 5),  # BT17 suction gas
    _slave_ntc(0x91, 6),  # BT15 liquid line
)
