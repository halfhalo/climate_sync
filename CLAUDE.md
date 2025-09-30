# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Climate Sync is a Home Assistant custom integration that synchronizes one climate entity (source) to control another climate entity (target). It enables smart thermostat control by syncing HVAC modes, temperatures, and applying advanced features like temperature offset compensation and boost mode.

## Architecture

### Core Components

- **`__init__.py`**: Main integration entry point containing `ClimateSyncManager` class
  - Handles setup/teardown of config entries
  - Manages state synchronization between source and target climate entities
  - Implements two operating modes: normal sync and boost mode
  - Uses event-driven architecture via `async_track_state_change_event`

- **`config_flow.py`**: UI configuration handler
  - `ClimateSyncConfigFlow`: Initial setup flow for selecting source/target entities
  - `ClimateSyncOptionsFlow`: Runtime configuration updates without reload
  - Validates source ≠ target and creates unique IDs to prevent duplicates

- **`const.py`**: Constants and default values for configuration options

### Key Operating Modes

**Normal Mode** (`_async_sync_normal_mode`):
- Syncs HVAC mode from source to target
- Syncs temperature setpoints with optional offset compensation
- Offset calculation: `target_setpoint = source_setpoint + (source_temp - target_temp) × sensitivity`
- Supports both single setpoint (heat/cool) and dual setpoint (auto) modes

**Boost Mode** (`_async_activate_boost_mode`):
- Activated when `source.hvac_action` is `HEATING` or `COOLING` (actively running)
- Saves current fan_mode and swing_mode on entry
- Sets extreme temperatures (max for heating, min for cooling)
- Sets fan to first available: powerful → high → auto
- Sets swing/vane to auto if supported
- Restores saved settings when exiting back to normal mode

### State Management

- `_syncing` flag prevents recursive state updates
- `_boost_active` tracks boost mode state to handle entry/exit transitions
- `_saved_fan_mode` and `_saved_swing_mode` preserve user settings during boost
- Options are stored in `config_entry.options` with fallback to `config_entry.data`

## Development Commands

This is a Home Assistant custom integration. Testing requires a running Home Assistant instance.

### Installation for Development

```bash
# Link integration to Home Assistant config directory
ln -s /path/to/climate_sync/custom_components/climate_sync ~/.homeassistant/custom_components/

# Restart Home Assistant to load the integration
```

### Enable Debug Logging

Add to Home Assistant `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.climate_sync: debug
```

## Important Implementation Details

- The integration reloads on options change via `async_update_options` listener
- State changes are handled via callbacks decorated with `@callback` for performance
- All service calls use `blocking=True` to ensure sequential execution
- Temperature offset supports fractional sensitivity (0.1-5.0) for fine-tuning
- Boost mode checks `hvac_action` (actual state) not `hvac_mode` (intent)
- Multiple instances are supported - each source→target pair is independent

## Home Assistant Integration Type

- **Integration Type**: `service` (modifies behavior of existing entities)
- **IoT Class**: `calculated` (derives state from other entities)
- **Config Flow**: UI-based configuration (no YAML required)
- **Minimum HA Version**: 2023.1.0
