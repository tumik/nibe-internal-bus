"""Sensors for the Nibe internal RS-485 bus."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NibeInternalBusConfigEntry
from .const import (
    FIELD_GP1_DUTY,
    FIELD_GP2_DUTY,
    FIELD_OPERATING_MODE,
    FIELD_RELAYS_RAW,
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
    NibeSensorDescription(
        key="relays_raw",
        field_id=FIELD_RELAYS_RAW,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    NibeSensorDescription(
        key="gp1_duty_raw",
        field_id=FIELD_GP1_DUTY,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
)

# The 3-way valve bit: 0 = the condenser feeds the heating circuit,
# 1 = it feeds the hot water coil.
VALVE_STATES = {0: VALVE_HEATING, 1: VALVE_HOT_WATER}


def _gp1_percent(duty: int) -> float:
    """GP1's duty-to-percent scale. Unverified, see the README."""
    return (800 - 10 * duty) / 7


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
    async_add_entities(
        NibeInternalBusSensor(coordinator, description) for description in SENSORS
    )


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
