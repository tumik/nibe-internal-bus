"""Config and options flow for the Nibe internal-bus integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_PUSH_INTERVAL,
    DEFAULT_PORT,
    DEFAULT_PUSH_INTERVAL,
    DOMAIN,
    MAX_PUSH_INTERVAL,
    MIN_PUSH_INTERVAL,
)
from .coordinator import CannotConnect, NoPumpData, NoValidFrames, async_probe

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): cv.string,
        vol.Required(CONF_PORT, default=DEFAULT_PORT): cv.port,
    }
)


class NibeInternalBusConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for the nibegw device's address and confirm it forwards bus data."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]

            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            try:
                await async_probe(self.hass, host, port)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except NoValidFrames:
                errors["base"] = "no_valid_frames"
            except NoPumpData:
                errors["base"] = "no_pump_data"
            else:
                return self.async_create_entry(
                    title=f"Nibe F1226 ({host})", data=user_input
                )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        """Return the options flow."""
        return NibeInternalBusOptionsFlow()


class NibeInternalBusOptionsFlow(OptionsFlow):
    """Tune how often decoded values are pushed into Home Assistant."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_PUSH_INTERVAL,
                        default=self.config_entry.options.get(
                            CONF_PUSH_INTERVAL, DEFAULT_PUSH_INTERVAL
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(min=MIN_PUSH_INTERVAL, max=MAX_PUSH_INTERVAL),
                    )
                }
            ),
        )
