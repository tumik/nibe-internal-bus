"""Binary sensors for the Nibe relay outputs.

All of these come from bit positions in the MASTER 0x55 frame. Byte 0 bit 3 is
the 3-way valve, which is exposed as an enum sensor instead.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NibeInternalBusConfigEntry
from .const import (
    FIELD_ADDITION_1KW,
    FIELD_ADDITION_2KW_A,
    FIELD_ADDITION_2KW_B,
    FIELD_ADDITION_2KW_C,
    FIELD_ADDITION_POWER,
    FIELD_BRINE_PUMP,
    FIELD_COMPRESSOR,
    FIELD_HEATING_PUMP,
    FIELD_RELAYS_BYTE1_BIT2,
    FIELD_RELAYS_BYTE1_BIT3,
)
from .coordinator import NibeInternalBusCoordinator
from .entity import NibeInternalBusEntity


@dataclass(frozen=True, kw_only=True)
class NibeBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a binary sensor and the bus field behind it."""

    field_id: str


def _diagnostic(key: str, field_id: str) -> NibeBinarySensorDescription:
    """A single relay bit kept for further research, disabled by default."""
    return NibeBinarySensorDescription(
        key=key,
        field_id=field_id,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    )


BINARY_SENSORS: tuple[NibeBinarySensorDescription, ...] = (
    NibeBinarySensorDescription(
        key="compressor",
        field_id=FIELD_COMPRESSOR,
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
    NibeBinarySensorDescription(
        key="heating_pump",
        field_id=FIELD_HEATING_PUMP,
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
    NibeBinarySensorDescription(
        key="brine_pump",
        field_id=FIELD_BRINE_PUMP,
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
    # On whenever any addition relay is, i.e. the derived power is non-zero.
    NibeBinarySensorDescription(
        key="electrical_addition",
        field_id=FIELD_ADDITION_POWER,
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
    _diagnostic("addition_relay_1kw", FIELD_ADDITION_1KW),
    _diagnostic("addition_relay_2kw_a", FIELD_ADDITION_2KW_A),
    _diagnostic("addition_relay_2kw_b", FIELD_ADDITION_2KW_B),
    _diagnostic("addition_relay_2kw_c", FIELD_ADDITION_2KW_C),
    _diagnostic("relays_byte1_bit2", FIELD_RELAYS_BYTE1_BIT2),
    _diagnostic("relays_byte1_bit3", FIELD_RELAYS_BYTE1_BIT3),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: NibeInternalBusConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the binary sensors."""
    coordinator = entry.runtime_data
    async_add_entities(
        NibeInternalBusBinarySensor(coordinator, description)
        for description in BINARY_SENSORS
    )


class NibeInternalBusBinarySensor(NibeInternalBusEntity, BinarySensorEntity):
    """A single relay output bit."""

    entity_description: NibeBinarySensorDescription

    def __init__(
        self,
        coordinator: NibeInternalBusCoordinator,
        description: NibeBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator, description, description.field_id)

    @property
    def is_on(self) -> bool | None:
        """Return whether the relay is energised."""
        value = self.coordinator.values.get(self._field_id)
        return None if value is None else bool(value)
