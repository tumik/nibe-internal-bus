"""Golden-vector tests for the value decoder.

Every expected temperature below was verified against the pump's own USB log
export for the same second.
"""

from __future__ import annotations

import pytest

from custom_components.nibe_internal_bus.binary_sensor import BINARY_SENSORS
from custom_components.nibe_internal_bus.coordinator import (
    EnergyMeter,
    addition_power,
    operating_mode,
)
from custom_components.nibe_internal_bus.decoder import (
    ADC_MAX,
    decode_frame,
    ntc_to_celsius,
)
from custom_components.nibe_internal_bus.fields import FIELD_SPECS, NTC_COEFFICIENTS
from custom_components.nibe_internal_bus.protocol import (
    MASTER,
    SLAVE,
    Frame,
    parse_frames,
)
from custom_components.nibe_internal_bus.sensor import (
    ADDITION_ENERGY,
    GP1_CALIBRATION,
    PERCENT_FROM_DUTY,
    SENSORS,
)

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


def test_ep14_temperatures_with_a_doubled_start_byte() -> None:
    # BT12 reads raw 0x015C, so the reply carries a doubled 5C.
    _, reply = parse_frames(
        bytes.fromhex(
            "5c 00 f5 91 00 64"
            " c0 91 11 5c 5c 01 91 01 6e 03 5d 03 86 00 41 03 8d 01 01 00 ab 06"
        )
    )

    values = decode_frame(reply)

    assert values["00F5_SLAVE_91_ntc0"] == pytest.approx(60.5, abs=TOLERANCE)
    assert values["00F5_SLAVE_91_ntc1"] == pytest.approx(54.5, abs=TOLERANCE)
    assert values["00F5_SLAVE_91_ntc2"] == pytest.approx(3.0, abs=TOLERANCE)
    assert values["00F5_SLAVE_91_ntc3"] == pytest.approx(5.6, abs=TOLERANCE)
    # One ADC count is worth ~0.35 degC this hot.
    assert values["00F5_SLAVE_91_ntc4"] == pytest.approx(98.2, abs=0.35)
    assert values["00F5_SLAVE_91_ntc5"] == pytest.approx(9.5, abs=TOLERANCE)


def test_main_board_temperatures_with_a_doubled_start_byte() -> None:
    # BT2 reads raw 0x015C.
    _, reply = parse_frames(
        bytes.fromhex(
            "5c 00 f5 90 00 65"
            " c0 90 11 35 03 96 01 b9 01 5c 5c 01 ff 03 01 00 ff 03 ff 03 a4 06"
        )
    )

    values = decode_frame(reply)

    assert values["00F5_SLAVE_90_ntc0"] == pytest.approx(11.1, abs=TOLERANCE)
    assert values["00F5_SLAVE_90_ntc1"] == pytest.approx(53.9, abs=TOLERANCE)
    assert values["00F5_SLAVE_90_ntc2"] == pytest.approx(50.2, abs=TOLERANCE)
    assert values["00F5_SLAVE_90_ntc3"] == pytest.approx(60.5, abs=TOLERANCE)


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


@pytest.mark.parametrize(("duty", "percent"), GP1_CALIBRATION)
def test_gp1_hits_every_known_speed_setting(duty: int, percent: float) -> None:
    assert PERCENT_FROM_DUTY["gp1_speed"](duty) == pytest.approx(percent)


def test_gp1_reads_zero_when_stopped() -> None:
    assert PERCENT_FROM_DUTY["gp1_speed"](0x64) == 0


def test_gp1_scale_is_monotonic_and_bounded() -> None:
    percents = [PERCENT_FROM_DUTY["gp1_speed"](duty) for duty in range(256)]

    assert all(0 <= percent <= 100 for percent in percents)
    assert all(a >= b for a, b in zip(percents, percents[1:], strict=False))


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


# Whole master frames as captured, stepping the electrical addition up to the
# pump's 6 kW limit. Every step was confirmed against Tot.Int.Add (43084) in
# the pump's USB log.
@pytest.mark.parametrize(
    ("datagram", "kw"),
    [
        ("5c 00 f5 55 02 02 04 a4", 0),  # idle
        ("5c 00 f5 55 02 0f 0c a1", 0),  # hot water on the compressor
        ("5c 00 f5 55 02 07 0c a9", 0),  # heating on the compressor
        ("5c 00 f5 55 02 0a 06 ae", 1),
        ("5c 00 f5 55 02 4a 04 ec", 2),
        ("5c 00 f5 55 02 4a 06 ee", 3),
        ("5c 00 f5 55 02 4a 05 ed", 4),
        ("5c 00 f5 55 02 4a 07 ef", 5),
        ("5c 00 f5 55 02 5a 05 fd", 6),
    ],
)
def test_addition_power_follows_the_relay_steps(datagram: str, kw: int) -> None:
    (relays,) = parse_frames(bytes.fromhex(datagram))

    assert relays.checksum_ok
    assert addition_power(decode_frame(relays)) == kw


@pytest.mark.parametrize(
    ("payload", "bit2", "bit3"),
    [("02 04", 1, 0), ("0f 0c", 1, 1), ("4a 07", 1, 0)],
)
def test_relay_byte1_bits(payload: str, bit2: int, bit3: int) -> None:
    values = decode_frame(frame(MASTER, 0x55, payload))

    assert values["00F5_MASTER_55_byte1"] == bytes.fromhex(payload)[1]
    assert values["00F5_MASTER_55_byte1bit2"] == bit2
    assert values["00F5_MASTER_55_byte1bit3"] == bit3


@pytest.mark.parametrize("cmd", [0x96, 0x99])
@pytest.mark.parametrize("status", [0x05, 0x06])
def test_status_replies_decode_raw(cmd: int, status: int) -> None:
    values = decode_frame(frame(SLAVE, cmd, f"{status:02x}"))

    assert values[f"00F5_SLAVE_{cmd:02X}_byte0"] == status


def test_energy_meter_integrates_each_step_until_the_next() -> None:
    meter = EnergyMeter(max_gap=60)

    meter.update(0, at=0)
    for second in range(1, 3601):
        meter.update(6, at=second)
    for second in range(3601, 5401):
        meter.update(2, at=second)
    meter.update(0, at=5401)

    # 0 kW for 1 s, 6 kW for 3600 s, 2 kW for 1800 s.
    assert meter.kwh == pytest.approx(7.0)


def test_energy_meter_skips_gaps_and_repeats() -> None:
    meter = EnergyMeter(max_gap=60)

    meter.update(6, at=0)
    meter.update(6, at=0)  # another frame of the same bus cycle
    meter.update(6, at=600)  # the bus was quiet for ten minutes
    assert meter.kwh == 0

    meter.update(6, at=630)
    assert meter.kwh == pytest.approx(6 * 30 / 3600)


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
    for description in (*SENSORS, ADDITION_ENERGY, *BINARY_SENSORS):
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
        ("0e 0c", "standby"),  # brine pump alone around a compressor start/stop
        ("07 0c", "heating"),
        ("0f 0c", "hot_water"),
        # The electrical addition alone, compressor off, heating hot water.
        ("0a 06", "hot_water"),
        ("5a 05", "hot_water"),
    ],
)
def test_operating_mode_follows_the_relay_bits(payload: str, mode: str) -> None:
    values = decode_frame(frame(MASTER, 0x55, payload))

    assert (
        operating_mode(
            values["00F5_MASTER_55_byte0bit0"],
            addition_power(values),
            values["00F5_MASTER_55_byte0bit3"],
        )
        == mode
    )
