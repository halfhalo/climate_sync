"""The Climate Sync integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_FAN_MODE,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_SWING_MODE,
    SERVICE_SET_TEMPERATURE,
    ATTR_HVAC_MODE,
    ATTR_TEMPERATURE,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    DOMAIN,
    CONF_SOURCE_CLIMATE,
    CONF_TARGET_CLIMATE,
    CONF_ENABLE_TEMP_OFFSET,
    CONF_ENABLE_BOOST_MODE,
    CONF_OFFSET_SENSITIVITY,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Climate Sync from a config entry."""
    source_entity = entry.data[CONF_SOURCE_CLIMATE]
    target_entity = entry.data[CONF_TARGET_CLIMATE]

    # Get options with fallback to data
    enable_temp_offset = entry.options.get(
        CONF_ENABLE_TEMP_OFFSET, entry.data.get(CONF_ENABLE_TEMP_OFFSET, True)
    )
    enable_boost_mode = entry.options.get(
        CONF_ENABLE_BOOST_MODE, entry.data.get(CONF_ENABLE_BOOST_MODE, True)
    )
    offset_sensitivity = entry.options.get(
        CONF_OFFSET_SENSITIVITY, entry.data.get(CONF_OFFSET_SENSITIVITY, 1.0)
    )

    sync_manager = ClimateSyncManager(
        hass,
        source_entity,
        target_entity,
        enable_temp_offset,
        enable_boost_mode,
        offset_sensitivity,
    )

    # Store the manager
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = sync_manager

    # Start listening for state changes
    entry.async_on_unload(
        async_track_state_change_event(
            hass, source_entity, sync_manager.async_source_changed
        )
    )

    # Perform initial sync
    await sync_manager.async_sync_state()

    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    # Reload the integration when options change
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hass.data[DOMAIN].pop(entry.entry_id)
    return True


class ClimateSyncManager:
    """Manages synchronization between two climate entities."""

    def __init__(
        self,
        hass: HomeAssistant,
        source_entity: str,
        target_entity: str,
        enable_temp_offset: bool,
        enable_boost_mode: bool,
        offset_sensitivity: float,
    ) -> None:
        """Initialize the sync manager."""
        self.hass = hass
        self.source_entity = source_entity
        self.target_entity = target_entity
        self.enable_temp_offset = enable_temp_offset
        self.enable_boost_mode = enable_boost_mode
        self.offset_sensitivity = offset_sensitivity
        self._syncing = False  # Prevent recursive updates
        self._boost_active = False  # Track if boost mode is active
        self._saved_fan_mode: str | None = None  # Save fan mode before boost
        self._saved_swing_mode: str | None = None  # Save swing mode before boost

    @callback
    def async_source_changed(self, event: Event) -> None:
        """Handle state changes from the source climate entity."""
        if self._syncing:
            return

        new_state = event.data.get("new_state")
        if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return

        # Schedule sync
        self.hass.async_create_task(self.async_sync_state())

    async def async_sync_state(self) -> None:
        """Synchronize the target climate entity with the source."""
        if self._syncing:
            return

        self._syncing = True
        try:
            source_state = self.hass.states.get(self.source_entity)
            target_state = self.hass.states.get(self.target_entity)

            if not source_state or not target_state:
                _LOGGER.warning(
                    "Source or target entity not found: %s, %s",
                    self.source_entity,
                    self.target_entity,
                )
                return

            if source_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                _LOGGER.debug("Source entity unavailable, skipping sync")
                return

            # Get source properties
            source_hvac_mode = source_state.state
            source_hvac_action = source_state.attributes.get("hvac_action")
            source_temp = source_state.attributes.get("current_temperature")
            source_target_temp = source_state.attributes.get("temperature")
            source_target_temp_low = source_state.attributes.get("target_temp_low")
            source_target_temp_high = source_state.attributes.get("target_temp_high")

            # Get target properties
            target_temp = target_state.attributes.get("current_temperature")
            target_min_temp = target_state.attributes.get("min_temp", 16)
            target_max_temp = target_state.attributes.get("max_temp", 30)
            target_fan_modes = target_state.attributes.get("fan_modes", [])
            target_swing_modes = target_state.attributes.get("swing_modes", [])

            # Check if boost mode should be activated
            is_actively_heating_or_cooling = source_hvac_action in (
                HVACAction.HEATING,
                HVACAction.COOLING,
            )

            if self.enable_boost_mode and is_actively_heating_or_cooling:
                await self._async_activate_boost_mode(
                    source_hvac_action,
                    target_state,
                    target_min_temp,
                    target_max_temp,
                    target_fan_modes,
                    target_swing_modes,
                )
            else:
                # Normal sync mode (or exiting boost mode)
                await self._async_sync_normal_mode(
                    source_hvac_mode,
                    source_target_temp,
                    source_target_temp_low,
                    source_target_temp_high,
                    source_temp,
                    target_temp,
                )

        except Exception as e:
            _LOGGER.exception("Error syncing climate state: %s", e)
        finally:
            self._syncing = False

    async def _async_activate_boost_mode(
        self,
        hvac_action: str,
        target_state: State,
        target_min_temp: float,
        target_max_temp: float,
        target_fan_modes: list[str],
        target_swing_modes: list[str],
    ) -> None:
        """Activate boost mode: extreme setpoint and max fan speed."""
        # Save current settings on first activation
        if not self._boost_active:
            self._saved_fan_mode = target_state.attributes.get("fan_mode")
            self._saved_swing_mode = target_state.attributes.get("swing_mode")
            _LOGGER.debug(
                "Entering boost mode - saved fan_mode: %s, swing_mode: %s",
                self._saved_fan_mode,
                self._saved_swing_mode,
            )
            self._boost_active = True

        _LOGGER.debug("Activating boost mode for %s", hvac_action)

        # Set extreme temperature based on action
        if hvac_action == HVACAction.HEATING:
            boost_temp = target_max_temp
            hvac_mode = HVACMode.HEAT
        else:  # COOLING
            boost_temp = target_min_temp
            hvac_mode = HVACMode.COOL

        # Set HVAC mode and temperature
        await self.hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {
                ATTR_ENTITY_ID: self.target_entity,
                ATTR_HVAC_MODE: hvac_mode,
            },
            blocking=True,
        )

        await self.hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_TEMPERATURE,
            {
                ATTR_ENTITY_ID: self.target_entity,
                ATTR_TEMPERATURE: boost_temp,
            },
            blocking=True,
        )

        # Set fan to max if available
        max_fan_modes = ["powerful", "high", "auto"]
        selected_fan = None
        for fan_mode in max_fan_modes:
            if fan_mode in target_fan_modes:
                selected_fan = fan_mode
                break

        if selected_fan:
            await self.hass.services.async_call(
                CLIMATE_DOMAIN,
                SERVICE_SET_FAN_MODE,
                {
                    ATTR_ENTITY_ID: self.target_entity,
                    "fan_mode": selected_fan,
                },
                blocking=True,
            )

        # Set swing/vane to auto if available
        if "auto" in target_swing_modes:
            await self.hass.services.async_call(
                CLIMATE_DOMAIN,
                SERVICE_SET_SWING_MODE,
                {
                    ATTR_ENTITY_ID: self.target_entity,
                    "swing_mode": "auto",
                },
                blocking=True,
            )

    async def _async_sync_normal_mode(
        self,
        source_hvac_mode: str,
        source_target_temp: float | None,
        source_target_temp_low: float | None,
        source_target_temp_high: float | None,
        source_temp: float | None,
        target_temp: float | None,
    ) -> None:
        """Sync normal mode: match HVAC mode and temperature with optional offset."""
        # Restore saved settings if exiting boost mode
        if self._boost_active:
            _LOGGER.debug(
                "Exiting boost mode - restoring fan_mode: %s, swing_mode: %s",
                self._saved_fan_mode,
                self._saved_swing_mode,
            )

            # Restore fan mode
            if self._saved_fan_mode:
                await self.hass.services.async_call(
                    CLIMATE_DOMAIN,
                    SERVICE_SET_FAN_MODE,
                    {
                        ATTR_ENTITY_ID: self.target_entity,
                        "fan_mode": self._saved_fan_mode,
                    },
                    blocking=True,
                )

            # Restore swing mode
            if self._saved_swing_mode:
                await self.hass.services.async_call(
                    CLIMATE_DOMAIN,
                    SERVICE_SET_SWING_MODE,
                    {
                        ATTR_ENTITY_ID: self.target_entity,
                        "swing_mode": self._saved_swing_mode,
                    },
                    blocking=True,
                )

            # Reset boost state
            self._boost_active = False
            self._saved_fan_mode = None
            self._saved_swing_mode = None

        # Sync HVAC mode
        await self.hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {
                ATTR_ENTITY_ID: self.target_entity,
                ATTR_HVAC_MODE: source_hvac_mode,
            },
            blocking=True,
        )

        # Calculate temperature offset if enabled
        temp_offset = 0.0
        if (
            self.enable_temp_offset
            and source_temp is not None
            and target_temp is not None
        ):
            temp_offset = (source_temp - target_temp) * self.offset_sensitivity
            _LOGGER.debug(
                "Temperature offset: %.1f°C (source: %.1f°C, target: %.1f°C, sensitivity: %.1f)",
                temp_offset,
                source_temp,
                target_temp,
                self.offset_sensitivity,
            )

        # Sync temperature setpoints
        service_data: dict[str, Any] = {ATTR_ENTITY_ID: self.target_entity}

        if source_hvac_mode == HVACMode.HEAT_COOL:
            # Auto mode: use both low and high temps
            if source_target_temp_low is not None:
                service_data["target_temp_low"] = source_target_temp_low + temp_offset
            if source_target_temp_high is not None:
                service_data["target_temp_high"] = source_target_temp_high + temp_offset
        elif source_target_temp is not None:
            # Single setpoint modes (heat, cool)
            service_data[ATTR_TEMPERATURE] = source_target_temp + temp_offset

        # Only call service if we have temperature data
        if len(service_data) > 1:  # More than just entity_id
            await self.hass.services.async_call(
                CLIMATE_DOMAIN,
                SERVICE_SET_TEMPERATURE,
                service_data,
                blocking=True,
            )