"""The Nibe internal-bus integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import CONF_PUSH_INTERVAL, DEFAULT_PUSH_INTERVAL
from .coordinator import NibeInternalBusCoordinator

NibeInternalBusConfigEntry = ConfigEntry[NibeInternalBusCoordinator]

PLATFORMS: list[Platform] = [Platform.BINARY_SENSOR, Platform.SENSOR]


async def async_setup_entry(
    hass: HomeAssistant, entry: NibeInternalBusConfigEntry
) -> bool:
    """Set up a nibegw device from a config entry."""
    coordinator = NibeInternalBusCoordinator(
        hass,
        entry,
        entry.data[CONF_HOST],
        entry.data[CONF_PORT],
        entry.options.get(CONF_PUSH_INTERVAL, DEFAULT_PUSH_INTERVAL),
    )

    await coordinator.async_start()
    if not await coordinator.async_wait_for_data():
        await coordinator.async_stop()
        raise ConfigEntryNotReady(
            f"No bus frames received from {entry.data[CONF_HOST]}"
        )

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: NibeInternalBusConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_stop()
    return unload_ok


async def _async_update_listener(
    hass: HomeAssistant, entry: NibeInternalBusConfigEntry
) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
