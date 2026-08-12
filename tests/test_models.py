"""Modello dati: validazione dei template e round-trip verso lo Store."""

from __future__ import annotations

from datetime import datetime

import pytest
from ctha import models
from ctha.const import (
    DEFAULT_DAY_SLOTS,
    DEFAULT_DAY_TEMPLATE_ID,
    DEFAULT_WEEK_TEMPLATE_ID,
    INHERIT_CHAR,
    LEVEL_COMFORT,
    LEVEL_ECO,
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
        models.DayTemplate(id="x", name="corto", slots="cc")


def test_day_template_con_carattere_ignoto_rifiutato() -> None:
    """Solo i caratteri dei livelli noti e il segnaposto di ereditarietà."""
    with pytest.raises(models.InvalidTemplateError):
        models.DayTemplate(id="x", name="ignoto", slots="z" * SLOTS_PER_DAY)


def test_carattere_di_ereditarieta_vale_none() -> None:
    """Il segnaposto non è un livello: significa "eredita dal globale"."""
    template = models.DayTemplate(
        id="i", name="eredita", slots=INHERIT_CHAR * SLOTS_PER_DAY
    )
    assert template.level_at(0) is None


def test_level_at_legge_lo_slot_giusto() -> None:
    """Lo slot 13 è la mattina: comfort nella giornata tipo."""
    template = models.DayTemplate(id="d", name="tipo")
    assert template.level_at(0) == LEVEL_ECO
    assert template.level_at(13) == LEVEL_COMFORT


def test_zona_senza_setpoint_eredita() -> None:
    """Un livello assente dalla zona è ereditarietà, non zero gradi."""
    zone = models.Zone(id="z1", name="Soggiorno")
    assert zone.setpoint_for(LEVEL_COMFORT) is None


def test_offset_di_zona_prevale_su_quello_di_scenario() -> None:
    """`zone_offsets` è una specializzazione dell'offset di scenario."""
    scenario = models.Scenario(id="s", name="Vacanza", offset=-3.0)
    scenario.zone_offsets["z1"] = 1.0
    assert scenario.offset_for("z1") == 1.0
    assert scenario.offset_for("z2") == -3.0


def test_round_trip_preserva_il_modello(data: models.CthaData) -> None:
    """Serializzare e rileggere non deve perdere né alterare nulla."""
    data.zones["z1"].setpoints[LEVEL_COMFORT] = 22.5
    data.scenarios["default"].zone_offsets["z1"] = -1.5

    restored = models.CthaData.from_dict(data.to_dict())

    assert restored.zones["z1"].name == "Soggiorno"
    assert restored.zones["z1"].setpoints[LEVEL_COMFORT] == 22.5
    assert restored.scenarios["default"].zone_offsets["z1"] == -1.5
    assert restored.week_templates[DEFAULT_WEEK_TEMPLATE_ID].days[0] == (
        DEFAULT_DAY_TEMPLATE_ID
    )


def test_round_trip_riporta_le_chiavi_dei_giorni_a_interi(
    data: models.CthaData,
) -> None:
    """JSON accetta solo chiavi stringa: la rilettura deve reintegerizzarle."""
    restored = models.CthaData.from_dict(data.to_dict())
    week = restored.week_templates[DEFAULT_WEEK_TEMPLATE_ID]
    assert sorted(week.days) == list(range(7))


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
    """Al primo avvio deve esistere una catena scenario → settimana → giorno."""
    model = models.CthaData.default()
    scenario = model.active()

    assert scenario is not None
    week = model.week_templates[scenario.week_template]
    assert set(week.days) == set(range(7))
    assert all(day in model.day_templates for day in week.days.values())
