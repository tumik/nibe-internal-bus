"""Binary sensors for the Nibe relay outputs.

All three come from bit positions in byte 0 of the MASTER 0x55 frame. Bit 3 is
the 3-way valve, which is exposed as an enum sensor instead.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import NibeInternalBusConfigEntry
from .const import FIELD_BRINE_PUMP, FIELD_COMPRESSOR, FIELD_HEATING_PUMP
from .coordinator import NibeInternalBusCoordinator
from .entity import NibeInternalBusEntity


@dataclass(frozen=True, kw_only=True)
class NibeBinarySensorDescription(BinarySensorEntityDescription):
    """Describes a binary sensor and the bus field behind it."""

    field_id: str


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
