"""Risoluzione del setpoint: funzioni pure, senza dipendenze da Home Assistant.

I due assi restano deliberatamente separati:

* **asse temporale** — scenario → week template → day template → slot → livello;
* **asse termico** — setpoint di zona → offset di scenario → setpoint globale.

Il primo dice *quale livello* vale in un istante, il secondo *quanti gradi*
vale quel livello per quella zona. Tenerli distinti è ciò che permette di
cambiare scenario senza riscrivere i template, e di ritoccare una zona senza
toccare il programma.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .const import (
    MAX_TEMP,
    MIN_TEMP,
    SLOT_MINUTES,
    SLOTS_PER_DAY,
)
from .models import CthaData, Scenario, Zone


@dataclass(frozen=True, slots=True)
class Resolution:
    """Esito della risoluzione, con la provenienza di ogni contributo.

    L'interfaccia deve poter mostrare non solo la temperatura finale ma anche
    da dove arriva: `source` distingue un valore proprio della zona da uno
    ereditato dal globale.
    """

    level: str | None
    base: float | None
    source: str
    offset: float
    temperature: float | None

    SOURCE_ZONE = "zone"
    SOURCE_GLOBAL = "global"
    SOURCE_NONE = "none"


def slot_index(moment: datetime) -> int:
    """Indice dello slot da 30 minuti che contiene l'istante indicato."""
    return (moment.hour * 60 + moment.minute) // SLOT_MINUTES


def slot_start(moment: datetime) -> datetime:
    """Istante di inizio dello slot corrente."""
    return moment.replace(
        minute=(moment.minute // SLOT_MINUTES) * SLOT_MINUTES, second=0, microsecond=0
    )


def next_slot_start(moment: datetime) -> datetime:
    """Istante di inizio dello slot successivo, usato dalla policy next_slot."""
    return slot_start(moment) + timedelta(minutes=SLOT_MINUTES)


def resolve_level(data: CthaData, zone: Zone, moment: datetime) -> str | None:
    """Risolve l'asse temporale: livello attivo per la zona in quell'istante.

    Restituisce `None` quando lo slot eredita esplicitamente, o quando la
    catena di riferimenti è incompleta (template cancellato, giorno non
    assegnato): in entrambi i casi non c'è un livello da applicare.
    """
    scenario = data.active()
    if scenario is None:
        return None

    week_id = zone.week_template or scenario.week_template
    week = data.week_templates.get(week_id)
    if week is None:
        return None

    day_id = week.day_template_id(moment.weekday())
    if day_id is None:
        return None

    day = data.day_templates.get(day_id)
    if day is None:
        return None

    return day.level_at(slot_index(moment))


def resolve_temperature(
    data: CthaData, zone: Zone, level: str | None, scenario: Scenario | None
) -> Resolution:
    """Risolve l'asse termico: gradi corrispondenti a un livello per la zona."""
    if level is None:
        return Resolution(None, None, Resolution.SOURCE_NONE, 0.0, None)

    base = zone.setpoint_for(level)
    source = Resolution.SOURCE_ZONE
    if base is None:
        base = data.global_setpoints.get(level)
        source = Resolution.SOURCE_GLOBAL

    if base is None:
        return Resolution(level, None, Resolution.SOURCE_NONE, 0.0, None)

    offset = scenario.offset_for(zone.id) if scenario else 0.0
    return Resolution(
        level=level,
        base=base,
        source=source,
        offset=offset,
        temperature=clamp(base + offset),
    )


def resolve_setpoint(data: CthaData, zone_id: str, moment: datetime) -> Resolution:
    """Risoluzione completa per una zona: livello e temperatura risultante."""
    zone = data.zones.get(zone_id)
    if zone is None:
        return Resolution(None, None, Resolution.SOURCE_NONE, 0.0, None)

    level = resolve_level(data, zone, moment)
    return resolve_temperature(data, zone, level, data.active())


def clamp(temperature: float) -> float:
    """Riporta la temperatura entro i limiti ammessi dal termostato."""
    return min(MAX_TEMP, max(MIN_TEMP, temperature))


def day_levels(data: CthaData, zone: Zone, moment: datetime) -> list[str | None]:
    """Livelli dei 48 slot del giorno indicato, per la griglia di programmazione."""
    base = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return [
        resolve_level(data, zone, base + timedelta(minutes=SLOT_MINUTES * slot))
        for slot in range(SLOTS_PER_DAY)
    ]
