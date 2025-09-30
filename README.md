# Climate Sync for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)

A Home Assistant custom integration that synchronizes one climate entity (source) to control another climate entity (target). Perfect for syncing thermostats like Nest to control mini-split systems like Kumo Cloud.

## Features

- **Universal Compatibility**: Works with any Home Assistant climate entities
- **Temperature Offset Compensation**: Automatically adjusts target setpoint based on temperature sensor differences
- **Boost Mode**: When source is actively heating/cooling:
  - Sets target fan to maximum speed
  - Sets extreme temperature (max for heating, min for cooling)
  - Sets vanes/swing to auto (if supported)
  - Restores original fan and swing settings when done
- **Multiple Instances**: Configure multiple source→target pairs for different rooms
- **Configurable Options**:
  - Enable/disable temperature offset compensation
  - Enable/disable boost mode
  - Adjust offset sensitivity multiplier
- **UI Configuration**: Easy setup through Home Assistant UI

## Use Cases

- Sync Nest thermostat → Kumo Cloud mini-split
- Sync Ecobee → any climate entity
- Use one thermostat's sensor to control another unit
- Compensate for temperature differences between thermostat and controlled unit locations

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click on "Integrations"
3. Click the three dots in the top right corner
4. Select "Custom repositories"
5. Add the repository URL: `https://github.com/yourusername/climate_sync`
6. Select category: "Integration"
7. Click "Add"
8. Find "Climate Sync" in HACS and install it
9. Restart Home Assistant

### Manual Installation

1. Copy the `custom_components/climate_sync` directory to your Home Assistant `custom_components` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings** → **Devices & Services**
2. Click **"+ Add Integration"**
3. Search for **"Climate Sync"**
4. Select your source climate entity (e.g., Nest thermostat)
5. Select your target climate entity (e.g., Kumo Cloud mini-split)
6. Configure options:
   - **Enable Temperature Offset Compensation**: Adjusts target setpoint when source and target sensors read different temperatures
   - **Enable Boost Mode**: Activates max fan and extreme temps when source is actively heating/cooling
   - **Temperature Offset Sensitivity Multiplier**: How aggressively to compensate (1.0 = 1:1 ratio, higher = more aggressive)

## How It Works

### Normal Mode

When the source thermostat changes state, Climate Sync:
1. Syncs HVAC mode (heat, cool, auto, off)
2. Syncs temperature setpoints
3. Optionally applies temperature offset based on sensor difference

**Example**:
- Source reads 70°F, target reads 68°F (2°F difference)
- Source setpoint is 72°F
- With sensitivity 1.0, target setpoint becomes 74°F (72 + 2)

### Boost Mode

When the source thermostat is **actively** heating or cooling (not just set to heat/cool mode):
1. **Saves** current fan mode and swing mode
2. **Sets** fan to: `powerful` → `high` → `auto` (first available)
3. **Sets** swing/vane to `auto` (if supported)
4. **Sets** extreme temperature:
   - Heating: Maximum supported temperature
   - Cooling: Minimum supported temperature

When source stops actively heating/cooling:
1. **Restores** saved fan mode
2. **Restores** saved swing mode
3. **Returns** to normal temperature sync

## Options

You can modify settings after setup:
1. Go to **Settings** → **Devices & Services**
2. Find the **Climate Sync** integration
3. Click **"Configure"**

## Multiple Instances

You can create as many sync pairs as needed:
- Living Room Nest → Living Room Kumo
- Bedroom Nest → Bedroom Kumo
- Office Nest → Office Kumo

Each instance runs independently with its own settings.

## Troubleshooting

### Sync not working
- Check both source and target entities are available
- Enable debug logging to see sync events

### Temperature offset too aggressive/not enough
- Adjust the **Offset Sensitivity Multiplier**
- 0.5 = half the difference
- 1.0 = full difference (default)
- 2.0 = double the difference

### Debug Logging

Add to `configuration.yaml`:
```yaml
logger:
  default: info
  logs:
    custom_components.climate_sync: debug
```

## License

MIT License

## Contributing

Contributions are welcome! Please open an issue or pull request.

## Credits

Created to solve the challenge of syncing Nest thermostats with Mitsubishi mini-splits via Kumo Cloud.