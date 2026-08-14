"""Modello dati: validazione dei template, livelli e round-trip verso lo Store."""

from __future__ import annotations

from datetime import datetime

import pytest
from conftest import ANTIFREEZE, HIGH, LOW
from ctha import models
from ctha.const import (
    DEFAULT_DAY_SLOTS,
    DEFAULT_DAY_TEMPLATE_ID,
    DEFAULT_LEVELS,
    DEFAULT_WEEK_TEMPLATE_ID,
    INHERIT_CHAR,
    OVERRIDE_SOURCE_HARDWARE,
    POLICY_STICKY,
    SLOTS_PER_DAY,
)


def test_day_slots_di_default_coprono_la_giornata() -> None:
    """La costante di default deve essere già un template valido."""
    assert len(DEFAULT_DAY_SLOTS) == SLOTS_PER_DAY


def test_day_template_corto_rifiutato() -> None:
    """Un template di lunghezza sbagliata non deve arrivare allo Store."""
    with pytest.raises(models.InvalidTemplateError):
        models.DayTemplate(id="x", name="corto", slots="aa")


def test_day_template_con_carattere_fuori_alfabeto_rifiutato() -> None:
    """La forma si valida sempre: solo caratteri di livello e il segnaposto."""
    with pytest.raises(models.InvalidTemplateError):
        models.DayTemplate(id="x", name="ignoto", slots="!" * SLOTS_PER_DAY)


def test_carattere_ignoto_ma_ben_formato_e_accettato() -> None:
    """Un livello eliminato lascia slot orfani: rileggerli non deve fallire.

    Rifiutarli qui vorrebbe dire non riuscire più a caricare lo Store; la
    validazione dei riferimenti è di `program.py`, che ha il modello intero.
    """
    template = models.DayTemplate(id="x", name="orfano", slots="z" * SLOTS_PER_DAY)
    assert template.char_at(0) == "z"


def test_carattere_di_ereditarieta_vale_none() -> None:
    """Il segnaposto non è un livello: significa "eredita da chi sta sopra"."""
    template = models.DayTemplate(
        id="i", name="eredita", slots=INHERIT_CHAR * SLOTS_PER_DAY
    )
    assert template.char_at(0) is None


def test_level_at_traduce_il_carattere_in_livello(data: models.CthaData) -> None:
    """Lo slot 13 è la mattina: «alta» nella giornata tipo di default."""
    template = data.day_templates[DEFAULT_DAY_TEMPLATE_ID]
    assert data.level_at(template, 0) == LOW
    assert data.level_at(template, 13) == HIGH


def test_level_for_char_di_un_livello_eliminato(data: models.CthaData) -> None:
    """Un carattere orfano non è un livello, e non deve sollevare eccezioni."""
    assert data.level_for_char("z") is None
    assert data.level_for_char(None) is None


def test_livelli_di_default_hanno_caratteri_distinti() -> None:
    """Due livelli con lo stesso carattere renderebbero i template ambigui."""
    chars = [char for _, _, char, _, _ in DEFAULT_LEVELS]
    assert len(set(chars)) == len(chars)
    assert INHERIT_CHAR not in chars


def test_scenario_assegna_una_settimana_per_zona() -> None:
    """Lo scenario *è* la mappa zona → settimana tipo."""
    scenario = models.Scenario(id="s", name="Vacanza", zones={"z1": "inverno"})
    assert scenario.week_template_for("z1") == "inverno"
    assert scenario.week_template_for("z2") is None


def test_round_trip_preserva_il_modello(data: models.CthaData) -> None:
    """Serializzare e rileggere non deve perdere né alterare nulla."""
    data.zones["z1"].setpoints[HIGH] = 22.5
    data.scenarios["default"].setpoints[LOW] = 15.0
    data.week_templates[DEFAULT_WEEK_TEMPLATE_ID].setpoints[ANTIFREEZE] = 8.0
    data.day_templates[DEFAULT_DAY_TEMPLATE_ID].setpoints[HIGH] = 23.0

    restored = models.CthaData.from_dict(data.to_dict())

    assert restored.zones["z1"].name == "Soggiorno"
    assert restored.zones["z1"].setpoints[HIGH] == 22.5
    assert restored.scenarios["default"].setpoints[LOW] == 15.0
    assert restored.week_templates[DEFAULT_WEEK_TEMPLATE_ID].setpoints[ANTIFREEZE] == 8.0
    assert restored.day_templates[DEFAULT_DAY_TEMPLATE_ID].setpoints[HIGH] == 23.0
    assert restored.scenarios["default"].zones["z1"] == DEFAULT_WEEK_TEMPLATE_ID


def test_round_trip_preserva_i_livelli(data: models.CthaData) -> None:
    """I livelli sono dati: colore e carattere devono sopravvivere al giro."""
    restored = models.CthaData.from_dict(data.to_dict())
    assert restored.levels[HIGH].char == data.levels[HIGH].char
    assert restored.levels[HIGH].color == data.levels[HIGH].color
    assert list(restored.levels) == list(data.levels)


def test_round_trip_riporta_le_chiavi_dei_giorni_a_interi(
    data: models.CthaData,
) -> None:
    """JSON accetta solo chiavi stringa: la rilettura deve reintegerizzarle."""
    restored = models.CthaData.from_dict(data.to_dict())
    week = restored.week_templates[DEFAULT_WEEK_TEMPLATE_ID]
    assert sorted(week.days) == list(range(7))


def test_setpoint_a_none_e_un_assenza(data: models.CthaData) -> None:
    """Nella v2 l'ereditarietà è l'assenza della chiave, non un valore nullo."""
    raw = data.to_dict()
    raw["zones"]["z1"]["setpoints"] = {HIGH: None, LOW: 16.0}

    restored = models.CthaData.from_dict(raw)

    assert HIGH not in restored.zones["z1"].setpoints
    assert restored.zones["z1"].setpoints[LOW] == 16.0


def test_round_trip_degli_override(data: models.CthaData) -> None:
    """I datetime passano per stringhe ISO e devono tornare datetime."""
    data.overrides["z1"] = models.Override(
        zone_id="z1",
        temperature=24.0,
        source=OVERRIDE_SOURCE_HARDWARE,
        policy=POLICY_STICKY,
        created_at=datetime(2026, 8, 11, 7, 10),
        expires_at=None,
        scenario_id="default",
    )

    restored = models.CthaData.from_dict(data.to_dict()).overrides["z1"]

    assert restored.created_at == datetime(2026, 8, 11, 7, 10)
    assert restored.expires_at is None
    assert restored.source == OVERRIDE_SOURCE_HARDWARE


def test_modello_di_default_e_gia_funzionante() -> None:
    """Al primo avvio devono esistere livelli, settimana e giornata tipo."""
    model = models.CthaData.default()
    scenario = model.active()

    assert scenario is not None
    assert set(model.levels) == {level_id for level_id, *_ in DEFAULT_LEVELS}
    assert set(model.global_setpoints) == set(model.levels)

    week = model.week_templates[DEFAULT_WEEK_TEMPLATE_ID]
    assert set(week.days) == set(range(7))
    assert all(day in model.day_templates for day in week.days.values())


def test_modello_di_default_non_ha_zone() -> None:
    """Le zone nascono con le config entry, non col modello."""
    model = models.CthaData.default()
    assert model.zones == {}
    assert model.scenarios["default"].zones == {}
