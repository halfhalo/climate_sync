"""Config flow for Climate Sync integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import selector
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_SOURCE_CLIMATE,
    CONF_TARGET_CLIMATE,
    CONF_ENABLE_TEMP_OFFSET,
    CONF_ENABLE_BOOST_MODE,
    CONF_OFFSET_SENSITIVITY,
    DEFAULT_ENABLE_TEMP_OFFSET,
    DEFAULT_ENABLE_BOOST_MODE,
    DEFAULT_OFFSET_SENSITIVITY,
)

_LOGGER = logging.getLogger(__name__)


class ClimateSyncConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Climate Sync."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # Validate that source and target are different
            if user_input[CONF_SOURCE_CLIMATE] == user_input[CONF_TARGET_CLIMATE]:
                errors["base"] = "same_climate"
            else:
                # Create unique ID from source and target
                await self.async_set_unique_id(
                    f"{user_input[CONF_SOURCE_CLIMATE]}_{user_input[CONF_TARGET_CLIMATE]}"
                )
                self._abort_if_unique_id_configured()

                # Set default options if not provided
                user_input.setdefault(CONF_ENABLE_TEMP_OFFSET, DEFAULT_ENABLE_TEMP_OFFSET)
                user_input.setdefault(CONF_ENABLE_BOOST_MODE, DEFAULT_ENABLE_BOOST_MODE)
                user_input.setdefault(CONF_OFFSET_SENSITIVITY, DEFAULT_OFFSET_SENSITIVITY)

                return self.async_create_entry(
                    title=f"{user_input[CONF_SOURCE_CLIMATE]} → {user_input[CONF_TARGET_CLIMATE]}",
                    data=user_input,
                )

        data_schema = vol.Schema(
            {
                vol.Required(CONF_SOURCE_CLIMATE): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=CLIMATE_DOMAIN)
                ),
                vol.Required(CONF_TARGET_CLIMATE): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=CLIMATE_DOMAIN)
                ),
                vol.Optional(
                    CONF_ENABLE_TEMP_OFFSET,
                    default=DEFAULT_ENABLE_TEMP_OFFSET,
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_ENABLE_BOOST_MODE,
                    default=DEFAULT_ENABLE_BOOST_MODE,
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_OFFSET_SENSITIVITY,
                    default=DEFAULT_OFFSET_SENSITIVITY,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.1,
                        max=5.0,
                        step=0.1,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> ClimateSyncOptionsFlow:
        """Get the options flow for this handler."""
        return ClimateSyncOptionsFlow(config_entry)


class ClimateSyncOptionsFlow(config_entries.OptionsFlow):
    """Handle options flow for Climate Sync."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_ENABLE_TEMP_OFFSET,
                    default=self.config_entry.data.get(
                        CONF_ENABLE_TEMP_OFFSET, DEFAULT_ENABLE_TEMP_OFFSET
                    ),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_ENABLE_BOOST_MODE,
                    default=self.config_entry.data.get(
                        CONF_ENABLE_BOOST_MODE, DEFAULT_ENABLE_BOOST_MODE
                    ),
                ): selector.BooleanSelector(),
                vol.Optional(
                    CONF_OFFSET_SENSITIVITY,
                    default=self.config_entry.data.get(
                        CONF_OFFSET_SENSITIVITY, DEFAULT_OFFSET_SENSITIVITY
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.1,
                        max=5.0,
                        step=0.1,
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=data_schema)