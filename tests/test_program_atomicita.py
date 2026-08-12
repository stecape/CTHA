"""Una modifica rifiutata non deve lasciare il programma a metà.

I servizi persistono il modello dopo ogni chiamata riuscita: se una chiamata
fallita avesse già mutato qualcosa, quel residuo finirebbe nello Store al
salvataggio successivo, e l'utente si ritroverebbe una modifica che non ha mai
chiesto.
"""

from __future__ import annotations

import pytest
from ctha import models, program
from ctha.const import SLOTS_PER_DAY


def test_settimana_non_cambia_se_un_giorno_e_sbagliato(data: models.CthaData) -> None:
    """Il giorno valido non viene assegnato se un altro della stessa chiamata non lo è."""
    program.set_day_template(data, "weekend", slots="c" * SLOTS_PER_DAY)

    with pytest.raises(program.UnknownReferenceError):
        program.set_week_template(
            data, "default", days={5: "weekend", 6: "fantasma"}
        )

    assert data.week_templates["default"].days[5] == "default"


def test_settimana_non_viene_creata_se_la_chiamata_fallisce(
    data: models.CthaData,
) -> None:
    """Nemmeno il contenitore deve restare in giro."""
    with pytest.raises(program.UnknownReferenceError):
        program.set_week_template(data, "nuova", days={0: "fantasma"})

    assert "nuova" not in data.week_templates


def test_scenario_non_cambia_se_una_zona_e_sbagliata(
    data: models.CthaData, zone: models.Zone
) -> None:
    """L'offset valido non passa se un altro della stessa chiamata cita una zona ignota."""
    with pytest.raises(program.UnknownReferenceError):
        program.set_scenario(
            data, "default", offset=-2.0, zone_offsets={zone.id: 1.0, "fantasma": 2.0}
        )

    assert data.scenarios["default"].offset == 0.0
    assert data.scenarios["default"].zone_offsets == {}


def test_duplicate_non_lascia_copie_orfane(data: models.CthaData) -> None:
    """Se il riaggancio non è possibile, la copia non deve nascere affatto."""
    with pytest.raises(program.ProgramError):
        program.duplicate_day_template(
            data, "default", new_id="copia", week_template="default", days=[9]
        )

    assert "copia" not in data.day_templates
