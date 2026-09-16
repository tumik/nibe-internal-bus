"""NibeGW RS-485 frame parsing.

Ported from esphome-nibe/examples/nibegw_sniff.py. This module is pure
protocol handling with no Home Assistant dependency so it can be unit tested
standalone.

Each UDP datagram forwarded by the ESP32 is one complete bus cycle: a master
("response", start byte 0x5C) frame, optionally followed by the accessory's
slave ("request", start byte 0xC0) reply, and a trailing ACK/NAK byte.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

START_MASTER: Final = 0x5C
START_SLAVE: Final = 0xC0
BYTE_ACK: Final = 0x06
BYTE_NAK: Final = 0x15

MASTER: Final = "MASTER"
SLAVE: Final = "SLAVE"


@dataclass(frozen=True, slots=True)
class Frame:
    """One decoded bus frame."""

    direction: str
    address: int | None
    cmd: int
    data: bytes
    checksum_ok: bool


def xor8(data: bytes) -> int:
    """XOR checksum, with NibeGW's 0x5C -> 0xC5 substitution."""
    checksum = 0
    for byte in data:
        checksum ^= byte
    # A checksum equal to the start byte would desynchronise the receiver.
    if checksum == START_MASTER:
        checksum = 0xC5
    return checksum


def build_trigger_packet() -> bytes:
    """Build the minimal valid slave frame used to register as a UDP target.

    START(0xC0) CMD(0x00) LEN(0x00) CHK -- a zero-length keepalive ping. It is
    tagged MODBUS40/READ_TOKEN by which port it arrives on, not by its content,
    so with the ESPHome device's `acknowledge:` list empty it is never dequeued
    onto the RS-485 bus.
    """
    frame = bytes([START_SLAVE, 0x00, 0x00])
    return frame + bytes([xor8(frame)])


TRIGGER_PACKET: Final = build_trigger_packet()


def parse_frames(data: bytes) -> list[Frame]:
    """Split one UDP datagram into its individual frames.

    Master frames checksum the bytes *after* the start byte; slave frames
    include it. Slave frames carry no address of their own -- they inherit it
    from the master frame that preceded them in the same datagram.

    ACK/NAK/noise bytes and truncated tails are discarded. Frames that fail
    their checksum are returned with ``checksum_ok=False`` so the caller can
    count them; they must not be decoded.
    """
    frames: list[Frame] = []
    pos = 0
    end_of_data = len(data)
    last_address: int | None = None

    while pos < end_of_data:
        byte = data[pos]

        if byte == START_MASTER and pos + 6 <= end_of_data:
            address = (data[pos + 1] << 8) | data[pos + 2]
            cmd = data[pos + 3]
            end = pos + 5 + data[pos + 4]
            if end >= end_of_data:
                break
            frames.append(
                Frame(
                    direction=MASTER,
                    address=address,
                    cmd=cmd,
                    data=data[pos + 5 : end],
                    checksum_ok=data[end] == xor8(data[pos + 1 : end]),
                )
            )
            last_address = address
            pos = end + 1
        elif byte == START_SLAVE and pos + 4 <= end_of_data:
            cmd = data[pos + 1]
            end = pos + 3 + data[pos + 2]
            if end >= end_of_data:
                break
            frames.append(
                Frame(
                    direction=SLAVE,
                    address=last_address,
                    cmd=cmd,
                    data=data[pos + 3 : end],
                    checksum_ok=data[end] == xor8(data[pos:end]),
                )
            )
            pos = end + 1
        else:
            pos += 1

    return frames
