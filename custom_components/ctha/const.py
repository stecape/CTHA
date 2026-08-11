"""Costanti condivise dell'integrazione CTHA."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "ctha"

# --- Config entry -----------------------------------------------------------
# La entry descrive il legame hardware di una zona; il programma settimanale
# vive nello Store (vedi store.py), non nelle opzioni della entry.
CONF_SENSOR: Final = "sensor_entity_id"
CONF_HEATER: Final = "heater_entity_id"
CONF_COLD_TOLERANCE: Final = "cold_tolerance"
CONF_HOT_TOLERANCE: Final = "hot_tolerance"
CONF_MIN_CYCLE_DURATION: Final = "min_cycle_duration"

# Isteresi di default (°C)
DEFAULT_COLD_TOLERANCE: Final = 0.3
DEFAULT_HOT_TOLERANCE: Final = 0.3

# --- Storage ----------------------------------------------------------------
STORAGE_VERSION: Final = 1
STORAGE_KEY: Final = f"{DOMAIN}.data"

# --- Asse temporale ---------------------------------------------------------
# Un day template è una stringa di 48 caratteri: un carattere ogni 30 minuti.
SLOT_MINUTES: Final = 30
SLOTS_PER_DAY: Final = 48

# Carattere che rappresenta esplicitamente l'ereditarietà dal livello globale:
# nel modello dati corrisponde a `null`, nella stringa a questo segnaposto.
INHERIT_CHAR: Final = "-"

# --- Asse termico -----------------------------------------------------------
LEVEL_COMFORT: Final = "comfort"
LEVEL_ECO: Final = "eco"
LEVEL_ANTIFREEZE: Final = "antifreeze"

# Mappa carattere del day template -> identificatore di livello.
LEVEL_BY_CHAR: Final[dict[str, str]] = {
    "c": LEVEL_COMFORT,
    "e": LEVEL_ECO,
    "a": LEVEL_ANTIFREEZE,
}
CHAR_BY_LEVEL: Final[dict[str, str]] = {
    level: char for char, level in LEVEL_BY_CHAR.items()
}

# Setpoint globali di default (°C), radice dell'ereditarietà termica.
DEFAULT_GLOBAL_SETPOINTS: Final[dict[str, float]] = {
    LEVEL_COMFORT: 21.0,
    LEVEL_ECO: 18.0,
    LEVEL_ANTIFREEZE: 7.0,
}

# Giornata tipo: notte in eco, risveglio e sera in comfort.
DEFAULT_DAY_SLOTS: Final = "e" * 12 + "c" * 5 + "e" * 17 + "c" * 11 + "e" * 3

DEFAULT_SCENARIO_ID: Final = "default"
DEFAULT_WEEK_TEMPLATE_ID: Final = "default"
DEFAULT_DAY_TEMPLATE_ID: Final = "default"

# --- Override ---------------------------------------------------------------
# Tre sorgenti fondamentalmente distinte, gestite in modo differenziato.
OVERRIDE_SOURCE_HA: Final = "ha"
OVERRIDE_SOURCE_EXTERNAL: Final = "external"
OVERRIDE_SOURCE_HARDWARE: Final = "hardware"

# Politiche di scadenza.
POLICY_NEXT_SLOT: Final = "next_slot"
POLICY_DURATION: Final = "duration"
POLICY_UNTIL_SCENARIO_CHANGE: Final = "until_scenario_change"
POLICY_STICKY: Final = "sticky"

OVERRIDE_POLICIES: Final[tuple[str, ...]] = (
    POLICY_NEXT_SLOT,
    POLICY_DURATION,
    POLICY_UNTIL_SCENARIO_CHANGE,
    POLICY_STICKY,
)

# Finestra entro cui una variazione di setpoint è considerata l'eco di una
# nostra scrittura, e non un override esterno da registrare.
ECHO_WINDOW: Final = timedelta(seconds=60)
ECHO_DEADBAND: Final = 0.15

# --- Riconciliazione --------------------------------------------------------
# Il watchdog riscrive periodicamente i setpoint desiderati per contrastare la
# riasserzione del programma da parte dell'unità centrale.
RECONCILE_INTERVAL: Final = timedelta(minutes=12)

# Ritardo fra una scrittura di zona e la successiva, per non saturare il bus.
WRITE_STAGGER_SECONDS: Final = 1.5

# --- Limiti del setpoint (°C) ----------------------------------------------
MIN_TEMP: Final = 5.0
MAX_TEMP: Final = 30.0
TEMP_STEP: Final = 0.5

# --- Servizi ----------------------------------------------------------------
SERVICE_SET_OVERRIDE: Final = "set_override"
SERVICE_CLEAR_OVERRIDE: Final = "clear_override"

ATTR_ZONE_ID: Final = "zone_id"
ATTR_POLICY: Final = "policy"
ATTR_DURATION: Final = "duration"
