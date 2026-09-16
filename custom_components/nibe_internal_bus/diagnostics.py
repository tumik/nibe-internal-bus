"""Diagnostics support for the Nibe internal-bus integration."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from . import NibeInternalBusConfigEntry

TO_REDACT = {CONF_HOST}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: NibeInternalBusConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "bus": {
            "frame_counts": dict(coordinator.frame_counts),
            "checksum_errors": coordinator.checksum_errors,
            "last_datagram_utc": coordinator.last_datagram_utc,
            "last_raw": coordinator.last_raw.hex(" ") if coordinator.last_raw else None,
        },
        "values": {
            field_id: {"value": value, "fresh": coordinator.is_fresh(field_id)}
            for field_id, value in sorted(coordinator.values.items())
        },
    }
