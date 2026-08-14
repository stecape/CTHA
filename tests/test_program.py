"""Editing del programma: integrità dei riferimenti e semantica delle modifiche."""

from __future__ import annotations

import pytest
from conftest import ANTIFREEZE, HIGH, LOW, MORNING
from ctha import models, program, resolve
from ctha.const import (
    DEFAULT_DAY_SLOTS,
    INHERIT_CHAR,
    LAYER_DAY_TEMPLATE,
    LAYER_GLOBAL,
    LAYER_SCENARIO,
    LAYER_WEEK_TEMPLATE,
    LAYER_ZONE,
    SLOTS_PER_DAY,
)


@pytest.fixture
def weekend(data: models.CthaData) -> models.DayTemplate:
    """Una seconda giornata tipo, per i casi con più template in gioco."""
    return program.set_day_template(
        data, "weekend", name="Weekend", slots="a" * SLOTS_PER_DAY
    )


# --- Livelli di temperatura -------------------------------------------------


def test_set_level_crea_con_carattere_e_radice(data: models.CthaData) -> None:
    """Un livello nuovo nasce con un carattere libero e un setpoint globale."""
    level = program.set_level(data, "tiepido", name="Tiepido")

    assert data.levels["tiepido"] is level
    assert level.char not in {"a", "m", "b", "g"}
    assert data.global_setpoints["tiepido"] == 20.0


def test_set_level_prende_il_carattere_dall_id(data: models.CthaData) -> None:
    """Un day template resta leggibile a occhio se il carattere ricorda il nome."""
    assert program.set_level(data, "tiepido").char == "t"


def test_set_level_non_riusa_un_carattere_occupato(data: models.CthaData) -> None:
    """Due livelli con lo stesso carattere renderebbero i template ambigui."""
    # "alta" occupa già la 'a': il livello ripiega sulla lettera successiva.
    assert program.set_level(data, "assente").char != data.levels[HIGH].char


def test_set_level_rifiuta_un_carattere_gia_preso(data: models.CthaData) -> None:
    """Chiederne esplicitamente uno occupato è un errore, non un'assegnazione muta."""
    with pytest.raises(program.ProgramError, match="già di un altro livello"):
        program.set_level(data, "tiepido", char="a")


def test_set_level_aggiorna_senza_toccare_il_carattere(data: models.CthaData) -> None:
    """Il carattere è già scritto nei template: cambiarlo li corromperebbe."""
    program.set_level(data, HIGH, name="Molto alta", color="#ffffff")

    assert data.levels[HIGH].name == "Molto alta"
    assert data.levels[HIGH].color == "#ffffff"
    assert data.levels[HIGH].char == "a"

    with pytest.raises(program.ProgramError, match="non si cambia"):
        program.set_level(data, HIGH, char="x")


def test_delete_level_dipinto_rifiutato(data: models.CthaData) -> None:
    """L'errore deve dire dove il livello è ancora dipinto."""
    with pytest.raises(program.ReferenceInUseError, match="giornata tipo"):
        program.delete_level(data, HIGH)


def test_delete_level_pulisce_tutte_le_tabelle(data: models.CthaData) -> None:
    """Eliminato il livello, le sue temperature non hanno più significato."""
    program.set_setpoint(data, ANTIFREEZE, 8.0, zone_id="z1")
    program.set_setpoint(data, ANTIFREEZE, 6.0, scenario_id="default")

    program.delete_level(data, ANTIFREEZE)

    assert ANTIFREEZE not in data.levels
    assert ANTIFREEZE not in data.global_setpoints
    assert ANTIFREEZE not in data.zones["z1"].setpoints
    assert ANTIFREEZE not in data.scenarios["default"].setpoints


def test_delete_ultimo_livello_rifiutato(data: models.CthaData) -> None:
    """Senza livelli non esisterebbe più un programma da risolvere."""
    data.day_templates["default"].slots = INHERIT_CHAR * SLOTS_PER_DAY
    for level_id in (HIGH, "media", LOW):
        program.delete_level(data, level_id)

    with pytest.raises(program.ReferenceInUseError, match="almeno un livello"):
        program.delete_level(data, ANTIFREEZE)


def test_level_usages_conta_gli_slot(data: models.CthaData) -> None:
    """È la stessa informazione che il pannello mostra sul pulsante Elimina."""
    usages = program.level_usages(data, HIGH)

    assert len(usages) == 1
    assert usages[0].kind == program.KIND_DAY_TEMPLATE
    assert usages[0].detail == "16 slot"


# --- Setpoint nella gerarchia -----------------------------------------------


def test_set_setpoint_globale(data: models.CthaData) -> None:
    """Il globale è la radice: cambia tutti quelli che ereditano."""
    program.set_setpoint(data, HIGH, 22.0)
    assert resolve.resolve_setpoint(data, "z1", MORNING).temperature == 22.0


def test_set_setpoint_globale_non_puo_ereditare(data: models.CthaData) -> None:
    """Sotto il globale non c'è nessuno da cui ereditare."""
    with pytest.raises(program.ProgramError):
        program.set_setpoint(data, HIGH, None)


@pytest.mark.parametrize(
    ("scope", "layer"),
    [
        ({"scenario_id": "default"}, LAYER_SCENARIO),
        ({"zone_id": "z1"}, LAYER_ZONE),
        ({"week_template": "default"}, LAYER_WEEK_TEMPLATE),
        ({"day_template": "default"}, LAYER_DAY_TEMPLATE),
    ],
)
def test_setpoint_scritto_e_poi_riereditato(
    data: models.CthaData, scope: dict[str, str], layer: str
) -> None:
    """In ogni punto della gerarchia `None` è il modo di tornare a ereditare."""
    program.set_setpoint(data, HIGH, 23.0, **scope)
    result = resolve.resolve_setpoint(data, "z1", MORNING)
    assert (result.temperature, result.source) == (23.0, layer)

    program.set_setpoint(data, HIGH, None, **scope)
    result = resolve.resolve_setpoint(data, "z1", MORNING)
    assert (result.temperature, result.source) == (21.0, LAYER_GLOBAL)


def test_setpoint_su_due_ambiti_rifiutato(data: models.CthaData) -> None:
    """Una temperatura sta in un punto solo: scriverne uno e ignorare l'altro no."""
    with pytest.raises(program.ProgramError, match="un solo livello"):
        program.set_setpoint(data, HIGH, 22.0, zone_id="z1", scenario_id="default")


def test_set_setpoint_fuori_scala(data: models.CthaData) -> None:
    """Un valore che il termostato non può tenere non deve entrare nel modello."""
    with pytest.raises(program.ProgramError):
        program.set_setpoint(data, HIGH, 45.0)


def test_set_setpoint_livello_sconosciuto(data: models.CthaData) -> None:
    """I livelli sono aperti, ma non si cita quello che non esiste."""
    with pytest.raises(program.UnknownReferenceError):
        program.set_setpoint(data, "tiepido", 20.0)


def test_set_setpoint_su_elemento_inesistente(data: models.CthaData) -> None:
    """Nemmeno l'ambito si inventa: un typo va detto, non assorbito."""
    with pytest.raises(program.UnknownReferenceError):
        program.set_setpoint(data, HIGH, 20.0, day_template="fantasma")


# --- Giornate tipo ----------------------------------------------------------


def test_set_day_template_crea(data: models.CthaData) -> None:
    """Un id nuovo crea il template, partendo dalla giornata di default."""
    template = program.set_day_template(data, "feriale", name="Feriale")

    assert data.day_templates["feriale"] is template
    assert template.name == "Feriale"
    assert template.slots == DEFAULT_DAY_SLOTS


def test_set_day_template_parte_vuota_se_i_livelli_sono_cambiati(
    data: models.CthaData,
) -> None:
    """La giornata di default cita i livelli iniziali: senza, si parte in ereditarietà."""
    data.day_templates["default"].slots = INHERIT_CHAR * SLOTS_PER_DAY
    program.delete_level(data, HIGH)

    template = program.set_day_template(data, "feriale")

    assert template.slots == INHERIT_CHAR * SLOTS_PER_DAY


def test_set_day_template_aggiorna_senza_azzerare(data: models.CthaData) -> None:
    """I campi omessi restano: la stessa chiamata ripetuta deve convergere."""
    program.set_day_template(data, "feriale", name="Feriale", slots="a" * SLOTS_PER_DAY)
    program.set_day_template(data, "feriale", name="Giorno feriale")

    template = data.day_templates["feriale"]
    assert template.name == "Giorno feriale"
    assert template.slots == "a" * SLOTS_PER_DAY


def test_set_day_template_rifiuta_slot_malformati(data: models.CthaData) -> None:
    """L'errore del modello arriva come ProgramError, mostrabile all'utente."""
    with pytest.raises(program.ProgramError):
        program.set_day_template(data, "rotto", slots="troppo corto")


def test_set_day_template_rifiuta_livelli_inesistenti(data: models.CthaData) -> None:
    """Uno slot che cita un livello eliminato non imporrebbe più nulla."""
    with pytest.raises(program.UnknownReferenceError, match="non esistono"):
        program.set_day_template(data, "rotto", slots="z" * SLOTS_PER_DAY)


def test_paint_dipinge_un_intervallo_inclusivo(data: models.CthaData) -> None:
    """Un trascinamento sulla griglia è un intervallo, estremi compresi."""
    program.paint_day_template(data, "default", HIGH, 0, 3)

    slots = data.day_templates["default"].slots
    assert slots[:4] == "aaaa"
    assert slots[4] == "b"


def test_paint_di_un_solo_slot(data: models.CthaData) -> None:
    """Senza slot finale si dipinge solo quello iniziale."""
    program.paint_day_template(data, "default", HIGH, 5)

    slots = data.day_templates["default"].slots
    assert slots[5] == "a"
    assert slots[4] == "b" and slots[6] == "b"


def test_paint_senza_livello_dipinge_l_ereditarieta(data: models.CthaData) -> None:
    """`None` non è "niente": è il segnaposto di ereditarietà."""
    program.paint_day_template(data, "default", None, 0, 1)
    assert data.day_templates["default"].slots[:2] == INHERIT_CHAR * 2


def test_paint_non_cambia_la_lunghezza(data: models.CthaData) -> None:
    """La stringa deve restare di 48 caratteri anche dopo molte pennellate."""
    program.paint_day_template(data, "default", HIGH, 0, 47)
    program.paint_day_template(data, "default", LOW, 10, 20)
    assert len(data.day_templates["default"].slots) == SLOTS_PER_DAY


@pytest.mark.parametrize(("start", "end"), [(-1, 5), (0, 48), (10, 5)])
def test_paint_rifiuta_intervalli_impossibili(
    data: models.CthaData, start: int, end: int
) -> None:
    """Fuori scala o rovesciato: meglio un errore che una stringa corrotta."""
    with pytest.raises(program.ProgramError):
        program.paint_day_template(data, "default", HIGH, start, end)


def test_paint_su_template_inesistente(data: models.CthaData) -> None:
    """Un riferimento rotto va segnalato, non creato al volo."""
    with pytest.raises(program.UnknownReferenceError):
        program.paint_day_template(data, "fantasma", HIGH, 0)


def test_paint_di_un_livello_inesistente(data: models.CthaData) -> None:
    """Anche il livello è un riferimento, e vale la stessa regola."""
    with pytest.raises(program.UnknownReferenceError):
        program.paint_day_template(data, "default", "tiepido", 0)


# --- Duplica e scollega -----------------------------------------------------


def test_duplicate_genera_un_id_libero(data: models.CthaData) -> None:
    """Senza id esplicito la copia non deve mai sovrascrivere un template."""
    first = program.duplicate_day_template(data, "default")
    second = program.duplicate_day_template(data, "default")

    assert first.id == "default_copy"
    assert second.id == "default_copy_2"
    assert first.slots == data.day_templates["default"].slots


def test_duplicate_copia_anche_le_temperature(data: models.CthaData) -> None:
    """Una copia che perdesse i setpoint non sarebbe la stessa giornata."""
    program.set_setpoint(data, HIGH, 23.0, day_template="default")
    copy = program.duplicate_day_template(data, "default")

    assert copy.setpoints[HIGH] == 23.0
    copy.setpoints[HIGH] = 24.0
    assert data.day_templates["default"].setpoints[HIGH] == 23.0


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
    program.paint_day_template(data, copy.id, HIGH, 0, 47)

    assert data.day_templates["default"].slots == DEFAULT_DAY_SLOTS


# --- Cancellazioni ----------------------------------------------------------


def test_delete_day_template_in_uso_rifiutato(data: models.CthaData) -> None:
    """L'errore deve dire chi lo sta usando, non solo che non si può."""
    with pytest.raises(
        program.ReferenceInUseError, match="settimana tipo 'Settimana tipo'"
    ):
        program.delete_day_template(data, "default")


def test_delete_day_template_libero(
    data: models.CthaData, weekend: models.DayTemplate
) -> None:
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


def test_delete_week_template_assegnata_a_una_zona(data: models.CthaData) -> None:
    """L'errore nomina lo scenario e la zona: è dove va tolta."""
    with pytest.raises(program.ReferenceInUseError, match="scenario 'Normale'"):
        program.delete_week_template(data, "default")


def test_week_template_usages_nomina_le_zone(data: models.CthaData) -> None:
    """Chi usa una settimana tipo è una zona *dentro* uno scenario."""
    usages = program.week_template_usages(data, "default")

    assert len(usages) == 1
    assert usages[0].kind == program.KIND_SCENARIO
    assert usages[0].detail == "Soggiorno"


def test_delete_week_template_libera(data: models.CthaData) -> None:
    """Una settimana che nessuno scenario assegna si elimina."""
    program.set_week_template(data, "inutilizzata", name="Inutilizzata")
    program.delete_week_template(data, "inutilizzata")

    assert "inutilizzata" not in data.week_templates


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


def test_set_scenario_parte_dalla_configurazione_attiva(
    data: models.CthaData,
) -> None:
    """Uno scenario nuovo deve essere subito attivabile senza fermare l'impianto."""
    scenario = program.set_scenario(data, "vacanza", name="Vacanza")

    assert scenario.zones == {"z1": "default"}


def test_set_scenario_assegna_le_zone(data: models.CthaData) -> None:
    """È l'operazione che definisce uno scenario: chi segue cosa."""
    program.set_week_template(data, "inverno", name="Inverno")
    program.set_scenario(data, "default", zones={"z1": "inverno"})

    assert data.scenarios["default"].zones["z1"] == "inverno"


def test_zona_a_none_esce_dallo_scenario(data: models.CthaData) -> None:
    """Una zona non programmata in uno scenario è uno stato legittimo."""
    program.set_scenario(data, "default", zones={"z1": None})

    assert "z1" not in data.scenarios["default"].zones
    assert resolve.resolve_setpoint(data, "z1", MORNING).temperature is None


def test_set_scenario_rifiuta_settimane_inesistenti(data: models.CthaData) -> None:
    """Meglio nessuna assegnazione che una che non risolve nulla."""
    with pytest.raises(program.UnknownReferenceError):
        program.set_scenario(data, "default", zones={"z1": "fantasma"})


def test_set_scenario_rifiuta_zone_inesistenti(data: models.CthaData) -> None:
    """Una zona che non esiste è quasi certamente un typo."""
    with pytest.raises(program.UnknownReferenceError):
        program.set_scenario(data, "default", zones={"fantasma": "default"})


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
    """Il cambio di scenario si vede subito, su entrambi gli assi."""
    program.set_scenario(data, "vacanza", name="Vacanza")
    program.set_setpoint(data, HIGH, 16.0, scenario_id="vacanza")
    program.set_active_scenario(data, "vacanza")

    assert resolve.resolve_setpoint(data, "z1", MORNING).temperature == 16.0


def test_activate_scenario_inesistente(data: models.CthaData) -> None:
    """Il servizio deve poter rispondere "questo scenario non esiste"."""
    with pytest.raises(program.UnknownReferenceError):
        program.set_active_scenario(data, "fantasma")


# --- Zone -------------------------------------------------------------------


def test_set_zone_week_template_lavora_sullo_scenario_attivo(
    data: models.CthaData, weekend: models.DayTemplate
) -> None:
    """Senza scenario esplicito si tocca quello in corso: è il gesto quotidiano."""
    program.set_week_template(
        data, "sempre_alta", days=dict.fromkeys(range(7), "weekend")
    )
    program.set_zone_week_template(data, "z1", "sempre_alta")

    assert data.scenarios["default"].zones["z1"] == "sempre_alta"


def test_set_zone_week_template_su_un_altro_scenario(data: models.CthaData) -> None:
    """Si può preparare uno scenario senza attivarlo."""
    program.set_week_template(data, "inverno", name="Inverno")
    program.set_scenario(data, "vacanza", name="Vacanza")
    program.set_zone_week_template(data, "z1", "inverno", scenario_id="vacanza")

    assert data.scenarios["vacanza"].zones["z1"] == "inverno"
    assert data.scenarios["default"].zones["z1"] == "default"


def test_programma_di_zona_inesistente(data: models.CthaData) -> None:
    """Assegnare una settimana che non esiste lascerebbe la zona senza livelli."""
    with pytest.raises(program.UnknownReferenceError):
        program.set_zone_week_template(data, "z1", "fantasma")


def test_ensure_zone_programma_la_zona_in_ogni_scenario(
    data: models.CthaData,
) -> None:
    """Una zona appena aggiunta non deve restare muta finché non si apre il pannello."""
    program.set_scenario(data, "vacanza", name="Vacanza")

    assert program.ensure_zone(data, "z2", "Cucina")

    assert data.zones["z2"].name == "Cucina"
    assert data.scenarios["default"].zones["z2"] == "default"
    assert data.scenarios["vacanza"].zones["z2"] == "default"


def test_ensure_zone_e_idempotente(data: models.CthaData) -> None:
    """Il coordinator la chiama a ogni avvio: non deve segnalare modifiche finte."""
    assert not program.ensure_zone(data, "z1", "Soggiorno")


def test_ensure_zone_aggiorna_il_nome(data: models.CthaData) -> None:
    """Rinominare la config entry deve arrivare fino al modello."""
    assert program.ensure_zone(data, "z1", "Salotto")
    assert data.zones["z1"].name == "Salotto"


def test_remove_zone_non_lascia_riferimenti(data: models.CthaData) -> None:
    """Rimossa la config entry, la zona non deve restare citata dagli scenari."""
    program.set_scenario(data, "vacanza", name="Vacanza")
    data.overrides["z1"] = models.Override(zone_id="z1", temperature=22.0)

    program.remove_zone(data, "z1")

    assert "z1" not in data.zones
    assert "z1" not in data.overrides
    assert all("z1" not in scenario.zones for scenario in data.scenarios.values())
