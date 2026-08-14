"""Modifica del programma: funzioni pure su `CthaData`, senza Home Assistant.

Il modello è a riferimenti: un day template è citato da più giorni di più week
template, un week template dalle zone di più scenari, un livello di temperatura
dagli slot di più giornate tipo. Ne discendono le due regole che questo modulo
fa rispettare al posto del chiamante:

* **niente riferimenti nel vuoto** — non si può citare un template o un livello
  che non esiste, altrimenti la risoluzione smetterebbe silenziosamente di
  produrre un valore e la zona resterebbe ferma senza spiegazione;
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
    DAYS_PER_WEEK,
    DEFAULT_DAY_SLOTS,
    DEFAULT_DAY_TEMPLATE_ID,
    DEFAULT_LEVEL_COLOR,
    DEFAULT_LEVEL_SETPOINT,
    INHERIT_CHAR,
    LAYER_DAY_TEMPLATE,
    LAYER_GLOBAL,
    LAYER_SCENARIO,
    LAYER_WEEK_TEMPLATE,
    LAYER_ZONE,
    LEVEL_CHARS,
    MAX_TEMP,
    MIN_TEMP,
    SLOTS_PER_DAY,
)
from .models import (
    CthaData,
    DayTemplate,
    InvalidTemplateError,
    Scenario,
    TemperatureLevel,
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


KIND_DAY_TEMPLATE = "day_template"
KIND_WEEK_TEMPLATE = "week_template"
KIND_SCENARIO = "scenario"
KIND_ZONE = "zone"

# L'identificatore del tipo resta in inglese per chi legge `Usage` da codice;
# i messaggi che finiscono sotto gli occhi dell'utente usano queste etichette.
KIND_LABELS: dict[str, str] = {
    KIND_DAY_TEMPLATE: "giornata tipo",
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
    """Scenari che assegnano questa settimana tipo, e a quali zone."""
    usages = []
    for scenario in data.scenarios.values():
        zones = [
            data.zones[zone_id].name if zone_id in data.zones else zone_id
            for zone_id, week_id in scenario.zones.items()
            if week_id == template_id
        ]
        if zones:
            usages.append(
                Usage(KIND_SCENARIO, scenario.id, scenario.name, ", ".join(zones))
            )
    return usages


def level_usages(data: CthaData, level_id: str) -> list[Usage]:
    """Giornate tipo che dipingono questo livello, e in quanti slot.

    Solo le giornate tipo contano: un livello citato da una tabella di setpoint
    non tiene in piedi nulla, e la sua riga sparisce insieme al livello. Uno
    slot dipinto invece resterebbe orfano, cioè un pezzo di programma che smette
    di imporre qualcosa senza che nessuno l'abbia chiesto.
    """
    if (level := data.levels.get(level_id)) is None:
        return []
    usages = []
    for template in data.day_templates.values():
        if painted := template.slots.count(level.char):
            usages.append(
                Usage(
                    KIND_DAY_TEMPLATE,
                    template.id,
                    template.name,
                    f"{painted} slot",
                )
            )
    return usages


# --- Livelli di temperatura -------------------------------------------------


def set_level(
    data: CthaData,
    level_id: str,
    name: str | None = None,
    color: str | None = None,
    char: str | None = None,
    setpoint: float | None = None,
) -> TemperatureLevel:
    """Crea o aggiorna un livello di temperatura.

    Alla creazione il livello riceve un carattere libero per i day template e,
    se non se ne indica una, una temperatura globale di partenza: il globale è
    la radice dell'ereditarietà e un livello senza radice non produrrebbe mai
    un setpoint.
    """
    if not level_id:
        raise ProgramError("Un livello di temperatura richiede un identificatore")

    if (level := data.levels.get(level_id)) is None:
        level = TemperatureLevel(
            id=level_id,
            name=name or level_id,
            char=_reserve_char(data, char, level_id),
            color=color or DEFAULT_LEVEL_COLOR,
        )
        data.levels[level_id] = level
        data.global_setpoints[level_id] = _valid_temperature(
            DEFAULT_LEVEL_SETPOINT if setpoint is None else setpoint
        )
        return level

    if char is not None and char != level.char:
        raise ProgramError(
            f"Il carattere di '{level_id}' non si cambia: è già scritto nelle "
            "giornate tipo che lo usano"
        )
    if name is not None:
        level.name = name
    if color is not None:
        level.color = color
    if setpoint is not None:
        data.global_setpoints[level_id] = _valid_temperature(setpoint)
    return level


def delete_level(data: CthaData, level_id: str) -> TemperatureLevel:
    """Elimina un livello e ogni setpoint che lo riguarda, se non è dipinto."""
    require_level(data, level_id)
    if len(data.levels) == 1:
        raise ReferenceInUseError("Deve restare almeno un livello di temperatura")
    if usages := level_usages(data, level_id):
        raise ReferenceInUseError(
            f"Il livello '{level_id}' è ancora dipinto in: "
            + "; ".join(str(usage) for usage in usages)
        )

    for setpoints in _all_setpoint_tables(data):
        setpoints.pop(level_id, None)
    return data.levels.pop(level_id)


def set_setpoint(
    data: CthaData,
    level: str,
    temperature: float | None,
    scenario_id: str | None = None,
    zone_id: str | None = None,
    week_template: str | None = None,
    day_template: str | None = None,
) -> float | None:
    """Scrive la temperatura di un livello a un punto preciso della gerarchia.

    Senza alcun ambito si tocca il globale, e lì `None` non ha significato: un
    livello globale senza temperatura lascerebbe senza valore tutti quelli che
    lo ereditano. In ogni altro punto `None` è proprio il modo di dire "torna a
    ereditare da chi sta sopra".
    """
    require_level(data, level)
    layer, setpoints = _setpoint_table(
        data, scenario_id, zone_id, week_template, day_template
    )

    if temperature is None:
        if layer == LAYER_GLOBAL:
            raise ProgramError(
                f"Il setpoint globale di '{level}' non può ereditare da nessuno"
            )
        setpoints.pop(level, None)
        return None

    setpoints[level] = _valid_temperature(temperature)
    return setpoints[level]


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
            slots=_default_slots(data) if slots is None else _valid_slots(data, slots),
        )
        data.day_templates[template_id] = template
        return template

    if name is not None:
        template.name = name
    if slots is not None:
        template.slots = _valid_slots(data, slots)
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

    char = INHERIT_CHAR if level is None else require_level(data, level).char
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
        id=copy_id,
        name=name or f"{source.name} (copia)",
        slots=source.slots,
        setpoints=dict(source.setpoints),
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
    """Elimina una settimana tipo, se nessuno scenario la assegna a una zona."""
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
    zones: dict[str, str | None] | None = None,
) -> Scenario:
    """Crea o aggiorna uno scenario; le assegnazioni di zona si fondono.

    Uno scenario nuovo parte dalla configurazione di quello attivo: chi ne crea
    uno vuole quasi sempre variarne uno esistente, e partire da tutte le zone
    scoperte vorrebbe dire un impianto fermo appena lo si attiva. Un valore
    `None` in `zones` toglie la zona dallo scenario, che è il modo di dire "qui
    questa zona non è programmata".
    """
    assignments = {
        require_zone(data, zone_id).id: _checked_week_template(data, week_id)
        for zone_id, week_id in (zones or {}).items()
    }

    scenario = data.scenarios.get(scenario_id)
    if scenario is None:
        active = data.active()
        scenario = Scenario(
            id=scenario_id,
            name=name or scenario_id,
            zones=dict(active.zones) if active else {},
        )
        data.scenarios[scenario_id] = scenario
    elif name is not None:
        scenario.name = name

    for zone_id, week_id in assignments.items():
        if week_id is None:
            scenario.zones.pop(zone_id, None)
        else:
            scenario.zones[zone_id] = week_id

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


def set_zone_week_template(
    data: CthaData,
    zone_id: str,
    template_id: str | None,
    scenario_id: str | None = None,
) -> Scenario:
    """Assegna a una zona la sua settimana tipo dentro uno scenario.

    Senza `scenario_id` si lavora sullo scenario attivo: è il gesto quotidiano,
    e chiedere ogni volta di ripetere quale scenario sia in corso sarebbe solo
    un modo di sbagliarlo.
    """
    require_zone(data, zone_id)
    scenario = (
        require_scenario(data, scenario_id)
        if scenario_id is not None
        else _require_active(data)
    )

    if template_id is None:
        scenario.zones.pop(zone_id, None)
    else:
        require_week_template(data, template_id)
        scenario.zones[zone_id] = template_id
    return scenario


# --- Zone -------------------------------------------------------------------


def ensure_zone(data: CthaData, zone_id: str, name: str) -> bool:
    """Registra la zona e le dà un programma in ogni scenario; dice se ha cambiato.

    Una zona appena aggiunta non è citata da nessuno scenario, e uno scenario
    che non la cita non la programma: senza questa assegnazione iniziale la
    zona resterebbe muta finché qualcuno non apre il pannello. Si sceglie la
    settimana tipo già più diffusa nello scenario, che è quasi sempre quella
    giusta e comunque la più facile da correggere.
    """
    changed = False
    if (zone := data.zones.get(zone_id)) is None:
        data.zones[zone_id] = Zone(id=zone_id, name=name)
        changed = True
    elif zone.name != name:
        zone.name = name
        changed = True

    for scenario in data.scenarios.values():
        if zone_id in scenario.zones:
            continue
        if (week_id := _prevailing_week_template(data, scenario)) is not None:
            scenario.zones[zone_id] = week_id
            changed = True

    return changed


def remove_zone(data: CthaData, zone_id: str) -> None:
    """Toglie ogni traccia di una zona: registro, override, assegnazioni."""
    data.zones.pop(zone_id, None)
    data.overrides.pop(zone_id, None)
    for scenario in data.scenarios.values():
        scenario.zones.pop(zone_id, None)


# --- Helper -----------------------------------------------------------------


def require_level(data: CthaData, level_id: str) -> TemperatureLevel:
    """Livello esistente, o errore che nomina il riferimento rotto."""
    if (level := data.levels.get(level_id)) is None:
        known = ", ".join(data.levels) or "nessuno"
        raise UnknownReferenceError(
            f"Livello di temperatura sconosciuto: '{level_id}' (esistenti: {known})"
        )
    return level


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


def _require_active(data: CthaData) -> Scenario:
    """Scenario attivo, o errore: senza di esso non c'è programma da toccare."""
    if (scenario := data.active()) is None:
        raise UnknownReferenceError(
            f"Lo scenario attivo '{data.active_scenario}' non esiste"
        )
    return scenario


def _checked_day_template(data: CthaData, template_id: str | None) -> str | None:
    """Id di giornata tipo esistente, o `None` per lasciare il giorno scoperto."""
    if template_id is None:
        return None
    return require_day_template(data, template_id).id


def _checked_week_template(data: CthaData, template_id: str | None) -> str | None:
    """Id di settimana tipo esistente, o `None` per lasciare la zona scoperta."""
    if template_id is None:
        return None
    return require_week_template(data, template_id).id


def _setpoint_table(
    data: CthaData,
    scenario_id: str | None,
    zone_id: str | None,
    week_template: str | None,
    day_template: str | None,
) -> tuple[str, dict[str, float]]:
    """Livello della gerarchia indicato dagli ambiti, e la sua tabella.

    Gli ambiti si escludono: una temperatura sta in un punto solo della
    gerarchia, e accettarne due significherebbe scriverne una e ignorare
    l'altra senza dirlo.
    """
    scopes = [
        (LAYER_SCENARIO, scenario_id),
        (LAYER_ZONE, zone_id),
        (LAYER_WEEK_TEMPLATE, week_template),
        (LAYER_DAY_TEMPLATE, day_template),
    ]
    given = [(layer, value) for layer, value in scopes if value is not None]

    if not given:
        return LAYER_GLOBAL, data.global_setpoints
    if len(given) > 1:
        raise ProgramError(
            "Un setpoint appartiene a un solo livello della gerarchia: indicati "
            + ", ".join(layer for layer, _ in given)
        )

    layer, target = given[0]
    if layer == LAYER_SCENARIO:
        return layer, require_scenario(data, target).setpoints
    if layer == LAYER_ZONE:
        return layer, require_zone(data, target).setpoints
    if layer == LAYER_WEEK_TEMPLATE:
        return layer, require_week_template(data, target).setpoints
    return layer, require_day_template(data, target).setpoints


def _all_setpoint_tables(data: CthaData) -> list[dict[str, float]]:
    """Ogni tabella di setpoint del modello, per le pulizie a valle."""
    return [
        data.global_setpoints,
        *(scenario.setpoints for scenario in data.scenarios.values()),
        *(zone.setpoints for zone in data.zones.values()),
        *(week.setpoints for week in data.week_templates.values()),
        *(day.setpoints for day in data.day_templates.values()),
    ]


def _reserve_char(data: CthaData, requested: str | None, level_id: str) -> str:
    """Carattere libero per il nuovo livello: quello chiesto, o uno derivato dall'id."""
    taken = {level.char for level in data.levels.values()}

    if requested is not None:
        if len(requested) != 1 or requested not in LEVEL_CHARS:
            raise ProgramError(
                f"Il carattere di un livello è uno solo, fra '{LEVEL_CHARS}': "
                f"ricevuto '{requested}'"
            )
        if requested in taken:
            raise ProgramError(f"Il carattere '{requested}' è già di un altro livello")
        return requested

    # Prima le lettere dell'identificatore, così il day template resta leggibile
    # anche a occhio nudo; poi il resto dell'alfabeto.
    for char in (*level_id.lower(), *LEVEL_CHARS):
        if char in LEVEL_CHARS and char not in taken:
            return char
    raise ProgramError(f"Finiti i caratteri disponibili: {len(taken)} livelli esistenti")


def _default_slots(data: CthaData) -> str:
    """Slot di partenza per una giornata tipo nuova.

    La giornata di default cita i quattro livelli iniziali: se l'utente li ha
    eliminati o ne ha cambiato i caratteri, quella stringa non vuole più dire
    niente, e una giornata tutta ereditata è l'unica partenza sempre valida.
    """
    known = {level.char for level in data.levels.values()} | {INHERIT_CHAR}
    if set(DEFAULT_DAY_SLOTS) <= known:
        return DEFAULT_DAY_SLOTS
    return INHERIT_CHAR * SLOTS_PER_DAY


def _prevailing_week_template(data: CthaData, scenario: Scenario) -> str | None:
    """Settimana tipo più diffusa nello scenario, o la prima che esiste."""
    if scenario.zones:
        counts: dict[str, int] = {}
        for week_id in scenario.zones.values():
            counts[week_id] = counts.get(week_id, 0) + 1
        return max(counts, key=lambda week_id: counts[week_id])
    return next(iter(data.week_templates), None)


def _valid_slots(data: CthaData, slots: str) -> str:
    """Stringa di slot valida per forma e per riferimenti.

    Chi chiama queste funzioni deve poter intercettare una sola famiglia di
    errori per dire all'utente "così non si può".
    """
    try:
        validate_slots(slots)
    except InvalidTemplateError as err:
        raise ProgramError(str(err)) from err

    known = {level.char for level in data.levels.values()} | {INHERIT_CHAR}
    if unknown := sorted(set(slots) - known):
        raise UnknownReferenceError(
            f"Gli slot citano livelli che non esistono: {', '.join(unknown)}"
        )
    return slots


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
