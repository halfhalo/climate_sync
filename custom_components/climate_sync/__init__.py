"""The Climate Sync integration."""

from __future__ import annotations

from datetime import timedelta
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
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval

from .const import (
    DOMAIN,
    CONF_SOURCE_CLIMATE,
    CONF_TARGET_CLIMATE,
    CONF_ENABLE_TEMP_OFFSET,
    CONF_ENABLE_BOOST_MODE,
    CONF_OFFSET_SENSITIVITY,
    CONF_SYNC_INTERVAL,
    DEFAULT_SYNC_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Climate Sync from a config entry."""
    source_entity = entry.data[CONF_SOURCE_CLIMATE]
    target_entity = entry.data[CONF_TARGET_CLIMATE]

    _LOGGER.info(
        "Setting up Climate Sync: %s → %s",
        source_entity,
        target_entity,
    )

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
    sync_interval = entry.options.get(
        CONF_SYNC_INTERVAL, entry.data.get(CONF_SYNC_INTERVAL, DEFAULT_SYNC_INTERVAL)
    )

    _LOGGER.debug(
        "Configuration: temp_offset=%s, boost_mode=%s, sensitivity=%.1f, sync_interval=%d min",
        enable_temp_offset,
        enable_boost_mode,
        offset_sensitivity,
        sync_interval,
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

    _LOGGER.debug("State change listener registered for %s", source_entity)

    # Set up periodic sync check
    async def periodic_sync(now):
        """Perform periodic sync check."""
        _LOGGER.debug("Periodic sync check triggered at %s", now)
        await sync_manager.async_sync_state()

    entry.async_on_unload(
        async_track_time_interval(
            hass,
            periodic_sync,
            timedelta(minutes=sync_interval),
        )
    )

    _LOGGER.info("Periodic sync scheduled every %d minutes", sync_interval)

    # Perform initial sync
    _LOGGER.debug("Performing initial sync")
    await sync_manager.async_sync_state()

    # Listen for options updates
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    _LOGGER.info("Climate Sync setup completed successfully")
    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    _LOGGER.info("Options updated, reloading integration")
    # Reload the integration when options change
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.info("Unloading Climate Sync integration")
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
            _LOGGER.debug("Sync already in progress, skipping")
            return

        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")

        if new_state is None or new_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            _LOGGER.debug(
                "Source state unavailable or unknown: %s",
                new_state.state if new_state else "None",
            )
            return

        _LOGGER.info(
            "Source state changed: %s → %s (action: %s)",
            old_state.state if old_state else "unknown",
            new_state.state,
            new_state.attributes.get("hvac_action", "unknown"),
        )

        # Schedule sync
        self.hass.async_create_task(self.async_sync_state())

    async def async_sync_state(self) -> None:
        """Synchronize the target climate entity with the source."""
        if self._syncing:
            _LOGGER.debug("Sync already in progress, skipping")
            return

        self._syncing = True
        _LOGGER.debug("Starting sync operation")

        try:
            source_state = self.hass.states.get(self.source_entity)
            target_state = self.hass.states.get(self.target_entity)

            if not source_state or not target_state:
                _LOGGER.warning(
                    "Source or target entity not found: source=%s (found=%s), target=%s (found=%s)",
                    self.source_entity,
                    source_state is not None,
                    self.target_entity,
                    target_state is not None,
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

            _LOGGER.debug(
                "Source state: mode=%s, action=%s, current_temp=%s, target_temp=%s, low=%s, high=%s",
                source_hvac_mode,
                source_hvac_action,
                source_temp,
                source_target_temp,
                source_target_temp_low,
                source_target_temp_high,
            )

            # Get target properties
            target_temp = target_state.attributes.get("current_temperature")
            target_min_temp = target_state.attributes.get("min_temp", 16)
            target_max_temp = target_state.attributes.get("max_temp", 30)
            target_fan_modes = target_state.attributes.get("fan_modes", [])
            target_swing_modes = target_state.attributes.get("swing_modes", [])

            _LOGGER.debug(
                "Target state: mode=%s, current_temp=%s, min=%s, max=%s, fan_modes=%s, swing_modes=%s",
                target_state.state,
                target_temp,
                target_min_temp,
                target_max_temp,
                target_fan_modes,
                target_swing_modes,
            )

            # Check if boost mode should be activated
            is_actively_heating_or_cooling = source_hvac_action in (
                HVACAction.HEATING,
                HVACAction.COOLING,
            )

            _LOGGER.debug(
                "Boost mode check: enabled=%s, actively_heating_cooling=%s, action=%s",
                self.enable_boost_mode,
                is_actively_heating_or_cooling,
                source_hvac_action,
            )

            if self.enable_boost_mode and is_actively_heating_or_cooling:
                _LOGGER.info("Activating boost mode for %s", source_hvac_action)
                await self._async_activate_boost_mode(
                    source_hvac_action,
                    target_state,
                    target_min_temp,
                    target_max_temp,
                    target_fan_modes,
                    target_swing_modes,
                )
            else:
                _LOGGER.info("Syncing in normal mode")
                # Normal sync mode (or exiting boost mode)
                await self._async_sync_normal_mode(
                    source_hvac_mode,
                    source_target_temp,
                    source_target_temp_low,
                    source_target_temp_high,
                    source_temp,
                    target_temp,
                    target_min_temp,
                    target_max_temp,
                )

            _LOGGER.debug("Sync operation completed successfully")

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
            _LOGGER.info(
                "Entering boost mode - saved fan_mode: %s, swing_mode: %s",
                self._saved_fan_mode,
                self._saved_swing_mode,
            )
            self._boost_active = True

        # Set extreme temperature based on action
        if hvac_action == HVACAction.HEATING:
            boost_temp = target_max_temp
            hvac_mode = HVACMode.HEAT
        else:  # COOLING
            boost_temp = target_min_temp
            hvac_mode = HVACMode.COOL

        _LOGGER.info(
            "Boost mode: setting %s to mode=%s, temp=%s",
            self.target_entity,
            hvac_mode,
            boost_temp,
        )

        # Set HVAC mode and temperature
        try:
            await self.hass.services.async_call(
                CLIMATE_DOMAIN,
                SERVICE_SET_HVAC_MODE,
                {
                    ATTR_ENTITY_ID: self.target_entity,
                    ATTR_HVAC_MODE: hvac_mode,
                },
                blocking=True,
            )
            _LOGGER.debug("HVAC mode set to %s", hvac_mode)
        except Exception as e:
            _LOGGER.error("Failed to set HVAC mode: %s", e)
            raise

        try:
            await self.hass.services.async_call(
                CLIMATE_DOMAIN,
                SERVICE_SET_TEMPERATURE,
                {
                    ATTR_ENTITY_ID: self.target_entity,
                    ATTR_TEMPERATURE: boost_temp,
                },
                blocking=True,
            )
            _LOGGER.debug("Temperature set to %s", boost_temp)
        except Exception as e:
            _LOGGER.error("Failed to set temperature: %s", e)
            raise

        # Set fan to max if available
        max_fan_modes = ["powerful", "high", "auto"]
        selected_fan = None
        for fan_mode in max_fan_modes:
            if fan_mode in target_fan_modes:
                selected_fan = fan_mode
                break

        if selected_fan:
            _LOGGER.debug("Setting fan mode to %s", selected_fan)
            try:
                await self.hass.services.async_call(
                    CLIMATE_DOMAIN,
                    SERVICE_SET_FAN_MODE,
                    {
                        ATTR_ENTITY_ID: self.target_entity,
                        "fan_mode": selected_fan,
                    },
                    blocking=True,
                )
                _LOGGER.debug("Fan mode set successfully")
            except Exception as e:
                _LOGGER.error("Failed to set fan mode: %s", e)
                raise
        else:
            _LOGGER.debug("No suitable fan mode found in %s", target_fan_modes)

        # Set swing/vane to auto if available
        if "auto" in target_swing_modes:
            _LOGGER.debug("Setting swing mode to auto")
            try:
                await self.hass.services.async_call(
                    CLIMATE_DOMAIN,
                    SERVICE_SET_SWING_MODE,
                    {
                        ATTR_ENTITY_ID: self.target_entity,
                        "swing_mode": "auto",
                    },
                    blocking=True,
                )
                _LOGGER.debug("Swing mode set successfully")
            except Exception as e:
                _LOGGER.error("Failed to set swing mode: %s", e)
                raise
        else:
            _LOGGER.debug("Auto swing mode not available in %s", target_swing_modes)

    async def _async_sync_normal_mode(
        self,
        source_hvac_mode: str,
        source_target_temp: float | None,
        source_target_temp_low: float | None,
        source_target_temp_high: float | None,
        source_temp: float | None,
        target_temp: float | None,
        target_min_temp: float,
        target_max_temp: float,
    ) -> None:
        """Sync normal mode: match HVAC mode and temperature with optional offset."""
        # Restore saved settings if exiting boost mode
        if self._boost_active:
            _LOGGER.info(
                "Exiting boost mode - restoring fan_mode: %s, swing_mode: %s",
                self._saved_fan_mode,
                self._saved_swing_mode,
            )

            # Restore fan mode
            if self._saved_fan_mode:
                try:
                    await self.hass.services.async_call(
                        CLIMATE_DOMAIN,
                        SERVICE_SET_FAN_MODE,
                        {
                            ATTR_ENTITY_ID: self.target_entity,
                            "fan_mode": self._saved_fan_mode,
                        },
                        blocking=True,
                    )
                    _LOGGER.debug("Fan mode restored to %s", self._saved_fan_mode)
                except Exception as e:
                    _LOGGER.error("Failed to restore fan mode: %s", e)

            # Restore swing mode
            if self._saved_swing_mode:
                try:
                    await self.hass.services.async_call(
                        CLIMATE_DOMAIN,
                        SERVICE_SET_SWING_MODE,
                        {
                            ATTR_ENTITY_ID: self.target_entity,
                            "swing_mode": self._saved_swing_mode,
                        },
                        blocking=True,
                    )
                    _LOGGER.debug("Swing mode restored to %s", self._saved_swing_mode)
                except Exception as e:
                    _LOGGER.error("Failed to restore swing mode: %s", e)

            # Reset boost state
            self._boost_active = False
            self._saved_fan_mode = None
            self._saved_swing_mode = None

        # Sync HVAC mode
        _LOGGER.info("Setting HVAC mode to %s", source_hvac_mode)
        try:
            await self.hass.services.async_call(
                CLIMATE_DOMAIN,
                SERVICE_SET_HVAC_MODE,
                {
                    ATTR_ENTITY_ID: self.target_entity,
                    ATTR_HVAC_MODE: source_hvac_mode,
                },
                blocking=True,
            )
            _LOGGER.debug("HVAC mode set successfully")
        except Exception as e:
            _LOGGER.error("Failed to set HVAC mode: %s", e)
            raise

        # Calculate temperature offset if enabled
        temp_offset = 0.0
        if (
            self.enable_temp_offset
            and source_temp is not None
            and target_temp is not None
        ):
            temp_offset = (source_temp - target_temp) * self.offset_sensitivity
            _LOGGER.info(
                "Temperature offset: %.1f°C (source: %.1f°C, target: %.1f°C, sensitivity: %.1f)",
                temp_offset,
                source_temp,
                target_temp,
                self.offset_sensitivity,
            )
        elif self.enable_temp_offset:
            _LOGGER.debug(
                "Offset enabled but missing temps: source=%s, target=%s",
                source_temp,
                target_temp,
            )

        # Sync temperature setpoints
        service_data: dict[str, Any] = {ATTR_ENTITY_ID: self.target_entity}

        if source_hvac_mode == HVACMode.HEAT_COOL:
            # Auto mode: use both low and high temps
            temp_low = None
            temp_high = None

            if source_target_temp_low is not None:
                calculated_low = source_target_temp_low + temp_offset
                temp_low = max(target_min_temp, min(target_max_temp, calculated_low))
                if temp_low != calculated_low:
                    _LOGGER.warning(
                        "Clamped target_temp_low from %.1f to %.1f (range: %.1f-%.1f)",
                        calculated_low,
                        temp_low,
                        target_min_temp,
                        target_max_temp,
                    )

            if source_target_temp_high is not None:
                calculated_high = source_target_temp_high + temp_offset
                temp_high = max(target_min_temp, min(target_max_temp, calculated_high))
                if temp_high != calculated_high:
                    _LOGGER.warning(
                        "Clamped target_temp_high from %.1f to %.1f (range: %.1f-%.1f)",
                        calculated_high,
                        temp_high,
                        target_min_temp,
                        target_max_temp,
                    )

            # Ensure low <= high if both are set
            if temp_low is not None and temp_high is not None:
                if temp_low > temp_high:
                    _LOGGER.warning(
                        "Auto mode: low temp (%.1f) > high temp (%.1f), adjusting to ensure low <= high",
                        temp_low,
                        temp_high,
                    )
                    # Swap them to maintain valid range
                    temp_low, temp_high = temp_high, temp_low

                service_data["target_temp_low"] = temp_low
                service_data["target_temp_high"] = temp_high
            elif temp_low is not None:
                service_data["target_temp_low"] = temp_low
            elif temp_high is not None:
                service_data["target_temp_high"] = temp_high

            _LOGGER.info(
                "Setting auto mode temps: low=%s, high=%s",
                service_data.get("target_temp_low"),
                service_data.get("target_temp_high"),
            )
        elif source_target_temp is not None:
            # Single setpoint modes (heat, cool)
            calculated_temp = source_target_temp + temp_offset
            clamped_temp = max(target_min_temp, min(target_max_temp, calculated_temp))
            service_data[ATTR_TEMPERATURE] = clamped_temp
            if clamped_temp != calculated_temp:
                _LOGGER.warning(
                    "Clamped temperature from %.1f to %.1f (range: %.1f-%.1f)",
                    calculated_temp,
                    clamped_temp,
                    target_min_temp,
                    target_max_temp,
                )
            _LOGGER.info(
                "Setting target temp: %s (source: %s, offset: %.1f)",
                service_data[ATTR_TEMPERATURE],
                source_target_temp,
                temp_offset,
            )
        else:
            _LOGGER.debug("No temperature setpoint available from source")

        # Only call service if we have temperature data
        if len(service_data) > 1:  # More than just entity_id
            try:
                await self.hass.services.async_call(
                    CLIMATE_DOMAIN,
                    SERVICE_SET_TEMPERATURE,
                    service_data,
                    blocking=True,
                )
                _LOGGER.debug("Temperature set successfully")
            except Exception as e:
                _LOGGER.error("Failed to set temperature: %s", e)
                raise
        else:
            _LOGGER.debug("No temperature data to sync")