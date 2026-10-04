"""Sensors for the Nibe internal RS-485 bus."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NibeInternalBusConfigEntry
from .const import (
    FIELD_ADDITION_POWER,
    FIELD_GP1_DUTY,
    FIELD_GP2_DUTY,
    FIELD_OPERATING_MODE,
    FIELD_RELAYS_RAW,
    FIELD_RELAYS_RAW_BYTE1,
    FIELD_STATUS_96,
    FIELD_STATUS_99,
    FIELD_THREE_WAY_VALVE,
    MODE_HEATING,
    MODE_HOT_WATER,
    MODE_STANDBY,
    VALVE_HEATING,
    VALVE_HOT_WATER,
)
from .coordinator import NibeInternalBusCoordinator
from .entity import NibeInternalBusEntity


@dataclass(frozen=True, kw_only=True)
class NibeSensorDescription(SensorEntityDescription):
    """Describes a sensor and where on the bus its value comes from."""

    field_id: str | None = None


def _temperature(key: str, field_id: str) -> NibeSensorDescription:
    return NibeSensorDescription(
        key=key,
        field_id=field_id,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        suggested_display_precision=1,
    )


def _diagnostic_raw(key: str, field_id: str) -> NibeSensorDescription:
    """An undecoded byte kept for further research, disabled by default."""
    return NibeSensorDescription(
        key=key,
        field_id=field_id,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    )


# The main board's own sensors are in the SLAVE 0x90 reply; the EP14 cooling
# module's set is in 0x91. All eleven are raw 10-bit NTC counts (see decoder).
SENSORS: tuple[NibeSensorDescription, ...] = (
    _temperature("bt1_outdoor", "00F5_SLAVE_90_ntc0"),
    _temperature("bt7_hot_water_top", "00F5_SLAVE_90_ntc1"),
    _temperature("bt6_hot_water_bottom", "00F5_SLAVE_90_ntc2"),
    _temperature("bt2_supply", "00F5_SLAVE_90_ntc3"),
    _temperature("bt12_condenser_out", "00F5_SLAVE_91_ntc0"),
    _temperature("bt3_return", "00F5_SLAVE_91_ntc1"),
    _temperature("bt11_brine_out", "00F5_SLAVE_91_ntc2"),
    _temperature("bt10_brine_in", "00F5_SLAVE_91_ntc3"),
    _temperature("bt14_hot_gas", "00F5_SLAVE_91_ntc4"),
    _temperature("bt17_suction_gas", "00F5_SLAVE_91_ntc5"),
    _temperature("bt15_liquid_line", "00F5_SLAVE_91_ntc6"),
    NibeSensorDescription(
        key="gp1_speed",
        field_id=FIELD_GP1_DUTY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        icon="mdi:pump",
    ),
    NibeSensorDescription(
        key="gp2_speed",
        field_id=FIELD_GP2_DUTY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        icon="mdi:pump",
    ),
    NibeSensorDescription(
        key="three_way_valve",
        field_id=FIELD_THREE_WAY_VALVE,
        device_class=SensorDeviceClass.ENUM,
        options=[VALVE_HEATING, VALVE_HOT_WATER],
        icon="mdi:valve",
    ),
    NibeSensorDescription(
        key="operating_mode",
        field_id=FIELD_OPERATING_MODE,
        device_class=SensorDeviceClass.ENUM,
        options=[MODE_STANDBY, MODE_HEATING, MODE_HOT_WATER],
    ),
    # Nominal: the sum of the switched-in relays' ratings, not a measurement.
    NibeSensorDescription(
        key="electrical_addition_power",
        field_id=FIELD_ADDITION_POWER,
        device_class=SensorDeviceClass.POWER,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement=UnitOfPower.KILO_WATT,
        suggested_display_precision=0,
    ),
    _diagnostic_raw("relays_raw", FIELD_RELAYS_RAW),
    _diagnostic_raw("relays_raw_byte1", FIELD_RELAYS_RAW_BYTE1),
    NibeSensorDescription(
        key="gp1_duty_raw",
        field_id=FIELD_GP1_DUTY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    _diagnostic_raw("status_96_raw", FIELD_STATUS_96),
    _diagnostic_raw("status_99_raw", FIELD_STATUS_99),
)

# Integrated by the coordinator from the addition power, so it has its own
# entity class rather than reading a decoded value.
ADDITION_ENERGY = NibeSensorDescription(
    key="electrical_addition_energy",
    field_id=FIELD_ADDITION_POWER,
    device_class=SensorDeviceClass.ENERGY,
    state_class=SensorStateClass.TOTAL_INCREASING,
    native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    suggested_display_precision=2,
)

# The 3-way valve bit: 0 = the condenser feeds the heating circuit,
# 1 = it feeds the hot water coil.
VALVE_STATES = {0: VALVE_HEATING, 1: VALVE_HOT_WATER}

# GP1's duty byte for each speed set in the pump's menu 5.1.11, as
# (duty, percent) in duty order. They do not lie on one straight line, so
# speeds in between are interpolated between the nearest two.
GP1_CALIBRATION: tuple[tuple[int, float], ...] = (
    (0x20, 70),
    (0x2D, 50),
    (0x34, 40),
    (0x3B, 30),
)
GP1_STOPPED = 0x64


def _gp1_percent(duty: int) -> float:
    """GP1's duty-to-percent scale, piecewise linear between known settings."""
    if duty >= GP1_STOPPED:
        return 0.0
    upper = bisect_left(GP1_CALIBRATION, duty, key=lambda point: point[0])
    upper = min(max(upper, 1), len(GP1_CALIBRATION) - 1)
    (duty0, percent0), (duty1, percent1) = GP1_CALIBRATION[upper - 1 : upper + 1]
    percent = percent0 + (percent1 - percent0) * (duty - duty0) / (duty1 - duty0)
    return min(max(percent, 0.0), 100.0)


def _gp2_percent(duty: int) -> float:
    return 100 - duty


PERCENT_FROM_DUTY = {"gp1_speed": _gp1_percent, "gp2_speed": _gp2_percent}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NibeInternalBusConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        NibeInternalBusSensor(coordinator, description) for description in SENSORS
    ]
    entities.append(NibeAdditionEnergySensor(coordinator, ADDITION_ENERGY))
    async_add_entities(entities)


class NibeInternalBusSensor(NibeInternalBusEntity, SensorEntity):
    """A single decoded bus value."""

    entity_description: NibeSensorDescription

    def __init__(
        self,
        coordinator: NibeInternalBusCoordinator,
        description: NibeSensorDescription,
    ) -> None:
        super().__init__(coordinator, description, description.field_id)

    @property
    def native_value(self) -> Any:
        """Return the decoded value."""
        value = self.coordinator.values.get(self._field_id)
        if value is None:
            return None

        if self.entity_description.key == "three_way_valve":
            return VALVE_STATES.get(int(value))
        if convert := PERCENT_FROM_DUTY.get(self.entity_description.key):
            return convert(int(value))
        return value


class NibeAdditionEnergySensor(NibeInternalBusEntity, RestoreSensor):
    """Energy used by the electrical addition, for the Energy dashboard.

    The coordinator's meter starts from zero on every setup; the last recorded
    total is added back here so the counter survives restarts.
    """

    entity_description: NibeSensorDescription

    def __init__(
        self,
        coordinator: NibeInternalBusCoordinator,
        description: NibeSensorDescription,
    ) -> None:
        super().__init__(coordinator, description, description.field_id)

    async def async_added_to_hass(self) -> None:
        """Carry the total over from before the restart."""
        await super().async_added_to_hass()
        last = await self.async_get_last_sensor_data()
        if last is not None and last.native_value is not None:
            self.coordinator.addition_energy.kwh += float(last.native_value)

    @property
    def native_value(self) -> float:
        """Return the energy used so far."""
        return self.coordinator.addition_energy.kwh
