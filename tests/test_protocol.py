"""Tests for NibeGW frame parsing."""

from __future__ import annotations

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
