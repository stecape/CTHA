"""Modifica del programma: funzioni pure su `CthaData`, senza Home Assistant.

Il modello è a riferimenti: un day template è citato da più giorni di più week
template, un week template da più scenari e da singole zone. Ne discendono le
due regole che questo modulo fa rispettare al posto del chiamante:

* **niente riferimenti nel vuoto** — non si può citare un template che non
  esiste, altrimenti la risoluzione smetterebbe silenziosamente di produrre un
  livello e la zona resterebbe ferma senza spiegazione;
* **niente cancellazioni che spezzano il programma** — chi è ancora citato non
  si elimina, e l'errore dice *chi* lo sta usando (`Usage`), che è la stessa
  informazione della vista "chi usa questo template" nel frontend.

Modificare un template condiviso significa modificarlo ovunque. Quando non è
questo che si vuole, la scappatoia è `duplicate_day_template`: copia e, se
richiesto, riaggancia solo i giorni indicati alla copia.

Nessuna funzione qui persiste né riapplica alcunché: mutano il modello in
memoria e basta. Salvataggio e riscrittura delle zone sono responsabilità del
coordinator.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .const import (
    CHAR_BY_LEVEL,
    DAYS_PER_WEEK,
    DEFAULT_DAY_SLOTS,
    DEFAULT_DAY_TEMPLATE_ID,
    INHERIT_CHAR,
    LEVELS,
    MAX_TEMP,
    MIN_TEMP,
    SLOTS_PER_DAY,
)
from .models import (
    CthaData,
    DayTemplate,
    InvalidTemplateError,
    Scenario,
    WeekTemplate,
    Zone,
    validate_slots,
)


class ProgramError(ValueError):
    """Una modifica al programma non è ammissibile."""


class UnknownReferenceError(ProgramError):
    """L'elemento citato non esiste nel modello."""


class ReferenceInUseError(ProgramError):
    """L'elemento è ancora citato da qualcun altro: eliminarlo lascerebbe un buco."""


KIND_WEEK_TEMPLATE = "week_template"
KIND_SCENARIO = "scenario"
KIND_ZONE = "zone"

# L'identificatore del tipo resta in inglese per chi legge `Usage` da codice;
# i messaggi che finiscono sotto gli occhi dell'utente usano queste etichette.
KIND_LABELS: dict[str, str] = {
    KIND_WEEK_TEMPLATE: "settimana tipo",
    KIND_SCENARIO: "scenario",
    KIND_ZONE: "zona",
}

WEEKDAY_NAMES: tuple[str, ...] = (
    "lunedì",
    "martedì",
    "mercoledì",
    "giovedì",
    "venerdì",
    "sabato",
    "domenica",
)


@dataclass(frozen=True, slots=True)
class Usage:
    """Un riferimento a un elemento del programma, da mostrare o da segnalare."""

    kind: str
    id: str
    name: str
    detail: str | None = None

    def __str__(self) -> str:
        """Forma leggibile, usata nei messaggi d'errore dei servizi."""
        label = f"{KIND_LABELS.get(self.kind, self.kind)} '{self.name}'"
        return f"{label} ({self.detail})" if self.detail else label


# --- Interrogazioni ---------------------------------------------------------


def day_template_usages(data: CthaData, template_id: str) -> list[Usage]:
    """Week template che assegnano questa giornata tipo, e in quali giorni."""
    usages = []
    for week in data.week_templates.values():
        days = sorted(day for day, tid in week.days.items() if tid == template_id)
        if days:
            usages.append(
                Usage(KIND_WEEK_TEMPLATE, week.id, week.name, _weekday_list(days))
            )
    return usages


def week_template_usages(data: CthaData, template_id: str) -> list[Usage]:
    """Scenari e zone che seguono questa settimana tipo."""
    usages = [
        Usage(KIND_SCENARIO, scenario.id, scenario.name)
        for scenario in data.scenarios.values()
        if scenario.week_template == template_id
    ]
    usages += [
        Usage(KIND_ZONE, zone.id, zone.name)
        for zone in data.zones.values()
        if zone.week_template == template_id
    ]
    return usages


# --- Giornate tipo ----------------------------------------------------------


def set_day_template(
    data: CthaData,
    template_id: str,
    name: str | None = None,
    slots: str | None = None,
) -> DayTemplate:
    """Crea o aggiorna una giornata tipo; i campi omessi restano come sono.

    Semantica di creazione-o-aggiornamento perché la stessa chiamata, ripetuta
    da un'automazione, deve poter convergere sullo stesso risultato.
    """
    if (template := data.day_templates.get(template_id)) is None:
        template = DayTemplate(
            id=template_id,
            name=name or template_id,
            slots=DEFAULT_DAY_SLOTS if slots is None else _valid_slots(slots),
        )
        data.day_templates[template_id] = template
        return template

    if name is not None:
        template.name = name
    if slots is not None:
        template.slots = _valid_slots(slots)
    return template


def paint_day_template(
    data: CthaData,
    template_id: str,
    level: str | None,
    start_slot: int,
    end_slot: int | None = None,
) -> DayTemplate:
    """Assegna un livello a un intervallo di slot, estremi inclusi.

    È la primitiva su cui poggia il paint-drag della griglia: un trascinamento
    è un intervallo, non 48 scritture. `level` a `None` dipinge l'ereditarietà.
    """
    template = require_day_template(data, template_id)
    end = start_slot if end_slot is None else end_slot

    if not 0 <= start_slot < SLOTS_PER_DAY or not 0 <= end < SLOTS_PER_DAY:
        raise ProgramError(
            f"Gli slot vanno da 0 a {SLOTS_PER_DAY - 1}: ricevuto {start_slot}-{end}"
        )
    if end < start_slot:
        raise ProgramError(f"Intervallo di slot rovesciato: {start_slot}-{end}")

    char = INHERIT_CHAR if level is None else _level_char(level)
    template.slots = (
        template.slots[:start_slot]
        + char * (end - start_slot + 1)
        + template.slots[end + 1 :]
    )
    return template


def duplicate_day_template(
    data: CthaData,
    template_id: str,
    new_id: str | None = None,
    name: str | None = None,
    week_template: str | None = None,
    days: list[int] | None = None,
) -> DayTemplate:
    """Duplica una giornata tipo e, se richiesto, ci riaggancia dei giorni.

    È la scappatoia "duplica e scollega": senza di essa l'unico modo di
    differenziare un giorno che condivide il template con altri sarebbe
    modificarlo per tutti. Con `week_template` e senza `days` si spostano sulla
    copia tutti i giorni che in quella settimana usavano l'originale.
    """
    source = require_day_template(data, template_id)
    copy_id = new_id or _unique_id(data.day_templates, f"{template_id}_copy")
    if copy_id in data.day_templates:
        raise ProgramError(f"Esiste già una giornata tipo con id '{copy_id}'")

    # I riferimenti si risolvono prima di creare la copia: un errore qui non
    # deve lasciare in giro un template orfano.
    week = (
        None if week_template is None else require_week_template(data, week_template)
    )
    targets: list[int] = []
    if week is not None:
        targets = (
            [_valid_weekday(day) for day in days]
            if days
            else [day for day, tid in week.days.items() if tid == template_id]
        )

    copy = DayTemplate(
        id=copy_id, name=name or f"{source.name} (copia)", slots=source.slots
    )
    data.day_templates[copy_id] = copy

    if week is not None:
        for day in targets:
            week.days[day] = copy_id

    return copy


def delete_day_template(data: CthaData, template_id: str) -> DayTemplate:
    """Elimina una giornata tipo, se nessun week template la sta usando."""
    require_day_template(data, template_id)
    if usages := day_template_usages(data, template_id):
        raise ReferenceInUseError(
            f"La giornata tipo '{template_id}' è ancora usata da: "
            + "; ".join(str(usage) for usage in usages)
        )
    return data.day_templates.pop(template_id)


# --- Settimane tipo ---------------------------------------------------------


def set_week_template(
    data: CthaData,
    template_id: str,
    name: str | None = None,
    days: dict[int, str | None] | None = None,
) -> WeekTemplate:
    """Crea o aggiorna una settimana tipo; `days` si fonde con l'esistente.

    La fusione è deliberata: l'operazione tipica è "la domenica usa questa
    giornata", non "riscrivi tutti e sette i giorni". Il valore `None` toglie
    l'assegnazione, lasciando il giorno scoperto.
    """
    # Prima si validano tutte le assegnazioni, poi se ne applica una: una
    # modifica rifiutata a metà lascerebbe il programma in uno stato che
    # l'utente non ha chiesto.
    assignments = {
        _valid_weekday(day): _checked_day_template(data, day_template_id)
        for day, day_template_id in (days or {}).items()
    }

    week = data.week_templates.get(template_id)
    if week is None:
        week = WeekTemplate(
            id=template_id,
            name=name or template_id,
            days=(
                dict.fromkeys(range(DAYS_PER_WEEK), DEFAULT_DAY_TEMPLATE_ID)
                if DEFAULT_DAY_TEMPLATE_ID in data.day_templates
                else {}
            ),
        )
        data.week_templates[template_id] = week
    elif name is not None:
        week.name = name

    for weekday, day_template_id in assignments.items():
        if day_template_id is None:
            week.days.pop(weekday, None)
        else:
            week.days[weekday] = day_template_id

    return week


def delete_week_template(data: CthaData, template_id: str) -> WeekTemplate:
    """Elimina una settimana tipo, se nessuno scenario o zona la segue."""
    require_week_template(data, template_id)
    if usages := week_template_usages(data, template_id):
        raise ReferenceInUseError(
            f"La settimana tipo '{template_id}' è ancora usata da: "
            + "; ".join(str(usage) for usage in usages)
        )
    return data.week_templates.pop(template_id)


# --- Scenari ----------------------------------------------------------------


def set_scenario(
    data: CthaData,
    scenario_id: str,
    name: str | None = None,
    week_template: str | None = None,
    offset: float | None = None,
    zone_offsets: dict[str, float | None] | None = None,
) -> Scenario:
    """Crea o aggiorna uno scenario; gli offset di zona si fondono.

    Un valore `None` in `zone_offsets` rimuove l'eccezione e riporta la zona
    all'offset generale dello scenario.
    """
    for zone_id in zone_offsets or {}:
        require_zone(data, zone_id)

    scenario = data.scenarios.get(scenario_id)
    if scenario is None:
        week_id = week_template or _default_week_template(data)
        require_week_template(data, week_id)
        scenario = Scenario(
            id=scenario_id,
            name=name or scenario_id,
            week_template=week_id,
            offset=offset or 0.0,
        )
        data.scenarios[scenario_id] = scenario
    else:
        if name is not None:
            scenario.name = name
        if week_template is not None:
            require_week_template(data, week_template)
            scenario.week_template = week_template
        if offset is not None:
            scenario.offset = offset

    for zone_id, zone_offset in (zone_offsets or {}).items():
        if zone_offset is None:
            scenario.zone_offsets.pop(zone_id, None)
        else:
            scenario.zone_offsets[zone_id] = zone_offset

    return scenario


def delete_scenario(data: CthaData, scenario_id: str) -> Scenario:
    """Elimina uno scenario, purché non sia quello attivo né l'ultimo rimasto."""
    require_scenario(data, scenario_id)
    if scenario_id == data.active_scenario:
        raise ReferenceInUseError(
            f"Lo scenario '{scenario_id}' è attivo: attivane un altro prima di eliminarlo"
        )
    if len(data.scenarios) == 1:
        raise ReferenceInUseError("Deve restare almeno uno scenario")
    return data.scenarios.pop(scenario_id)


def set_active_scenario(data: CthaData, scenario_id: str) -> Scenario:
    """Rende attivo uno scenario esistente."""
    scenario = require_scenario(data, scenario_id)
    data.active_scenario = scenario_id
    return scenario


# --- Setpoint e zone --------------------------------------------------------


def set_setpoint(
    data: CthaData,
    level: str,
    temperature: float | None,
    zone_id: str | None = None,
) -> float | None:
    """Imposta un setpoint globale o di zona per un livello.

    Senza `zone_id` si tocca la radice dell'ereditarietà, e lì `None` non ha
    significato: un livello globale senza temperatura lascerebbe le zone che lo
    ereditano senza alcun valore. Su una zona, invece, `None` è proprio il modo
    di dire "torna a ereditare".
    """
    _valid_level(level)

    if zone_id is None:
        if temperature is None:
            raise ProgramError(
                f"Il setpoint globale di '{level}' non può ereditare da nessuno"
            )
        data.global_setpoints[level] = _valid_temperature(temperature)
        return data.global_setpoints[level]

    zone = require_zone(data, zone_id)
    if temperature is None:
        zone.setpoints.pop(level, None)
        return None

    zone.setpoints[level] = _valid_temperature(temperature)
    return zone.setpoints[level]


def set_zone_week_template(
    data: CthaData, zone_id: str, template_id: str | None
) -> Zone:
    """Assegna a una zona un programma proprio, o la riporta a quello di scenario."""
    zone = require_zone(data, zone_id)
    if template_id is not None:
        require_week_template(data, template_id)
    zone.week_template = template_id
    return zone


# --- Helper -----------------------------------------------------------------


def require_day_template(data: CthaData, template_id: str) -> DayTemplate:
    """Giornata tipo esistente, o errore che nomina il riferimento rotto."""
    if (template := data.day_templates.get(template_id)) is None:
        raise UnknownReferenceError(f"Giornata tipo sconosciuta: '{template_id}'")
    return template


def require_week_template(data: CthaData, template_id: str) -> WeekTemplate:
    """Settimana tipo esistente, o errore che nomina il riferimento rotto."""
    if (template := data.week_templates.get(template_id)) is None:
        raise UnknownReferenceError(f"Settimana tipo sconosciuta: '{template_id}'")
    return template


def require_scenario(data: CthaData, scenario_id: str) -> Scenario:
    """Scenario esistente, o errore che nomina il riferimento rotto."""
    if (scenario := data.scenarios.get(scenario_id)) is None:
        raise UnknownReferenceError(f"Scenario sconosciuto: '{scenario_id}'")
    return scenario


def require_zone(data: CthaData, zone_id: str) -> Zone:
    """Zona esistente, o errore che nomina il riferimento rotto."""
    if (zone := data.zones.get(zone_id)) is None:
        raise UnknownReferenceError(f"Zona sconosciuta: '{zone_id}'")
    return zone


def _checked_day_template(data: CthaData, template_id: str | None) -> str | None:
    """Id di giornata tipo esistente, o `None` per lasciare il giorno scoperto."""
    if template_id is None:
        return None
    return require_day_template(data, template_id).id


def _default_week_template(data: CthaData) -> str:
    """Settimana su cui appoggiare un nuovo scenario quando non è specificata."""
    active = data.active()
    if active is not None:
        return active.week_template
    if data.week_templates:
        return next(iter(data.week_templates))
    raise UnknownReferenceError("Non esiste nessuna settimana tipo da assegnare")


def _level_char(level: str) -> str:
    """Carattere del day template corrispondente al livello."""
    return CHAR_BY_LEVEL[_valid_level(level)]


def _valid_level(level: str) -> str:
    """Livello noto, o errore: i livelli sono un insieme chiuso."""
    if level not in LEVELS:
        raise ProgramError(
            f"Livello sconosciuto: '{level}' (attesi: {', '.join(LEVELS)})"
        )
    return level


def _valid_slots(slots: str) -> str:
    """Stringa di slot valida, con l'errore del modello riportato come ProgramError.

    Chi chiama queste funzioni deve poter intercettare una sola famiglia di
    errori per dire all'utente "così non si può".
    """
    try:
        return validate_slots(slots)
    except InvalidTemplateError as err:
        raise ProgramError(str(err)) from err


def _valid_temperature(temperature: float) -> float:
    """Temperatura entro i limiti del termostato."""
    if not MIN_TEMP <= temperature <= MAX_TEMP:
        raise ProgramError(
            f"Temperatura fuori scala: {temperature} °C (ammessi {MIN_TEMP}-{MAX_TEMP})"
        )
    return float(temperature)


def _valid_weekday(day: int) -> int:
    """Giorno della settimana valido, con 0 = lunedì."""
    if not 0 <= day < DAYS_PER_WEEK:
        raise ProgramError(f"Giorno della settimana non valido: {day} (0 = lunedì)")
    return day


def _weekday_list(days: list[int]) -> str:
    """Elenco leggibile di giorni, per i messaggi e la vista delle dipendenze."""
    return ", ".join(WEEKDAY_NAMES[day] for day in days)


def _unique_id(existing: Mapping[str, object], base: str) -> str:
    """Primo identificatore libero della forma `base`, `base_2`, `base_3`…"""
    if base not in existing:
        return base
    suffix = 2
    while f"{base}_{suffix}" in existing:
        suffix += 1
    return f"{base}_{suffix}"
