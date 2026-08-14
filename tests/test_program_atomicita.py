"""Una modifica rifiutata non deve lasciare il programma a metà.

I servizi persistono il modello dopo ogni chiamata riuscita: se una chiamata
fallita avesse già mutato qualcosa, quel residuo finirebbe nello Store al
salvataggio successivo, e l'utente si ritroverebbe una modifica che non ha mai
chiesto.
"""

from __future__ import annotations

import pytest
from conftest import HIGH
from ctha import models, program
from ctha.const import SLOTS_PER_DAY


def test_settimana_non_cambia_se_un_giorno_e_sbagliato(data: models.CthaData) -> None:
    """Il giorno valido non viene assegnato se un altro della stessa chiamata non lo è."""
    program.set_day_template(data, "weekend", slots="a" * SLOTS_PER_DAY)

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


def test_scenario_non_cambia_se_una_zona_e_sbagliata(data: models.CthaData) -> None:
    """L'assegnazione valida non passa se un'altra della stessa chiamata è ignota."""
    program.set_week_template(data, "inverno", name="Inverno")

    with pytest.raises(program.UnknownReferenceError):
        program.set_scenario(
            data, "default", zones={"z1": "inverno", "fantasma": "inverno"}
        )

    assert data.scenarios["default"].zones["z1"] == "default"


def test_scenario_non_viene_creato_se_la_chiamata_fallisce(
    data: models.CthaData,
) -> None:
    """Uno scenario a metà sarebbe attivabile, e sbagliato."""
    with pytest.raises(program.UnknownReferenceError):
        program.set_scenario(data, "vacanza", zones={"z1": "fantasma"})

    assert "vacanza" not in data.scenarios


def test_livello_non_nasce_se_il_carattere_e_occupato(data: models.CthaData) -> None:
    """Un livello senza carattere non sarebbe dipingibile: meglio non crearlo."""
    with pytest.raises(program.ProgramError):
        program.set_level(data, "tiepido", char="a")

    assert "tiepido" not in data.levels
    assert "tiepido" not in data.global_setpoints


def test_duplicate_non_lascia_copie_orfane(data: models.CthaData) -> None:
    """Se il riaggancio non è possibile, la copia non deve nascere affatto."""
    with pytest.raises(program.ProgramError):
        program.duplicate_day_template(
            data, "default", new_id="copia", week_template="default", days=[9]
        )

    assert "copia" not in data.day_templates


def test_setpoint_ambiguo_non_scrive_da_nessuna_parte(data: models.CthaData) -> None:
    """Con due ambiti non si sceglie: si rifiuta, senza toccare né l'uno né l'altro."""
    with pytest.raises(program.ProgramError):
        program.set_setpoint(data, HIGH, 22.0, zone_id="z1", scenario_id="default")

    assert data.zones["z1"].setpoints == {}
    assert data.scenarios["default"].setpoints == {}
