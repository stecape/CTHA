"""Risoluzione del setpoint: funzioni pure, senza dipendenze da Home Assistant.

I due assi restano deliberatamente separati:

* **asse temporale** — scenario attivo → settimana tipo della zona in quello
  scenario → giornata tipo del giorno → slot → livello;
* **asse termico** — la gerarchia delle sovrascritture, dal più specifico al
  più generale: day template → week template → zona → scenario → globale.

Il primo dice *quale livello* vale in un istante, il secondo *quanti gradi*
vale quel livello lungo quel percorso. I due assi si incontrano nella catena:
gli stessi quattro elementi che portano al livello sono anche i quattro luoghi
in cui la sua temperatura può essere sovrascritta, ed è il motivo per cui si
risolvono in un passaggio solo.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .const import (
    LAYER_DAY_TEMPLATE,
    LAYER_GLOBAL,
    LAYER_NONE,
    LAYER_SCENARIO,
    LAYER_WEEK_TEMPLATE,
    LAYER_ZONE,
    MAX_TEMP,
    MIN_TEMP,
    SLOT_MINUTES,
    SLOTS_PER_DAY,
)
from .models import CthaData, DayTemplate, Scenario, WeekTemplate, Zone


@dataclass(frozen=True, slots=True)
class Chain:
    """Il percorso che porta da una zona al suo slot, in un dato istante.

    È il cammino nella gerarchia: scenario attivo, zona, settimana tipo che lo
    scenario le assegna, giornata tipo del giorno. Un anello mancante — zona non
    configurata nello scenario, giorno scoperto, template eliminato — spezza la
    catena, e da lì in poi non c'è nulla da applicare.
    """

    scenario: Scenario | None = None
    zone: Zone | None = None
    week: WeekTemplate | None = None
    day: DayTemplate | None = None
    slot: int = 0

    @property
    def complete(self) -> bool:
        """True se la catena arriva fino alla giornata tipo."""
        return self.day is not None


@dataclass(frozen=True, slots=True)
class Resolution:
    """Esito della risoluzione, con il livello della gerarchia che ha deciso.

    L'interfaccia deve poter mostrare non solo la temperatura finale ma anche
    da dove arriva: `source` è uno dei cinque livelli della gerarchia, e senza
    di esso un valore ereditato è indistinguibile da uno scritto a mano.
    """

    level: str | None = None
    temperature: float | None = None
    source: str = LAYER_NONE


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


def resolve_chain(data: CthaData, zone_id: str, moment: datetime) -> Chain:
    """Percorre la gerarchia dalla zona fino alla giornata tipo dell'istante."""
    slot = slot_index(moment)
    zone = data.zones.get(zone_id)
    scenario = data.active()
    if zone is None or scenario is None:
        return Chain(scenario=scenario, zone=zone, slot=slot)

    week_id = scenario.week_template_for(zone_id)
    week = data.week_templates.get(week_id) if week_id else None
    if week is None:
        return Chain(scenario=scenario, zone=zone, slot=slot)

    day_id = week.day_template_id(moment.weekday())
    day = data.day_templates.get(day_id) if day_id else None
    return Chain(scenario=scenario, zone=zone, week=week, day=day, slot=slot)


def resolve_level(data: CthaData, zone_id: str, moment: datetime) -> str | None:
    """Risolve l'asse temporale: livello attivo per la zona in quell'istante.

    Restituisce `None` quando lo slot eredita esplicitamente, o quando la
    catena è incompleta: in entrambi i casi non c'è un livello da applicare.
    """
    return level_of(data, resolve_chain(data, zone_id, moment))


def level_of(data: CthaData, chain: Chain) -> str | None:
    """Livello imposto dallo slot in fondo alla catena, se ce n'è uno."""
    if chain.day is None:
        return None
    return data.level_at(chain.day, chain.slot)


def resolve_temperature(
    data: CthaData, chain: Chain, level: str | None
) -> Resolution:
    """Risolve l'asse termico percorrendo la gerarchia dal basso verso l'alto.

    Il primo livello della catena che dichiara una temperatura per quel livello
    vince; chi non la dichiara eredita da chi sta sopra. Il globale chiude la
    catena, ed è l'unico che non può ereditare da nessuno.
    """
    if level is None:
        return Resolution()

    layers: tuple[tuple[str, dict[str, float]], ...] = (
        (LAYER_DAY_TEMPLATE, chain.day.setpoints if chain.day else {}),
        (LAYER_WEEK_TEMPLATE, chain.week.setpoints if chain.week else {}),
        (LAYER_ZONE, chain.zone.setpoints if chain.zone else {}),
        (LAYER_SCENARIO, chain.scenario.setpoints if chain.scenario else {}),
        (LAYER_GLOBAL, data.global_setpoints),
    )

    for source, setpoints in layers:
        if (temperature := setpoints.get(level)) is not None:
            return Resolution(level, clamp(temperature), source)

    # Livello esistente ma senza alcun setpoint, nemmeno globale: non c'è una
    # temperatura da scrivere, e inventarne una sarebbe peggio che non scrivere.
    return Resolution(level, None, LAYER_NONE)


def resolve_setpoint(data: CthaData, zone_id: str, moment: datetime) -> Resolution:
    """Risoluzione completa per una zona: livello e temperatura risultante."""
    chain = resolve_chain(data, zone_id, moment)
    return resolve_temperature(data, chain, level_of(data, chain))


def resolve_level_temperature(
    data: CthaData, zone_id: str, level: str, moment: datetime
) -> Resolution:
    """Gradi che varrebbero per un livello imposto dall'esterno.

    Serve ai preset: forzare «alta» significa forzare la temperatura che «alta»
    ha *per questa zona adesso*, cioè lungo la catena corrente e non nel vuoto.
    """
    return resolve_temperature(data, resolve_chain(data, zone_id, moment), level)


def clamp(temperature: float) -> float:
    """Riporta la temperatura entro i limiti ammessi dal termostato."""
    return min(MAX_TEMP, max(MIN_TEMP, temperature))


def day_levels(data: CthaData, zone_id: str, moment: datetime) -> list[str | None]:
    """Livelli dei 48 slot del giorno indicato, per la griglia di programmazione."""
    base = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    return [
        resolve_level(data, zone_id, base + timedelta(minutes=SLOT_MINUTES * slot))
        for slot in range(SLOTS_PER_DAY)
    ]
