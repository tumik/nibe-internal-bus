"""Tests for NibeGW frame parsing."""

from __future__ import annotations

import pytest

from custom_components.nibe_internal_bus.protocol import (
    MASTER,
    SLAVE,
    TRIGGER_PACKET,
    parse_frames,
    xor8,
)


def master_frame(address: int, cmd: int, payload: bytes) -> bytes:
    body = bytes([address >> 8, address & 0xFF, cmd, len(payload)]) + payload
    return bytes([0x5C]) + body + bytes([xor8(body)])


def slave_frame(cmd: int, payload: bytes) -> bytes:
    body = bytes([0xC0, cmd, len(payload)]) + payload
    return body + bytes([xor8(body)])


def test_trigger_packet_is_a_zero_length_slave_frame() -> None:
    assert TRIGGER_PACKET == bytes([0xC0, 0x00, 0x00, 0xC0])


def test_xor8_never_returns_the_master_start_byte() -> None:
    assert xor8(bytes([0x5C])) == 0xC5


def test_slave_frames_inherit_the_preceding_master_address() -> None:
    datagram = (
        master_frame(0x00F5, 0x6A, bytes([0x90]))
        + slave_frame(0x90, bytes(range(16)))
        + bytes([0x06])
    )

    frames = parse_frames(datagram)

    assert [f.direction for f in frames] == [MASTER, SLAVE]
    assert all(f.address == 0x00F5 for f in frames)
    assert all(f.checksum_ok for f in frames)
    assert frames[1].cmd == 0x90
    assert frames[1].data == bytes(range(16))


def test_bad_checksum_is_flagged_not_dropped() -> None:
    datagram = bytearray(master_frame(0x00F5, 0x55, bytes([0x02, 0x04])))
    datagram[-1] ^= 0xFF

    (frame,) = parse_frames(bytes(datagram))

    assert frame.checksum_ok is False


def test_truncated_tail_is_discarded() -> None:
    complete = master_frame(0x00F5, 0x55, bytes([0x02, 0x04]))
    datagram = complete + bytes([0x5C, 0x00, 0xF5])

    frames = parse_frames(datagram)

    assert len(frames) == 1
    assert frames[0].checksum_ok


def test_ack_and_noise_bytes_do_not_produce_frames() -> None:
    assert parse_frames(bytes([0x06, 0x15, 0x00, 0xFF])) == []


# Captured off the bus. A 0x5C in the payload goes out doubled, and both the
# length byte (0x11 for 16 payload bytes) and the checksum count the doubling.
@pytest.mark.parametrize(
    ("datagram", "payload"),
    [
        (
            "5c 00 f5 91 00 64"
            " c0 91 11 5c 5c 01 91 01 6e 03 5d 03 86 00 41 03 8d 01 01 00 ab 06",
            "5c 01 91 01 6e 03 5d 03 86 00 41 03 8d 01 01 00",
        ),
        (
            "5c 00 f5 90 00 65"
            " c0 90 11 35 03 96 01 b9 01 5c 5c 01 ff 03 01 00 ff 03 ff 03 a4 06",
            "35 03 96 01 b9 01 5c 01 ff 03 01 00 ff 03 ff 03",
        ),
    ],
)
def test_doubled_start_byte_in_a_payload_is_unescaped(
    datagram: str, payload: str
) -> None:
    master, slave = parse_frames(bytes.fromhex(datagram))

    assert master.checksum_ok
    assert slave.checksum_ok
    assert slave.data == bytes.fromhex(payload)


def test_doubled_start_byte_in_a_master_payload_is_unescaped() -> None:
    (frame,) = parse_frames(master_frame(0x00F5, 0x55, bytes([0x5C, 0x5C, 0x04])))

    assert frame.checksum_ok
    assert frame.data == bytes([0x5C, 0x04])


def test_checksum_of_0x5c_is_sent_as_0xc5() -> None:
    # Captured off the bus: these bytes XOR to 0x5C.
    datagram = bytes.fromhex(
        "5c 00 f5 91 00 64 c0 91 10 63 01 82 01 6a 03 5a 03 7e 00 32 03 83 01 01 00 c5"
    )

    _, slave = parse_frames(datagram)

    assert slave.checksum_ok
