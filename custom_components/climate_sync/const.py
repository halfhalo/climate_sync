"""Constants for the Climate Sync integration."""

DOMAIN = "climate_sync"

# Configuration keys
CONF_SOURCE_CLIMATE = "source_climate"
CONF_TARGET_CLIMATE = "target_climate"
CONF_ENABLE_TEMP_OFFSET = "enable_temp_offset"
CONF_ENABLE_BOOST_MODE = "enable_boost_mode"
CONF_OFFSET_SENSITIVITY = "offset_sensitivity"
CONF_SYNC_INTERVAL = "sync_interval"

# Default values
DEFAULT_ENABLE_TEMP_OFFSET = True
DEFAULT_ENABLE_BOOST_MODE = True
DEFAULT_OFFSET_SENSITIVITY = 1.0
DEFAULT_SYNC_INTERVAL = 5  # minutes

# Boost mode timing
BOOST_ACTIVATION_DELAY = 15  # minutes - how long to wait before activating boost
BOOST_MINIMUM_RUNTIME = 10  # minutes - minimum time to stay in boost mode