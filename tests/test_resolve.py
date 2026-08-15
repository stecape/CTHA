"""Risoluzione del setpoint: asse temporale, gerarchia termica, indipendenza."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from conftest import HIGH, LOW, MORNING, NIGHT
from ctha import models, program, resolve
from ctha.const import (
    INHERIT_CHAR,
    LAYER_DAY_TEMPLATE,
    LAYER_GLOBAL,
    LAYER_NONE,
    LAYER_SCENARIO,
    LAYER_WEEK_TEMPLATE,
    LAYER_ZONE,
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


def test_slot_index_legge_l_orologio_a_muro() -> None:
    """Lo slot dipende dall'ora scritta nell'istante, non dall'istante assoluto.

    Qui non si può fare altrimenti: `resolve` non importa Home Assistant e non
    conosce il fuso configurato. È però la ragione per cui il coordinator deve
    convertire in ora locale *prima* di chiamare — e il motivo per cui questo
    test esiste. Il watchdog girava su `async_track_time_interval`, che consegna
    UTC, mentre il tick di slot riceveva l'ora locale: i due scrivevano il
    programma di fasce diverse, e la zona rimbalzava fra i due valori.
    """
    locale = datetime(2026, 8, 15, 23, 2, tzinfo=timezone(timedelta(hours=2)))

    assert resolve.slot_index(locale) == 46
    assert resolve.slot_index(locale.astimezone(timezone.utc)) == 42


def test_lo_scarto_di_fuso_dopo_mezzanotte_sposta_il_giorno() -> None:
    """Dopo mezzanotte l'istante non convertito cambia anche la giornata tipo.

    Peggio dello slot sbagliato: alle 01:00 di domenica, in UTC è ancora sabato,
    quindi la settimana tipo pescherebbe il giorno prima.
    """
    locale = datetime(2026, 8, 16, 1, 0, tzinfo=timezone(timedelta(hours=2)))

    assert locale.weekday() == 6  # domenica
    assert locale.astimezone(timezone.utc).weekday() == 5  # sabato


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


def test_livello_dal_programma(data: models.CthaData) -> None:
    """Notte in bassa, mattina in alta: è la giornata tipo di default."""
    assert resolve.resolve_level(data, "z1", NIGHT) == LOW
    assert resolve.resolve_level(data, "z1", MORNING) == HIGH


def test_lo_scenario_decide_la_settimana_della_zona(data: models.CthaData) -> None:
    """Cambiare scenario riprogramma la zona: è tutto ciò che uno scenario fa."""
    program.set_day_template(data, "sempre_bassa", slots="b" * SLOTS_PER_DAY)
    program.set_week_template(
        data, "risparmio", days=dict.fromkeys(range(7), "sempre_bassa")
    )
    program.set_scenario(data, "vacanza", name="Vacanza", zones={"z1": "risparmio"})
    program.set_active_scenario(data, "vacanza")

    assert resolve.resolve_level(data, "z1", MORNING) == LOW


def test_zona_non_configurata_nello_scenario_non_da_livello(
    data: models.CthaData, scenario: models.Scenario
) -> None:
    """Una zona che lo scenario non cita non è programmata, e non riceve nulla."""
    scenario.zones.pop("z1")
    assert resolve.resolve_level(data, "z1", MORNING) is None
    assert resolve.resolve_setpoint(data, "z1", MORNING).temperature is None


def test_catena_di_riferimenti_rotta_non_da_livello(
    data: models.CthaData, scenario: models.Scenario
) -> None:
    """Se la settimana citata non esiste non c'è un livello da applicare."""
    scenario.zones["z1"] = "inesistente"
    assert resolve.resolve_level(data, "z1", MORNING) is None


def test_giorno_non_assegnato_non_da_livello(data: models.CthaData) -> None:
    """Un giorno senza day template è un buco esplicito nel programma."""
    data.week_templates["default"].days.pop(MORNING.weekday())
    assert resolve.resolve_level(data, "z1", MORNING) is None


def test_la_catena_nomina_gli_anelli(data: models.CthaData) -> None:
    """Il pannello mostra "segue X, oggi Y": la catena glielo dice."""
    chain = resolve.resolve_chain(data, "z1", MORNING)

    assert chain.complete
    assert chain.scenario is not None and chain.scenario.id == "default"
    assert chain.week is not None and chain.week.id == "default"
    assert chain.day is not None and chain.day.id == "default"
    assert chain.slot == 14


# --- gerarchia termica ------------------------------------------------------


def test_setpoint_ereditato_dal_globale(data: models.CthaData) -> None:
    """Senza sovrascritture si arriva alla radice, e la fonte lo dichiara."""
    result = resolve.resolve_setpoint(data, "z1", MORNING)
    assert result.temperature == 21.0
    assert result.source == LAYER_GLOBAL


@pytest.mark.parametrize(
    ("layer", "expected_source"),
    [
        (LAYER_SCENARIO, LAYER_SCENARIO),
        (LAYER_ZONE, LAYER_ZONE),
        (LAYER_WEEK_TEMPLATE, LAYER_WEEK_TEMPLATE),
        (LAYER_DAY_TEMPLATE, LAYER_DAY_TEMPLATE),
    ],
)
def test_ogni_livello_puo_sovrascrivere_il_globale(
    data: models.CthaData, layer: str, expected_source: str
) -> None:
    """Ognuno dei quattro livelli, da solo, batte il globale."""
    _table(data, layer)[HIGH] = 25.0

    result = resolve.resolve_setpoint(data, "z1", MORNING)

    assert result.temperature == 25.0
    assert result.source == expected_source


def test_il_piu_specifico_vince_su_tutti(data: models.CthaData) -> None:
    """Global < scenario < zona < settimana < giornata: l'ordine è questo."""
    data.scenarios["default"].setpoints[HIGH] = 18.0
    assert resolve.resolve_setpoint(data, "z1", MORNING).temperature == 18.0

    data.zones["z1"].setpoints[HIGH] = 19.0
    assert resolve.resolve_setpoint(data, "z1", MORNING).temperature == 19.0

    data.week_templates["default"].setpoints[HIGH] = 20.0
    assert resolve.resolve_setpoint(data, "z1", MORNING).temperature == 20.0

    data.day_templates["default"].setpoints[HIGH] = 21.5
    assert resolve.resolve_setpoint(data, "z1", MORNING).temperature == 21.5


def test_si_eredita_livello_per_livello(data: models.CthaData) -> None:
    """Sovrascrivere «alta» non porta con sé anche gli altri livelli."""
    data.zones["z1"].setpoints[HIGH] = 24.0

    assert resolve.resolve_setpoint(data, "z1", MORNING).source == LAYER_ZONE
    assert resolve.resolve_setpoint(data, "z1", NIGHT).source == LAYER_GLOBAL


def test_slot_che_eredita_non_produce_temperatura(data: models.CthaData) -> None:
    """Senza livello non c'è nulla da scrivere: la zona resta al suo stato."""
    data.day_templates["default"].slots = INHERIT_CHAR * SLOTS_PER_DAY
    result = resolve.resolve_setpoint(data, "z1", MORNING)

    assert result.level is None
    assert result.temperature is None
    assert result.source == LAYER_NONE


def test_livello_senza_alcun_setpoint(data: models.CthaData) -> None:
    """Un livello esistente ma senza radice non produce una temperatura."""
    data.global_setpoints.pop(HIGH)
    result = resolve.resolve_setpoint(data, "z1", MORNING)

    assert result.level == HIGH
    assert result.temperature is None
    assert result.source == LAYER_NONE


def test_zona_sconosciuta(data: models.CthaData) -> None:
    """Chiedere una zona che non esiste non deve sollevare eccezioni."""
    assert resolve.resolve_setpoint(data, "ignota", MORNING).temperature is None


@pytest.mark.parametrize(
    ("value", "expected"), [(-50.0, MIN_TEMP), (50.0, MAX_TEMP), (21.0, 21.0)]
)
def test_clamp_ai_limiti_del_termostato(
    data: models.CthaData, value: float, expected: float
) -> None:
    """Un valore assurdo nel modello non deve arrivare così com'è sul bus."""
    data.zones["z1"].setpoints[HIGH] = value
    assert resolve.resolve_setpoint(data, "z1", MORNING).temperature == expected


def test_temperatura_di_un_livello_forzato(data: models.CthaData) -> None:
    """I preset forzano un livello: i gradi restano quelli della catena."""
    data.zones["z1"].setpoints[LOW] = 16.0

    result = resolve.resolve_level_temperature(data, "z1", LOW, MORNING)

    assert result.temperature == 16.0
    assert result.source == LAYER_ZONE


def test_day_levels_copre_tutta_la_giornata(data: models.CthaData) -> None:
    """La griglia di programmazione legge 48 livelli, uno per slot."""
    levels = resolve.day_levels(data, "z1", MORNING)
    assert len(levels) == SLOTS_PER_DAY
    assert levels[0] == LOW
    assert levels[13] == HIGH


def _table(data: models.CthaData, layer: str) -> dict[str, float]:
    """Tabella di setpoint del livello indicato, per i test parametrici."""
    return {
        LAYER_SCENARIO: data.scenarios["default"].setpoints,
        LAYER_ZONE: data.zones["z1"].setpoints,
        LAYER_WEEK_TEMPLATE: data.week_templates["default"].setpoints,
        LAYER_DAY_TEMPLATE: data.day_templates["default"].setpoints,
    }[layer]
