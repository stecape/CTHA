"""Migrazione dello Store dalla versione 1 alla 2.

I dati della v1 hanno tre livelli fissi e uno scenario con *una* settimana
tipo. Dopo la migrazione devono restare leggibili dal modello nuovo senza che
l'utente ritrovi un impianto riprogrammato a sua insaputa.
"""

from __future__ import annotations

import pytest
from ctha import models
from ctha.const import SLOTS_PER_DAY
from ctha.migrate import migrate_v1_to_v2


@pytest.fixture
def v1() -> dict:
    """Uno Store della versione 1 con due zone, di cui una con programma proprio."""
    return {
        "global_setpoints": {"comfort": 21.0, "eco": 18.0, "antifreeze": 7.0},
        "day_templates": {
            "default": {
                "id": "default",
                "name": "Giornata tipo",
                "slots": "e" * 12 + "c" * 36,
            }
        },
        "week_templates": {
            "default": {
                "id": "default",
                "name": "Settimana tipo",
                "days": {str(day): "default" for day in range(7)},
            },
            "solo_eco": {"id": "solo_eco", "name": "Solo eco", "days": {}},
        },
        "scenarios": {
            "default": {
                "id": "default",
                "name": "Normale",
                "week_template": "default",
                "offset": 0.0,
                "zone_offsets": {},
            },
            "vacanza": {
                "id": "vacanza",
                "name": "Vacanza",
                "week_template": "default",
                "offset": -3.0,
                "zone_offsets": {"z1": 1.0},
            },
        },
        "zones": {
            "z1": {
                "id": "z1",
                "name": "Soggiorno",
                "setpoints": {"comfort": 22.5, "eco": None},
                "week_template": None,
            },
            "z2": {
                "id": "z2",
                "name": "Studio",
                "setpoints": {},
                "week_template": "solo_eco",
            },
        },
        "overrides": {},
        "active_scenario": "default",
    }


def test_i_tre_livelli_diventano_dati(v1: dict) -> None:
    """Stessi caratteri: le giornate tipo già dipinte restano valide."""
    data = models.CthaData.from_dict(migrate_v1_to_v2(v1))

    assert set(data.levels) == {"comfort", "eco", "antifreeze"}
    assert data.levels["comfort"].char == "c"
    assert data.global_setpoints["eco"] == 18.0
    assert data.level_at(data.day_templates["default"], 0) == "eco"


def test_la_settimana_dello_scenario_diventa_quella_di_ogni_zona(v1: dict) -> None:
    """Prima lo scenario aveva una settimana sola: ora ce l'ha per ciascuna zona."""
    data = models.CthaData.from_dict(migrate_v1_to_v2(v1))

    assert data.scenarios["default"].zones["z1"] == "default"


def test_il_programma_proprio_della_zona_ha_la_precedenza(v1: dict) -> None:
    """Era il significato di `Zone.week_template`, e va conservato."""
    data = models.CthaData.from_dict(migrate_v1_to_v2(v1))

    assert data.scenarios["default"].zones["z2"] == "solo_eco"
    assert data.scenarios["vacanza"].zones["z2"] == "solo_eco"


def test_l_offset_di_scenario_diventa_temperature_esplicite(v1: dict) -> None:
    """Gli offset non esistono più: quello generale si riscrive come sovrascritture."""
    data = models.CthaData.from_dict(migrate_v1_to_v2(v1))

    assert data.scenarios["vacanza"].setpoints == {
        "comfort": 18.0,
        "eco": 15.0,
        "antifreeze": 5.0,
    }
    assert data.scenarios["default"].setpoints == {}


def test_i_setpoint_nulli_diventano_assenze(v1: dict) -> None:
    """Nella v2 l'ereditarietà è l'assenza della chiave."""
    data = models.CthaData.from_dict(migrate_v1_to_v2(v1))

    assert data.zones["z1"].setpoints == {"comfort": 22.5}


def test_i_template_conservano_gli_slot(v1: dict) -> None:
    """La migrazione non deve toccare il programma settimanale."""
    data = models.CthaData.from_dict(migrate_v1_to_v2(v1))
    template = data.day_templates["default"]

    assert len(template.slots) == SLOTS_PER_DAY
    assert template.slots == v1["day_templates"]["default"]["slots"]
    assert template.setpoints == {}


def test_store_vuoto_non_esplode() -> None:
    """Un file troncato o vuoto deve dare un modello leggibile, non un errore."""
    data = models.CthaData.from_dict(migrate_v1_to_v2({}))

    assert data.scenarios == {}
    assert data.active_scenario == "default"
