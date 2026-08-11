"""Costanti condivise dell'integrazione CTHA."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "ctha"

# Chiavi di configurazione (config flow / options flow)
CONF_SENSOR: Final = "sensor_entity_id"
CONF_HEATER: Final = "heater_entity_id"
CONF_COLD_TOLERANCE: Final = "cold_tolerance"
CONF_HOT_TOLERANCE: Final = "hot_tolerance"
CONF_MIN_CYCLE_DURATION: Final = "min_cycle_duration"
CONF_SCHEDULE: Final = "schedule"

# Preset supportati dal cronotermostato
PRESET_COMFORT: Final = "comfort"
PRESET_ECO: Final = "eco"
PRESET_ANTIFREEZE: Final = "antifreeze"

# Temperature di default per ciascun preset (°C)
DEFAULT_TEMP_COMFORT: Final = 21.0
DEFAULT_TEMP_ECO: Final = 18.0
DEFAULT_TEMP_ANTIFREEZE: Final = 7.0

# Isteresi di default (°C)
DEFAULT_COLD_TOLERANCE: Final = 0.3
DEFAULT_HOT_TOLERANCE: Final = 0.3

# Limiti del setpoint (°C)
MIN_TEMP: Final = 5.0
MAX_TEMP: Final = 30.0
TEMP_STEP: Final = 0.5
