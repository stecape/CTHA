"""Risoluzione del setpoint: asse temporale, asse termico e loro indipendenza."""

from __future__ import annotations

from datetime import datetime

import pytest
from conftest import MORNING, NIGHT
from ctha import models, resolve
from ctha.const import (
    INHERIT_CHAR,
    LEVEL_COMFORT,
    LEVEL_ECO,
    MAX_TEMP,
    MIN_TEMP,
    SLOTS_PER_DAY,
)


@pytest.mark.parametrize(
    ("moment", "expected"),
    [
        (datetime(2026, 8, 11, 0, 0), 0),
        (datetime(2026, 8, 11, 0, 29), 0),
        (datetime(2026, 8, 11, 0, 30), 1),
        (datetime(2026, 8, 11, 6, 30), 13),
        (datetime(2026, 8, 11, 23, 59), 47),
    ],
)
def test_slot_index(moment: datetime, expected: int) -> None:
    """Ogni mezz'ora è uno slot, dalla mezzanotte alle 23:30."""
    assert resolve.slot_index(moment) == expected


def test_slot_start_tronca_al_confine() -> None:
    """L'inizio dello slot azzera anche secondi e microsecondi."""
    assert resolve.slot_start(datetime(2026, 8, 11, 7, 10, 42, 5)) == datetime(
        2026, 8, 11, 7, 0
    )


def test_next_slot_start() -> None:
    """La policy next_slot si appoggia a questo confine."""
    assert resolve.next_slot_start(datetime(2026, 8, 11, 7, 10)) == datetime(
        2026, 8, 11, 7, 30
    )


def test_next_slot_start_scavalca_la_mezzanotte() -> None:
    """L'ultimo slot del giorno deve sfociare in quello successivo."""
    assert resolve.next_slot_start(datetime(2026, 8, 11, 23, 45)) == datetime(
        2026, 8, 12, 0, 0
    )


# --- asse temporale ---------------------------------------------------------


def test_livello_dal_programma(data: models.CthaData, zone: models.Zone) -> None:
    """Notte in eco, mattina in comfort: è la giornata tipo di default."""
    assert resolve.resolve_level(data, zone, NIGHT) == LEVEL_ECO
    assert resolve.resolve_level(data, zone, MORNING) == LEVEL_COMFORT


def test_week_template_di_zona_prevale_su_quello_di_scenario(
    data: models.CthaData, zone: models.Zone
) -> None:
    """Una zona può seguire un programma tutto suo."""
    data.day_templates["sempre_eco"] = models.DayTemplate(
        id="sempre_eco", name="Sempre eco", slots="e" * SLOTS_PER_DAY
    )
    data.week_templates["solo_eco"] = models.WeekTemplate(
        id="solo_eco",
        name="Solo eco",
        days=dict.fromkeys(range(7), "sempre_eco"),
    )
    zone.week_template = "solo_eco"

    assert resolve.resolve_level(data, zone, MORNING) == LEVEL_ECO


def test_catena_di_riferimenti_rotta_non_da_livello(
    data: models.CthaData, zone: models.Zone
) -> None:
    """Se il week template citato non esiste non c'è un livello da applicare."""
    zone.week_template = "inesistente"
    assert resolve.resolve_level(data, zone, MORNING) is None


def test_giorno_non_assegnato_non_da_livello(
    data: models.CthaData, zone: models.Zone
) -> None:
    """Un giorno senza day template è un buco esplicito nel programma."""
    data.week_templates["default"].days.pop(MORNING.weekday())
    assert resolve.resolve_level(data, zone, MORNING) is None


# --- asse termico -----------------------------------------------------------


def test_setpoint_ereditato_dal_globale(data: models.CthaData) -> None:
    """Senza setpoint di zona si usa il globale, e la fonte lo dichiara."""
    result = resolve.resolve_setpoint(data, "z1", MORNING)
    assert result.temperature == 21.0
    assert result.source == resolve.Resolution.SOURCE_GLOBAL


def test_setpoint_di_zona_prevale(data: models.CthaData, zone: models.Zone) -> None:
    """Il valore proprio della zona vince, e la fonte cambia di conseguenza."""
    zone.setpoints[LEVEL_COMFORT] = 22.5
    result = resolve.resolve_setpoint(data, "z1", MORNING)
    assert result.temperature == 22.5
    assert result.source == resolve.Resolution.SOURCE_ZONE


def test_none_significa_eredita(data: models.CthaData, zone: models.Zone) -> None:
    """`None` è ereditarietà esplicita, non "zero gradi"."""
    zone.setpoints[LEVEL_COMFORT] = None
    result = resolve.resolve_setpoint(data, "z1", MORNING)
    assert result.temperature == 21.0
    assert result.source == resolve.Resolution.SOURCE_GLOBAL


def test_offset_di_scenario_sposta_la_temperatura(data: models.CthaData) -> None:
    """Lo scenario agisce sull'asse termico, non su quello temporale."""
    data.scenarios["default"].offset = -2.0
    result = resolve.resolve_setpoint(data, "z1", MORNING)
    assert result.level == LEVEL_COMFORT
    assert result.temperature == 19.0
    assert result.offset == -2.0


def test_offset_di_zona_prevale_su_quello_di_scenario(data: models.CthaData) -> None:
    """L'eccezione per una zona non si somma all'offset generale: lo sostituisce."""
    data.scenarios["default"].offset = -2.0
    data.scenarios["default"].zone_offsets["z1"] = 1.0
    assert resolve.resolve_setpoint(data, "z1", MORNING).temperature == 22.0


def test_slot_che_eredita_non_produce_temperatura(
    data: models.CthaData, zone: models.Zone
) -> None:
    """Senza livello non c'è nulla da scrivere: la zona resta al suo stato."""
    data.day_templates["default"].slots = INHERIT_CHAR * SLOTS_PER_DAY
    result = resolve.resolve_setpoint(data, "z1", MORNING)
    assert result.level is None
    assert result.temperature is None
    assert result.source == resolve.Resolution.SOURCE_NONE


def test_zona_sconosciuta(data: models.CthaData) -> None:
    """Chiedere una zona che non esiste non deve sollevare eccezioni."""
    assert resolve.resolve_setpoint(data, "ignota", MORNING).temperature is None


@pytest.mark.parametrize(
    ("offset", "expected"), [(-50.0, MIN_TEMP), (50.0, MAX_TEMP), (0.0, 21.0)]
)
def test_clamp_ai_limiti_del_termostato(
    data: models.CthaData, offset: float, expected: float
) -> None:
    """Un offset assurdo non deve produrre setpoint fuori scala sul bus."""
    data.scenarios["default"].offset = offset
    assert resolve.resolve_setpoint(data, "z1", MORNING).temperature == expected


def test_day_levels_copre_tutta_la_giornata(
    data: models.CthaData, zone: models.Zone
) -> None:
    """La griglia di programmazione legge 48 livelli, uno per slot."""
    levels = resolve.day_levels(data, zone, MORNING)
    assert len(levels) == SLOTS_PER_DAY
    assert levels[0] == LEVEL_ECO
    assert levels[13] == LEVEL_COMFORT
