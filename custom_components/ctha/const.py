"""Costanti condivise dell'integrazione CTHA."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "ctha"

# --- Config entry -----------------------------------------------------------
# La entry lega una zona al termostato che la governa: una entità `climate`
# già esistente (per l'impianto BTicino, quella creata da MyHOME per la zona).
# Il programma settimanale vive nello Store (vedi store.py), non nella entry.
CONF_TARGET: Final = "target_entity_id"

# Scostamento sotto il quale una riscrittura del setpoint è inutile. Il
# watchdog gira ogni pochi minuti su tutte le zone: senza questa soglia
# riscriverebbe sul bus valori già corretti, per sempre.
WRITE_DEADBAND: Final = 0.05

# Un comando sul bus OpenWebNet può perdersi senza che nessuno se ne accorga:
# la chiamata al servizio riesce comunque, perché ha solo consegnato il comando
# al gateway. L'unica verifica possibile è guardare se il termostato riporta il
# valore chiesto — e riprovare se non lo riporta.
#
# `WRITE_VERIFY_SECONDS` è quanto si concede al bus per rispondere prima di
# considerare persa la scrittura: troppo poco fa riprovare quando bastava
# aspettare, e ogni tentativo in più è traffico su un bus lento.
WRITE_ATTEMPTS: Final = 3
WRITE_VERIFY_SECONDS: Final = 1.5
WRITE_RETRY_SECONDS: Final = 2.0

# --- Storage ----------------------------------------------------------------
# Versione 2: livelli di temperatura definibili dall'utente, scenari come
# configurazione delle zone, ereditarietà su cinque livelli.
STORAGE_VERSION: Final = 2
STORAGE_KEY: Final = f"{DOMAIN}.data"

# --- Asse temporale ---------------------------------------------------------
# Un day template è una stringa di 48 caratteri: un carattere ogni 30 minuti.
SLOT_MINUTES: Final = 30
SLOTS_PER_DAY: Final = 48

DAYS_PER_WEEK: Final = 7

# Carattere che rappresenta esplicitamente l'ereditarietà: nel modello dati
# corrisponde all'assenza di un livello, nella stringa a questo segnaposto.
INHERIT_CHAR: Final = "-"

# Alfabeto ammesso per gli slot: un carattere per livello, assegnato quando il
# livello viene creato. Restare su un solo carattere per slot tiene il day
# template compatto e la pennellata una singola sostituzione di sottostringa.
LEVEL_CHARS: Final = "abcdefghijklmnopqrstuvwxyz0123456789"

# --- Asse termico -----------------------------------------------------------
# I livelli non sono più un insieme chiuso: si creano e si eliminano come i
# template. Questi quattro esistono solo al primo avvio, e da lì in poi sono
# dati come gli altri — rinominabili, ricolorabili, eliminabili.
#
# Ordine dei campi: id, nome, carattere del day template, colore, setpoint
# globale iniziale.
DEFAULT_LEVELS: Final[tuple[tuple[str, str, str, str, float], ...]] = (
    ("alta", "Alta", "a", "#e0703c", 21.0),
    ("media", "Media", "m", "#e0b13c", 19.0),
    ("bassa", "Bassa", "b", "#3f9d7c", 17.0),
    ("antigelo", "Antigelo", "g", "#4a7fbf", 7.0),
)

# Colore di un livello creato senza indicarne uno.
DEFAULT_LEVEL_COLOR: Final = "#8a8f98"

# Setpoint globale di un livello creato senza indicarne uno: il globale è la
# radice dell'ereditarietà e non può restare vuoto.
DEFAULT_LEVEL_SETPOINT: Final = 20.0

# Giornata tipo iniziale: notte bassa, mattina e sera alte, giornata media.
DEFAULT_DAY_SLOTS: Final = "b" * 12 + "a" * 5 + "m" * 17 + "a" * 11 + "b" * 3

DEFAULT_SCENARIO_ID: Final = "default"
DEFAULT_WEEK_TEMPLATE_ID: Final = "default"
DEFAULT_DAY_TEMPLATE_ID: Final = "default"

# --- Gerarchia dei setpoint -------------------------------------------------
# Dal più generale al più specifico: chi sta più in basso sovrascrive, chi non
# dice nulla eredita da chi sta sopra. È l'ordine in cui `resolve_temperature`
# interroga i livelli, e l'unico posto in cui la gerarchia è scritta.
LAYER_GLOBAL: Final = "global"
LAYER_SCENARIO: Final = "scenario"
LAYER_ZONE: Final = "zone"
LAYER_WEEK_TEMPLATE: Final = "week_template"
LAYER_DAY_TEMPLATE: Final = "day_template"

# Dal più specifico al più generale: l'ordine di interrogazione.
SETPOINT_LAYERS: Final[tuple[str, ...]] = (
    LAYER_DAY_TEMPLATE,
    LAYER_WEEK_TEMPLATE,
    LAYER_ZONE,
    LAYER_SCENARIO,
    LAYER_GLOBAL,
)

LAYER_NONE: Final = "none"

# --- Override ---------------------------------------------------------------
# Tre sorgenti fondamentalmente distinte, gestite in modo differenziato.
OVERRIDE_SOURCE_HA: Final = "ha"
OVERRIDE_SOURCE_EXTERNAL: Final = "external"
OVERRIDE_SOURCE_HARDWARE: Final = "hardware"

# Politiche di scadenza.
POLICY_NEXT_SLOT: Final = "next_slot"
# Dura finché il programma tiene lo stesso livello: una mano sul termostato
# alle 07:05 vale per tutta la fascia del mattino, non venticinque minuti.
POLICY_UNTIL_LEVEL_CHANGE: Final = "until_level_change"
POLICY_DURATION: Final = "duration"
POLICY_UNTIL_SCENARIO_CHANGE: Final = "until_scenario_change"
POLICY_STICKY: Final = "sticky"

OVERRIDE_POLICIES: Final[tuple[str, ...]] = (
    POLICY_NEXT_SLOT,
    POLICY_UNTIL_LEVEL_CHANGE,
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

# Le modifiche al programma arrivano a raffica (una griglia dipinta col mouse è
# decine di chiamate): si aspetta la fine della raffica prima di riscrivere le
# zone, perché ogni riscrittura completa occupa il bus per WRITE_STAGGER_SECONDS
# per zona.
APPLY_DEBOUNCE_SECONDS: Final = 5.0

# --- Limiti del setpoint (°C) ----------------------------------------------
MIN_TEMP: Final = 5.0
MAX_TEMP: Final = 30.0
TEMP_STEP: Final = 0.5

# --- Servizi ----------------------------------------------------------------
SERVICE_SET_OVERRIDE: Final = "set_override"
SERVICE_CLEAR_OVERRIDE: Final = "clear_override"

# Riscrittura a richiesta: il watchdog passa ogni RECONCILE_INTERVAL, e quando
# si sta guardando una zona rimasta indietro dodici minuti sono lunghi.
SERVICE_APPLY: Final = "apply"

SERVICE_SET_DAY_TEMPLATE: Final = "set_day_template"
SERVICE_PAINT_SLOTS: Final = "paint_slots"
SERVICE_DUPLICATE_DAY_TEMPLATE: Final = "duplicate_day_template"
SERVICE_DELETE_DAY_TEMPLATE: Final = "delete_day_template"
SERVICE_SET_WEEK_TEMPLATE: Final = "set_week_template"
SERVICE_DELETE_WEEK_TEMPLATE: Final = "delete_week_template"
SERVICE_SET_SCENARIO: Final = "set_scenario"
SERVICE_DELETE_SCENARIO: Final = "delete_scenario"
SERVICE_ACTIVATE_SCENARIO: Final = "activate_scenario"
SERVICE_SET_ZONE_WEEK_TEMPLATE: Final = "set_zone_week_template"
SERVICE_SET_LEVEL: Final = "set_level"
SERVICE_DELETE_LEVEL: Final = "delete_level"
SERVICE_SET_SETPOINT: Final = "set_setpoint"

# --- Pannello frontend ------------------------------------------------------
# Il bundle React vive dentro il componente e viene servito da un percorso
# statico dedicato; il pannello lo carica come modulo ESM.
PANEL_URL: Final = "/ctha-frontend"
PANEL_MODULE: Final = f"{PANEL_URL}/ctha-panel.js"
PANEL_PATH: Final = "ctha"
PANEL_ELEMENT: Final = "ctha-panel"
PANEL_TITLE: Final = "Cronotermostato"
PANEL_ICON: Final = "mdi:calendar-clock"

WS_GET: Final = f"{DOMAIN}/get"
WS_SUBSCRIBE: Final = f"{DOMAIN}/subscribe"

ATTR_ZONE_ID: Final = "zone_id"
ATTR_POLICY: Final = "policy"
ATTR_DURATION: Final = "duration"
ATTR_TEMPLATE_ID: Final = "template_id"
ATTR_NAME: Final = "name"
ATTR_SLOTS: Final = "slots"
ATTR_LEVEL: Final = "level"
ATTR_START_SLOT: Final = "start_slot"
ATTR_END_SLOT: Final = "end_slot"
ATTR_DAYS: Final = "days"
ATTR_NEW_ID: Final = "new_id"
ATTR_SCENARIO_ID: Final = "scenario_id"
ATTR_WEEK_TEMPLATE: Final = "week_template"
ATTR_DAY_TEMPLATE: Final = "day_template"
ATTR_ZONES: Final = "zones"
ATTR_COLOR: Final = "color"
ATTR_CHAR: Final = "char"
