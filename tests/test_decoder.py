"""Golden-vector tests for the value decoder.

Every expected temperature below was verified against the pump's own USB log
export for the same second.
"""

from __future__ import annotations

import pytest

from custom_components.nibe_internal_bus.binary_sensor import BINARY_SENSORS
from custom_components.nibe_internal_bus.coordinator import operating_mode
from custom_components.nibe_internal_bus.decoder import (
    ADC_MAX,
    decode_frame,
    ntc_to_celsius,
)
from custom_components.nibe_internal_bus.fields import FIELD_SPECS, NTC_COEFFICIENTS
from custom_components.nibe_internal_bus.protocol import MASTER, SLAVE, Frame
from custom_components.nibe_internal_bus.sensor import PERCENT_FROM_DUTY, SENSORS

TOLERANCE = 0.1


def frame(direction: str, cmd: int, payload: str) -> Frame:
    return Frame(
        direction=direction,
        address=0x00F5,
        cmd=cmd,
        data=bytes.fromhex(payload),
        checksum_ok=True,
    )


def test_open_circuit_and_digital_flag_decode_to_nothing() -> None:
    assert ntc_to_celsius(ADC_MAX, NTC_COEFFICIENTS) is None
    assert ntc_to_celsius(0, NTC_COEFFICIENTS) is None
    # Raw 1 is a digital flag; naively decoded it would read ~414 degC.
    assert ntc_to_celsius(1, NTC_COEFFICIENTS) is None


def test_main_board_temperatures() -> None:
    values = decode_frame(
        frame(SLAVE, 0x90, "17 03 9c 01 cc 01 c4 02 ff 03 ff 03 ff 03 ff 03")
    )

    assert values["00F5_SLAVE_90_ntc0"] == pytest.approx(14.8, abs=TOLERANCE)
    assert values["00F5_SLAVE_90_ntc1"] == pytest.approx(53.3, abs=TOLERANCE)
    assert values["00F5_SLAVE_90_ntc2"] == pytest.approx(48.2, abs=TOLERANCE)
    assert values["00F5_SLAVE_90_ntc3"] == pytest.approx(23.9, abs=TOLERANCE)
    # Slots 4-7 read full scale: nothing is wired to them.
    assert len(values) == 4


def test_ep14_temperatures() -> None:
    values = decode_frame(
        frame(SLAVE, 0x91, "c6 02 c6 02 10 03 f6 02 75 02 a0 02 bf 02 01 00")
    )

    assert values["00F5_SLAVE_91_ntc0"] == pytest.approx(23.6, abs=TOLERANCE)
    assert values["00F5_SLAVE_91_ntc1"] == pytest.approx(23.6, abs=TOLERANCE)
    assert values["00F5_SLAVE_91_ntc2"] == pytest.approx(15.6, abs=TOLERANCE)
    assert values["00F5_SLAVE_91_ntc3"] == pytest.approx(18.5, abs=TOLERANCE)
    assert values["00F5_SLAVE_91_ntc4"] == pytest.approx(31.7, abs=TOLERANCE)
    assert values["00F5_SLAVE_91_ntc5"] == pytest.approx(27.5, abs=TOLERANCE)
    assert values["00F5_SLAVE_91_ntc6"] == pytest.approx(24.4, abs=TOLERANCE)
    # Slot 7 holds raw 1, a digital flag, and must not become a temperature.
    assert len(values) == 7


@pytest.mark.parametrize(
    ("payload", "gp1_duty", "gp2_duty"),
    [("3b 64", 59, 100), ("34 00", 52, 0)],
)
def test_pump_duty_bytes_decode_raw(
    payload: str, gp1_duty: int, gp2_duty: int
) -> None:
    values = decode_frame(frame(MASTER, 0xA0, payload))

    assert values["00F5_MASTER_A0_byte0"] == gp1_duty
    assert values["00F5_MASTER_A0_byte1"] == gp2_duty


@pytest.mark.parametrize(
    ("gp1_duty", "gp2_duty", "gp1_percent", "gp2_percent"),
    [(59, 100, 30, 0), (52, 0, 40, 100)],
)
def test_duty_converts_to_percent(
    gp1_duty: int, gp2_duty: int, gp1_percent: int, gp2_percent: int
) -> None:
    assert PERCENT_FROM_DUTY["gp1_speed"](gp1_duty) == pytest.approx(gp1_percent)
    assert PERCENT_FROM_DUTY["gp2_speed"](gp2_duty) == pytest.approx(gp2_percent)


@pytest.mark.parametrize(
    ("payload", "relays", "bits"),
    [
        ("02 04", 2, (0, 1, 0, 0)),
        ("07 0c", 7, (1, 1, 1, 0)),
        ("0f 0c", 15, (1, 1, 1, 1)),
    ],
)
def test_relay_bits(payload: str, relays: int, bits: tuple[int, ...]) -> None:
    values = decode_frame(frame(MASTER, 0x55, payload))

    assert values["00F5_MASTER_55_byte0"] == relays
    for bit, expected in enumerate(bits):
        assert values[f"00F5_MASTER_55_byte0bit{bit}"] == expected


def test_frames_failing_their_checksum_are_not_decoded() -> None:
    bad = Frame(
        direction=MASTER,
        address=0x00F5,
        cmd=0x55,
        data=bytes([0x0F, 0x0C]),
        checksum_ok=False,
    )

    assert decode_frame(bad) == {}


def test_every_field_id_is_unique() -> None:
    assert len({spec.field_id for spec in FIELD_SPECS}) == len(FIELD_SPECS)


def test_every_entity_field_id_is_produced_by_the_decoder() -> None:
    known = {spec.field_id for spec in FIELD_SPECS}
    for description in (*SENSORS, *BINARY_SENSORS):
        field_id = description.field_id
        if field_id is None or field_id.startswith("derived_"):
            continue
        assert field_id in known, f"{description.key} reads an undecoded field"


# Relay bytes taken from the capture: 2 = idle, 7 = heating run, 15 = hot water.
@pytest.mark.parametrize(
    ("payload", "mode"),
    [
        ("02 04", "standby"),
        ("0a 04", "standby"),
        ("07 0c", "heating"),
        ("0f 0c", "hot_water"),
    ],
)
def test_operating_mode_follows_the_relay_bits(payload: str, mode: str) -> None:
    values = decode_frame(frame(MASTER, 0x55, payload))

    assert (
        operating_mode(
            values["00F5_MASTER_55_byte0bit0"], values["00F5_MASTER_55_byte0bit3"]
        )
        == mode
    )
