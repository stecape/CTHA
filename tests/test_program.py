"""Editing del programma: integrità dei riferimenti e semantica delle modifiche."""

from __future__ import annotations

import pytest
from conftest import MORNING
from ctha import models, program, resolve
from ctha.const import (
    DEFAULT_DAY_SLOTS,
    INHERIT_CHAR,
    LEVEL_COMFORT,
    LEVEL_ECO,
    SLOTS_PER_DAY,
)


@pytest.fixture
def weekend(data: models.CthaData) -> models.DayTemplate:
    """Una seconda giornata tipo, per i casi con più template in gioco."""
    return program.set_day_template(
        data, "weekend", name="Weekend", slots="c" * SLOTS_PER_DAY
    )


# --- Giornate tipo ----------------------------------------------------------


def test_set_day_template_crea(data: models.CthaData) -> None:
    """Un id nuovo crea il template, partendo dalla giornata di default."""
    template = program.set_day_template(data, "feriale", name="Feriale")

    assert data.day_templates["feriale"] is template
    assert template.name == "Feriale"
    assert template.slots == DEFAULT_DAY_SLOTS


def test_set_day_template_aggiorna_senza_azzerare(data: models.CthaData) -> None:
    """I campi omessi restano: la stessa chiamata ripetuta deve convergere."""
    program.set_day_template(data, "feriale", name="Feriale", slots="c" * SLOTS_PER_DAY)
    program.set_day_template(data, "feriale", name="Giorno feriale")

    template = data.day_templates["feriale"]
    assert template.name == "Giorno feriale"
    assert template.slots == "c" * SLOTS_PER_DAY


def test_set_day_template_rifiuta_slot_malformati(data: models.CthaData) -> None:
    """L'errore del modello arriva come ProgramError, mostrabile all'utente."""
    with pytest.raises(program.ProgramError):
        program.set_day_template(data, "rotto", slots="troppo corto")


def test_paint_dipinge_un_intervallo_inclusivo(data: models.CthaData) -> None:
    """Un trascinamento sulla griglia è un intervallo, estremi compresi."""
    program.paint_day_template(data, "default", LEVEL_COMFORT, 0, 3)

    slots = data.day_templates["default"].slots
    assert slots[:4] == "cccc"
    assert slots[4] == "e"


def test_paint_di_un_solo_slot(data: models.CthaData) -> None:
    """Senza slot finale si dipinge solo quello iniziale."""
    program.paint_day_template(data, "default", LEVEL_COMFORT, 5)

    slots = data.day_templates["default"].slots
    assert slots[5] == "c"
    assert slots[4] == "e" and slots[6] == "e"


def test_paint_senza_livello_dipinge_l_ereditarieta(data: models.CthaData) -> None:
    """`None` non è "niente": è il segnaposto di ereditarietà dal globale."""
    program.paint_day_template(data, "default", None, 0, 1)
    assert data.day_templates["default"].slots[:2] == INHERIT_CHAR * 2


def test_paint_non_cambia_la_lunghezza(data: models.CthaData) -> None:
    """La stringa deve restare di 48 caratteri anche dopo molte pennellate."""
    program.paint_day_template(data, "default", LEVEL_COMFORT, 0, 47)
    program.paint_day_template(data, "default", LEVEL_ECO, 10, 20)
    assert len(data.day_templates["default"].slots) == SLOTS_PER_DAY


@pytest.mark.parametrize(("start", "end"), [(-1, 5), (0, 48), (10, 5)])
def test_paint_rifiuta_intervalli_impossibili(
    data: models.CthaData, start: int, end: int
) -> None:
    """Fuori scala o rovesciato: meglio un errore che una stringa corrotta."""
    with pytest.raises(program.ProgramError):
        program.paint_day_template(data, "default", LEVEL_COMFORT, start, end)


def test_paint_su_template_inesistente(data: models.CthaData) -> None:
    """Un riferimento rotto va segnalato, non creato al volo."""
    with pytest.raises(program.UnknownReferenceError):
        program.paint_day_template(data, "fantasma", LEVEL_COMFORT, 0)


# --- Duplica e scollega -----------------------------------------------------


def test_duplicate_genera_un_id_libero(data: models.CthaData) -> None:
    """Senza id esplicito la copia non deve mai sovrascrivere un template."""
    first = program.duplicate_day_template(data, "default")
    second = program.duplicate_day_template(data, "default")

    assert first.id == "default_copy"
    assert second.id == "default_copy_2"
    assert first.slots == data.day_templates["default"].slots


def test_duplicate_non_sovrascrive_un_id_esistente(data: models.CthaData) -> None:
    """Un id esplicito già in uso è un errore, non una sostituzione silenziosa."""
    with pytest.raises(program.ProgramError):
        program.duplicate_day_template(data, "default", new_id="default")


def test_duplicate_e_scollega_solo_i_giorni_indicati(data: models.CthaData) -> None:
    """La scappatoia: differenziare un giorno senza toccare gli altri."""
    copy = program.duplicate_day_template(
        data, "default", week_template="default", days=[2]
    )

    week = data.week_templates["default"]
    assert week.days[2] == copy.id
    assert week.days[1] == "default"


def test_duplicate_senza_giorni_sposta_tutti_quelli_che_usavano_l_originale(
    data: models.CthaData,
) -> None:
    """Con una settimana ma senza giorni, la copia rileva l'originale ovunque."""
    copy = program.duplicate_day_template(data, "default", week_template="default")

    assert set(data.week_templates["default"].days.values()) == {copy.id}


def test_duplicate_non_altera_l_originale(data: models.CthaData) -> None:
    """Dipingere sulla copia non deve tornare indietro sull'originale."""
    copy = program.duplicate_day_template(data, "default")
    program.paint_day_template(data, copy.id, LEVEL_COMFORT, 0, 47)

    assert data.day_templates["default"].slots == DEFAULT_DAY_SLOTS


# --- Cancellazioni ----------------------------------------------------------


def test_delete_day_template_in_uso_rifiutato(data: models.CthaData) -> None:
    """L'errore deve dire chi lo sta usando, non solo che non si può."""
    with pytest.raises(
        program.ReferenceInUseError, match="settimana tipo 'Settimana tipo'"
    ):
        program.delete_day_template(data, "default")


def test_delete_day_template_libero(data: models.CthaData, weekend: models.DayTemplate) -> None:
    """Un template che nessuno cita si elimina senza storie."""
    program.delete_day_template(data, weekend.id)
    assert weekend.id not in data.day_templates


def test_usages_elenca_settimane_e_giorni(
    data: models.CthaData, weekend: models.DayTemplate
) -> None:
    """È la stessa informazione della vista "chi usa questo template"."""
    program.set_week_template(data, "default", days={5: "weekend", 6: "weekend"})

    usages = program.day_template_usages(data, "weekend")

    assert len(usages) == 1
    assert usages[0].kind == program.KIND_WEEK_TEMPLATE
    assert usages[0].detail == "sabato, domenica"


def test_delete_week_template_usato_da_uno_scenario(data: models.CthaData) -> None:
    """Lo scenario di default segue la settimana di default."""
    with pytest.raises(program.ReferenceInUseError, match="scenario"):
        program.delete_week_template(data, "default")


def test_delete_week_template_usato_da_una_zona(
    data: models.CthaData, zone: models.Zone
) -> None:
    """Anche una singola zona basta a bloccare la cancellazione."""
    program.set_week_template(data, "solo_zona", name="Solo zona")
    program.set_zone_week_template(data, zone.id, "solo_zona")

    with pytest.raises(program.ReferenceInUseError, match="zona 'Soggiorno'"):
        program.delete_week_template(data, "solo_zona")


# --- Settimane tipo ---------------------------------------------------------


def test_set_week_template_parte_dalla_giornata_di_default(
    data: models.CthaData,
) -> None:
    """Una settimana nuova nasce già coperta: sette giorni scoperti sarebbero un buco."""
    week = program.set_week_template(data, "inverno", name="Inverno")
    assert set(week.days) == set(range(7))
    assert set(week.days.values()) == {"default"}


def test_set_week_template_fonde_i_giorni(
    data: models.CthaData, weekend: models.DayTemplate
) -> None:
    """Assegnare la domenica non deve azzerare gli altri sei giorni."""
    program.set_week_template(data, "default", days={6: "weekend"})

    week = data.week_templates["default"]
    assert week.days[6] == "weekend"
    assert week.days[0] == "default"


def test_giorno_a_none_resta_scoperto(data: models.CthaData) -> None:
    """Togliere l'assegnazione è un'operazione legittima, non un errore."""
    program.set_week_template(data, "default", days={6: None})
    assert 6 not in data.week_templates["default"].days


def test_set_week_template_rifiuta_giornate_inesistenti(data: models.CthaData) -> None:
    """Un typo nell'id lascerebbe il giorno senza livello: meglio fermarsi."""
    with pytest.raises(program.UnknownReferenceError):
        program.set_week_template(data, "default", days={0: "fantasma"})


def test_set_week_template_rifiuta_giorni_fuori_scala(data: models.CthaData) -> None:
    """I giorni vanno da 0 (lunedì) a 6 (domenica)."""
    with pytest.raises(program.ProgramError):
        program.set_week_template(data, "default", days={7: "default"})


# --- Scenari ----------------------------------------------------------------


def test_set_scenario_eredita_la_settimana_attiva(data: models.CthaData) -> None:
    """Uno scenario nuovo deve essere subito risolvibile."""
    scenario = program.set_scenario(data, "vacanza", name="Vacanza", offset=-3.0)

    assert scenario.week_template == "default"
    assert scenario.offset == -3.0


def test_set_scenario_rifiuta_settimane_inesistenti(data: models.CthaData) -> None:
    """Meglio nessuno scenario che uno che non risolve nulla."""
    with pytest.raises(program.UnknownReferenceError):
        program.set_scenario(data, "vacanza", week_template="fantasma")


def test_zone_offsets_si_fondono_e_si_rimuovono(
    data: models.CthaData, zone: models.Zone
) -> None:
    """`None` rimuove l'eccezione e riporta la zona all'offset generale."""
    program.set_scenario(data, "default", zone_offsets={zone.id: 1.5})
    assert data.scenarios["default"].zone_offsets[zone.id] == 1.5

    program.set_scenario(data, "default", zone_offsets={zone.id: None})
    assert zone.id not in data.scenarios["default"].zone_offsets


def test_offset_di_zona_su_zona_inesistente(data: models.CthaData) -> None:
    """Un offset per una zona che non esiste è quasi certamente un typo."""
    with pytest.raises(program.UnknownReferenceError):
        program.set_scenario(data, "default", zone_offsets={"fantasma": 1.0})


def test_delete_scenario_attivo_rifiutato(data: models.CthaData) -> None:
    """Restare senza scenario attivo spegnerebbe la risoluzione."""
    program.set_scenario(data, "vacanza", name="Vacanza")
    with pytest.raises(program.ReferenceInUseError, match="attivo"):
        program.delete_scenario(data, "default")


def test_delete_ultimo_scenario_rifiutato(data: models.CthaData) -> None:
    """Anche cambiando attivo, uno scenario deve restare."""
    program.set_scenario(data, "vacanza", name="Vacanza")
    program.set_active_scenario(data, "vacanza")
    program.delete_scenario(data, "default")

    with pytest.raises(program.ReferenceInUseError):
        program.delete_scenario(data, "vacanza")


def test_activate_scenario_cambia_la_risoluzione(data: models.CthaData) -> None:
    """Il cambio di scenario si vede subito sull'asse termico."""
    program.set_scenario(data, "vacanza", name="Vacanza", offset=-4.0)
    program.set_active_scenario(data, "vacanza")

    assert resolve.resolve_setpoint(data, "z1", MORNING).temperature == 17.0


def test_activate_scenario_inesistente(data: models.CthaData) -> None:
    """Il servizio deve poter rispondere "questo scenario non esiste"."""
    with pytest.raises(program.UnknownReferenceError):
        program.set_active_scenario(data, "fantasma")


# --- Setpoint e zone --------------------------------------------------------


def test_set_setpoint_globale(data: models.CthaData) -> None:
    """Il globale è la radice: cambia le zone che ereditano."""
    program.set_setpoint(data, LEVEL_COMFORT, 22.0)
    assert resolve.resolve_setpoint(data, "z1", MORNING).temperature == 22.0


def test_set_setpoint_globale_non_puo_ereditare(data: models.CthaData) -> None:
    """Sotto il globale non c'è nessuno da cui ereditare."""
    with pytest.raises(program.ProgramError):
        program.set_setpoint(data, LEVEL_COMFORT, None)


def test_set_setpoint_di_zona_e_ritorno_all_ereditarieta(
    data: models.CthaData, zone: models.Zone
) -> None:
    """Su una zona `None` è il modo esplicito di tornare a ereditare."""
    program.set_setpoint(data, LEVEL_COMFORT, 23.0, zone_id=zone.id)
    result = resolve.resolve_setpoint(data, "z1", MORNING)
    assert (result.temperature, result.source) == (23.0, resolve.Resolution.SOURCE_ZONE)

    program.set_setpoint(data, LEVEL_COMFORT, None, zone_id=zone.id)
    result = resolve.resolve_setpoint(data, "z1", MORNING)
    assert (result.temperature, result.source) == (
        21.0,
        resolve.Resolution.SOURCE_GLOBAL,
    )


def test_set_setpoint_fuori_scala(data: models.CthaData) -> None:
    """Un valore che il termostato non può tenere non deve entrare nel modello."""
    with pytest.raises(program.ProgramError):
        program.set_setpoint(data, LEVEL_COMFORT, 45.0)


def test_set_setpoint_livello_sconosciuto(data: models.CthaData) -> None:
    """I livelli sono un insieme chiuso: comfort, eco, antigelo."""
    with pytest.raises(program.ProgramError):
        program.set_setpoint(data, "tiepido", 20.0)


def test_zona_torna_a_seguire_lo_scenario(
    data: models.CthaData, zone: models.Zone, weekend: models.DayTemplate
) -> None:
    """Il programma proprio della zona si toglie passando `None`."""
    program.set_week_template(data, "solo_comfort", days=dict.fromkeys(range(7), "weekend"))
    program.set_zone_week_template(data, zone.id, "solo_comfort")
    assert resolve.resolve_level(data, zone, MORNING) == LEVEL_COMFORT

    program.set_zone_week_template(data, zone.id, None)
    assert zone.week_template is None


def test_programma_di_zona_inesistente(data: models.CthaData, zone: models.Zone) -> None:
    """Assegnare una settimana che non esiste lascerebbe la zona senza livelli."""
    with pytest.raises(program.UnknownReferenceError):
        program.set_zone_week_template(data, zone.id, "fantasma")
