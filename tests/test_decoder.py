"""Golden-vector tests for the value decoder.

Every expected temperature below was verified against the pump's own USB log
export for the same second.
"""

from __future__ import annotations

import pytest

from custom_components.nibe_internal_bus.binary_sensor import BINARY_SENSORS
from custom_components.nibe_internal_bus.const import (
    FIELD_GP1_DUTY,
    FIELD_GP2_DUTY,
    FIELD_HP_ALARM,
    FIELD_LP_ALARM,
    FIELD_TB_ALARM,
    STATUS_FAULT_CODES,
    STATUS_STATES,
)
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
from custom_components.nibe_internal_bus.fields import FIELD_SPECS
from custom_components.nibe_internal_bus.ntc_table import NTC_X10
from custom_components.nibe_internal_bus.protocol import (
    MASTER,
    SLAVE,
    Frame,
    parse_frames,
)
from custom_components.nibe_internal_bus.pump import (
    INVERTED_CURVES,
    duty_from_percent,
    percent_from_duty,
)
from custom_components.nibe_internal_bus.sensor import (
    ADDITION_ENERGY,
    PERCENT_FROM_DUTY,
    SENSORS,
)

# The firmware table is what the pump itself uses; the golden vectors below were
# read from the pump's (3-sample averaged) USB log, so allow one display digit.
TOLERANCE = 0.11


def frame(direction: str, cmd: int, payload: str) -> Frame:
    return Frame(
        direction=direction,
        address=0x00F5,
        cmd=cmd,
        data=bytes.fromhex(payload),
        checksum_ok=True,
    )


def test_open_circuit_and_digital_flag_decode_to_nothing() -> None:
    assert ntc_to_celsius(ADC_MAX) is None
    assert ntc_to_celsius(0) is None
    # Raw 1 is a digital flag; as an NTC it would read 231.8 degC (> 170).
    assert ntc_to_celsius(1) is None
    # Firmware limits are -60.0 .. +170.0 degC, inclusive.
    assert ntc_to_celsius(25) == pytest.approx(169.1, abs=0.01)
    assert ntc_to_celsius(24) is None
    assert ntc_to_celsius(1020) == pytest.approx(-58.2, abs=0.01)
    assert ntc_to_celsius(1021) is None


@pytest.mark.parametrize(
    ("raw", "celsius"), [(444, 49.9), (787, 15.2), (500, 44.2), (1000, -31.1)]
)
def test_table_values_match_the_firmware(raw: int, celsius: float) -> None:
    assert ntc_to_celsius(raw) == pytest.approx(celsius, abs=0.001)


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
    # Slot 7 holds raw 1, a digital flag (the LP input), not a temperature.
    assert "00F5_SLAVE_91_ntc7" not in values
    assert values["00F5_SLAVE_91_din_gt7"] == 0
    assert len(values) == 8


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
def test_pump_duty_bytes_decode_raw(payload: str, gp1_duty: int, gp2_duty: int) -> None:
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
    assert PERCENT_FROM_DUTY["gp1_speed"](gp1_duty) == pytest.approx(gp1_percent, abs=1)
    assert PERCENT_FROM_DUTY["gp2_speed"](gp2_duty) == pytest.approx(gp2_percent)


@pytest.mark.parametrize(
    ("percent", "gp1_duty", "gp2_duty"),
    [(0, 100, 100), (1, 77, 77), (30, 59, 58), (50, 45, 44), (99, 13, 10), (100, 0, 0)],
)
def test_pump_curves_match_the_firmware(
    percent: int, gp1_duty: int, gp2_duty: int
) -> None:
    assert duty_from_percent(percent, INVERTED_CURVES[0x0F]) == gp1_duty
    assert duty_from_percent(percent, INVERTED_CURVES[0x0E]) == gp2_duty


@pytest.mark.parametrize("pump_type", [0x0F, 0x0E, 0x0D, 0x1A])
def test_pump_inverse_is_within_one_percent(pump_type: int) -> None:
    curve = INVERTED_CURVES[pump_type]
    for percent in range(101):
        back = percent_from_duty(duty_from_percent(percent, curve), curve)
        assert back is not None
        assert abs(back - percent) <= 1


def test_gp1_hits_the_settings_seen_in_the_usb_log() -> None:
    # (duty byte, pump menu percent) pairs confirmed against GP1-speed 43437.
    for duty, percent in ((0x20, 70), (0x2D, 50), (0x34, 40), (0x3B, 30)):
        assert PERCENT_FROM_DUTY["gp1_speed"](duty) == pytest.approx(percent, abs=1)


def test_pump_reads_zero_when_stopped_and_none_without_pwm() -> None:
    assert PERCENT_FROM_DUTY["gp1_speed"](0x64) == 0
    assert PERCENT_FROM_DUTY["gp2_speed"](0x64) == 0
    assert PERCENT_FROM_DUTY["gp2_speed"](0xFF) is None


def test_pump_scale_is_monotonic_and_bounded() -> None:
    for key in ("gp1_speed", "gp2_speed"):
        percents = [PERCENT_FROM_DUTY[key](duty) for duty in range(255)]
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


def test_every_field_id_is_unique_per_command() -> None:
    keys = {(spec.field_id, spec.cmd) for spec in FIELD_SPECS}
    assert len(keys) == len(FIELD_SPECS)


# One complete idle bus cycle, one datagram per line, captured live from an F1226
# (compressor, pumps and addition off, no alarms).
IDLE_CYCLE = (
    "5C00F5A00264645706",
    "5C00F555020004A606",
    "5C00F5960063C09601055206",
    "5C00F5900065C0901065039601BC0192020100FF03FF03FF036106",
    "5C00F5910064C09110A402BE021403FC026D029B02C20201008506",
    "5C00F5920067C09210B500FF03FF0303020100FF03FF03FF030B06",
    "5C00F5930066C09306A40322000100D106",
    "5C00F585007006",
)


def decode_datagrams(datagrams: tuple[str, ...]) -> dict[str, float | int]:
    values: dict[str, float | int] = {}
    for datagram in datagrams:
        for decoded in parse_frames(bytes.fromhex(datagram)):
            assert decoded.checksum_ok
            values.update(decode_frame(decoded))
    return values


def test_idle_cycle_captured_from_the_pump() -> None:
    values = decode_datagrams(IDLE_CYCLE)

    # Relays: everything off except the always-set bit 1.2.
    assert values["00F5_MASTER_55_byte0"] == 0x00
    assert values["00F5_MASTER_55_byte1"] == 0x04
    assert values["00F5_MASTER_55_byte1bit4"] == 0
    assert values["00F5_MASTER_55_byte0bit5"] == 0
    assert values["00F5_MASTER_55_byte0bit7"] == 0
    # Both pumps stopped (duty 100), compressor protection reports "stopped".
    assert PERCENT_FROM_DUTY["gp1_speed"](values[FIELD_GP1_DUTY]) == 0
    assert PERCENT_FROM_DUTY["gp2_speed"](values[FIELD_GP2_DUTY]) == 0
    assert values["00F5_SLAVE_status_code"] == 5
    # Protection inputs inactive, spare words as seen on the wire.
    assert values["00F5_SLAVE_93_din_lt0"] == 0  # raw 932
    assert values["00F5_SLAVE_91_din_gt7"] == 0  # raw 1
    assert values["00F5_SLAVE_92_din_gt0"] == 0  # raw 181
    assert values["00F5_SLAVE_92_adc3"] == 515
    assert values["00F5_SLAVE_93_adc1"] == 34
    # Temperatures straight from the firmware table (BT1 raw 0x0365 = 869).
    assert values["00F5_SLAVE_90_ntc0"] == pytest.approx(NTC_X10[869] / 10)
    assert values["00F5_SLAVE_91_ntc0"] == pytest.approx(NTC_X10[0x02A4] / 10)
    # Open inputs do not become temperatures.
    assert "00F5_SLAVE_90_ntc4" not in values


def test_protection_inputs_use_the_firmware_thresholds() -> None:
    hp = FIELD_HP_ALARM
    lp = FIELD_LP_ALARM
    tb = FIELD_TB_ALARM
    ok_93 = decode_frame(frame(SLAVE, 0x93, "a4 03 22 00 01 00"))
    alarm_93 = decode_frame(frame(SLAVE, 0x93, "2b 01 22 00 01 00"))  # raw 299
    edge_93 = decode_frame(frame(SLAVE, 0x93, "2c 01 22 00 01 00"))  # raw 300
    assert (ok_93[hp], alarm_93[hp], edge_93[hp]) == (0, 1, 0)

    lp_payload = "a4 02 be 02 14 03 fc 02 6d 02 9b 02 c2 02 {} 01"
    assert decode_frame(frame(SLAVE, 0x91, lp_payload.format("2d")))[lp] == 1
    assert decode_frame(frame(SLAVE, 0x91, lp_payload.format("2c")))[lp] == 0

    tb_payload = "{} 01 ff 03 ff 03 03 02 01 00 ff 03 ff 03 ff 03"
    assert decode_frame(frame(SLAVE, 0x92, tb_payload.format("2d")))[tb] == 1
    assert decode_frame(frame(SLAVE, 0x92, tb_payload.format("2c")))[tb] == 0


def test_spare_relay_bits_and_hot_water_circulation() -> None:
    values = decode_frame(frame(MASTER, 0x55, "a2 14"))

    assert values["00F5_MASTER_55_byte0bit5"] == 1
    assert values["00F5_MASTER_55_byte0bit7"] == 1
    assert values["00F5_MASTER_55_byte1bit4"] == 1


def test_status_codes_and_fault_set() -> None:
    assert set(STATUS_STATES) >= {1, 2, 3, 4, 5, 6, 7, 8, 9, 0xFE}
    assert STATUS_FAULT_CODES == {1, 2, 3, 4, 8, 9, 0xFE}
    # Normal operating states are not faults.
    assert not {5, 6, 7} & STATUS_FAULT_CODES


@pytest.mark.parametrize("cmd", [0x96, 0x99])
@pytest.mark.parametrize("code", [5, 6])
def test_status_code_is_merged_across_both_polls(cmd: int, code: int) -> None:
    values = decode_frame(frame(SLAVE, cmd, f"{code:02x}"))

    assert values["00F5_SLAVE_status_code"] == code


def test_nak_frames_are_not_decoded() -> None:
    (relays,) = parse_frames(bytes.fromhex("5c 00 f5 55 02 0f 0c a1 15"))

    assert relays.acked is False
    assert decode_frame(relays) == {}


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
