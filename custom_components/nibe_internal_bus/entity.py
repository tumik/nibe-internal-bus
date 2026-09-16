"""Base entity for the Nibe internal-bus integration."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import NibeInternalBusCoordinator


class NibeInternalBusEntity(CoordinatorEntity[NibeInternalBusCoordinator]):
    """Common device info, naming and staleness handling."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: NibeInternalBusCoordinator,
        description: EntityDescription,
        field_id: str | None,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._field_id = field_id
        self._attr_translation_key = description.key
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="Nibe",
            model="F1226",
            name="Nibe F1226",
            configuration_url=f"http://{coordinator.host}",
        )

    @property
    def available(self) -> bool:
        """Unavailable once this field's frame stops arriving on the bus."""
        if not super().available:
            return False
        if self._field_id is None:
            return self.coordinator.last_datagram is not None
        return self.coordinator.is_fresh(self._field_id)
