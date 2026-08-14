"""Modello dati di CTHA, serializzabile nello Store di Home Assistant.

Il modello è basato su riferimenti: scenari, week template e day template si
citano per identificatore anziché duplicare i dati, così un template può essere
riusato da più giorni e da più scenari.

Cinque elementi portano una tabella `setpoints` (livello → °C): il globale, lo
scenario, la zona, la settimana tipo e la giornata tipo. Un livello assente da
una tabella non è un "non so": è la richiesta esplicita di ereditare da chi sta
sopra nella gerarchia. Quale sia il "sopra" lo decide `resolve.py`, che è
l'unico posto in cui l'ordine è scritto.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Self

from .const import (
    DEFAULT_DAY_SLOTS,
    DEFAULT_DAY_TEMPLATE_ID,
    DEFAULT_LEVEL_COLOR,
    DEFAULT_LEVELS,
    DEFAULT_SCENARIO_ID,
    DEFAULT_WEEK_TEMPLATE_ID,
    INHERIT_CHAR,
    LEVEL_CHARS,
    OVERRIDE_SOURCE_HA,
    POLICY_NEXT_SLOT,
    SLOTS_PER_DAY,
)


class InvalidTemplateError(ValueError):
    """Un template non rispetta il formato atteso."""


def validate_slots(slots: str) -> str:
    """Verifica lunghezza e alfabeto di una stringa di slot.

    Qui si controlla solo la forma: che i caratteri corrispondano a livelli
    davvero esistenti è una domanda sul modello intero, e la fa `program.py`.
    Tenerla fuori dal dataclass permette di ricostruire dallo Store un template
    che cita un livello eliminato, invece di rifiutare l'intero salvataggio.
    """
    if len(slots) != SLOTS_PER_DAY:
        raise InvalidTemplateError(
            f"Un day template richiede {SLOTS_PER_DAY} caratteri, ricevuti {len(slots)}"
        )
    if unknown := set(slots) - set(LEVEL_CHARS) - {INHERIT_CHAR}:
        raise InvalidTemplateError(
            f"Caratteri non validi nel day template: {sorted(unknown)}"
        )
    return slots


def _setpoints(raw: Any) -> dict[str, float]:
    """Tabella di setpoint ripulita: i valori vuoti sono assenze, non zeri."""
    if not isinstance(raw, dict):
        return {}
    return {
        str(level): float(value) for level, value in raw.items() if value is not None
    }


@dataclass(slots=True)
class TemperatureLevel:
    """Un livello di temperatura: «alta», «antigelo», o qualsiasi altro.

    `char` è il carattere che rappresenta il livello dentro i day template, e
    non cambia mai dopo la creazione: cambiarlo vorrebbe dire riscrivere tutte
    le giornate tipo che lo usano. `color` serve al pannello, che senza un
    colore per livello non potrebbe disegnare una griglia leggibile una volta
    che i livelli non sono più tre noti in anticipo.
    """

    id: str
    name: str
    char: str
    color: str = DEFAULT_LEVEL_COLOR

    def to_dict(self) -> dict[str, Any]:
        """Serializza il livello."""
        return {"id": self.id, "name": self.name, "char": self.char, "color": self.color}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Ricostruisce il livello dallo Store."""
        return cls(
            id=data["id"],
            name=data["name"],
            char=data["char"],
            color=data.get("color", DEFAULT_LEVEL_COLOR),
        )


@dataclass(slots=True)
class DayTemplate:
    """Giornata tipo: 48 slot da 30 minuti, un carattere per slot."""

    id: str
    name: str
    slots: str = DEFAULT_DAY_SLOTS
    setpoints: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Rifiuta subito i template malformati, prima che finiscano nello Store."""
        validate_slots(self.slots)

    def char_at(self, slot: int) -> str | None:
        """Carattere dello slot indicato, o `None` se lo slot eredita."""
        char = self.slots[slot % SLOTS_PER_DAY]
        return None if char == INHERIT_CHAR else char

    def to_dict(self) -> dict[str, Any]:
        """Serializza il template."""
        return {
            "id": self.id,
            "name": self.name,
            "slots": self.slots,
            "setpoints": dict(self.setpoints),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Ricostruisce il template dallo Store."""
        return cls(
            id=data["id"],
            name=data["name"],
            slots=data["slots"],
            setpoints=_setpoints(data.get("setpoints")),
        )


@dataclass(slots=True)
class WeekTemplate:
    """Settimana tipo: per ogni giorno (0 = lunedì) l'id di un day template."""

    id: str
    name: str
    days: dict[int, str] = field(default_factory=dict)
    setpoints: dict[str, float] = field(default_factory=dict)

    def day_template_id(self, weekday: int) -> str | None:
        """Id del day template associato al giorno, se assegnato."""
        return self.days.get(weekday)

    def to_dict(self) -> dict[str, Any]:
        """Serializza la settimana; le chiavi JSON devono essere stringhe."""
        return {
            "id": self.id,
            "name": self.name,
            "days": {str(day): template for day, template in self.days.items()},
            "setpoints": dict(self.setpoints),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Ricostruisce la settimana dallo Store."""
        return cls(
            id=data["id"],
            name=data["name"],
            days={int(day): template for day, template in data.get("days", {}).items()},
            setpoints=_setpoints(data.get("setpoints")),
        )


@dataclass(slots=True)
class Scenario:
    """Configurazione delle zone: a ciascuna la sua settimana tipo.

    Uno scenario *è* la mappa zona → settimana tipo. Cambiare scenario è
    l'unico gesto che riprogramma tutto l'impianto in una volta, ed è il motivo
    per cui l'assegnazione sta qui e non sulla zona: una zona non può seguire
    due settimane diverse nello stesso scenario, ma deve poterne seguire una
    diversa in ciascuno.

    Una zona assente dalla mappa non è programmata in questo scenario: nessun
    livello, nessun setpoint scritto.
    """

    id: str
    name: str
    zones: dict[str, str] = field(default_factory=dict)
    setpoints: dict[str, float] = field(default_factory=dict)

    def week_template_for(self, zone_id: str) -> str | None:
        """Settimana tipo assegnata alla zona in questo scenario."""
        return self.zones.get(zone_id)

    def to_dict(self) -> dict[str, Any]:
        """Serializza lo scenario."""
        return {
            "id": self.id,
            "name": self.name,
            "zones": dict(self.zones),
            "setpoints": dict(self.setpoints),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Ricostruisce lo scenario dallo Store."""
        return cls(
            id=data["id"],
            name=data["name"],
            zones=dict(data.get("zones", {})),
            setpoints=_setpoints(data.get("setpoints")),
        )


@dataclass(slots=True)
class Zone:
    """Zona termica: l'identità di un ambiente e le sue temperature proprie.

    La zona non sa quale programma segue — glielo assegna lo scenario attivo.
    Quello che le appartiene sono i gradi: `setpoints` è la tabella con cui un
    ambiente dice "io la bassa la voglio a 18", indipendentemente da quale
    scenario sia in corso.
    """

    id: str
    name: str
    setpoints: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serializza la zona."""
        return {"id": self.id, "name": self.name, "setpoints": dict(self.setpoints)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Ricostruisce la zona dallo Store."""
        return cls(
            id=data["id"],
            name=data["name"],
            setpoints=_setpoints(data.get("setpoints")),
        )


@dataclass(slots=True)
class Override:
    """Scostamento temporaneo dal programma per una zona.

    `source` distingue chi lo ha prodotto (noi, un'app esterna, la manopola
    fisica) perché i tre casi si trattano in modo diverso; `policy` e
    `expires_at` descrivono quando decade.

    `scenario_id` e `level` sono la memoria di com'era il mondo quando
    l'override è nato: le policy che scadono su un *cambiamento* — di scenario,
    di fascia — non hanno altro modo di accorgersi che il cambiamento è
    avvenuto. `level` può essere legittimamente `None`: lo slot che eredita non
    impone nessuna fascia, ed è uno stato da cui si può comunque uscire.
    """

    zone_id: str
    temperature: float
    source: str = OVERRIDE_SOURCE_HA
    policy: str = POLICY_NEXT_SLOT
    created_at: datetime | None = None
    expires_at: datetime | None = None
    scenario_id: str | None = None
    level: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serializza l'override; i datetime diventano stringhe ISO."""
        return {
            "zone_id": self.zone_id,
            "temperature": self.temperature,
            "source": self.source,
            "policy": self.policy,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "scenario_id": self.scenario_id,
            "level": self.level,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Ricostruisce l'override dallo Store."""
        return cls(
            zone_id=data["zone_id"],
            temperature=data["temperature"],
            source=data.get("source", OVERRIDE_SOURCE_HA),
            policy=data.get("policy", POLICY_NEXT_SLOT),
            created_at=_parse_dt(data.get("created_at")),
            expires_at=_parse_dt(data.get("expires_at")),
            scenario_id=data.get("scenario_id"),
            level=data.get("level"),
        )


def _parse_dt(value: str | None) -> datetime | None:
    """Converte una stringa ISO in datetime, tollerando valori assenti."""
    return datetime.fromisoformat(value) if value else None


@dataclass(slots=True)
class CthaData:
    """Radice del modello: tutto ciò che CTHA persiste."""

    levels: dict[str, TemperatureLevel] = field(default_factory=dict)
    global_setpoints: dict[str, float] = field(default_factory=dict)
    day_templates: dict[str, DayTemplate] = field(default_factory=dict)
    week_templates: dict[str, WeekTemplate] = field(default_factory=dict)
    scenarios: dict[str, Scenario] = field(default_factory=dict)
    zones: dict[str, Zone] = field(default_factory=dict)
    overrides: dict[str, Override] = field(default_factory=dict)
    active_scenario: str = DEFAULT_SCENARIO_ID

    @classmethod
    def default(cls) -> Self:
        """Costruisce un modello minimo ma già funzionante al primo avvio."""
        levels = {
            level_id: TemperatureLevel(level_id, name, char, color)
            for level_id, name, char, color, _ in DEFAULT_LEVELS
        }
        day = DayTemplate(
            id=DEFAULT_DAY_TEMPLATE_ID, name="Giornata tipo", slots=DEFAULT_DAY_SLOTS
        )
        week = WeekTemplate(
            id=DEFAULT_WEEK_TEMPLATE_ID,
            name="Settimana tipo",
            days={weekday: DEFAULT_DAY_TEMPLATE_ID for weekday in range(7)},
        )
        # Nessuna zona ancora: le zone nascono con le config entry, e sono le
        # entry a farsi assegnare una settimana tipo negli scenari esistenti.
        scenario = Scenario(id=DEFAULT_SCENARIO_ID, name="Normale")
        return cls(
            levels=levels,
            global_setpoints={
                level_id: setpoint for level_id, _, _, _, setpoint in DEFAULT_LEVELS
            },
            day_templates={day.id: day},
            week_templates={week.id: week},
            scenarios={scenario.id: scenario},
        )

    def active(self) -> Scenario | None:
        """Scenario attivo, se ancora esistente."""
        return self.scenarios.get(self.active_scenario)

    def level_for_char(self, char: str | None) -> str | None:
        """Id del livello rappresentato da un carattere del day template.

        Restituisce `None` anche per un carattere orfano: un livello eliminato
        mentre qualche template lo citava ancora non deve mandare in errore la
        risoluzione, deve solo smettere di imporre un livello.
        """
        if char is None:
            return None
        return next(
            (level.id for level in self.levels.values() if level.char == char), None
        )

    def level_at(self, template: DayTemplate, slot: int) -> str | None:
        """Livello imposto da uno slot di una giornata tipo, se ne impone uno."""
        return self.level_for_char(template.char_at(slot))

    def to_dict(self) -> dict[str, Any]:
        """Serializza l'intero modello per lo Store."""
        return {
            "levels": {k: v.to_dict() for k, v in self.levels.items()},
            "global_setpoints": dict(self.global_setpoints),
            "day_templates": {k: v.to_dict() for k, v in self.day_templates.items()},
            "week_templates": {k: v.to_dict() for k, v in self.week_templates.items()},
            "scenarios": {k: v.to_dict() for k, v in self.scenarios.items()},
            "zones": {k: v.to_dict() for k, v in self.zones.items()},
            "overrides": {k: v.to_dict() for k, v in self.overrides.items()},
            "active_scenario": self.active_scenario,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Ricostruisce il modello dallo Store."""
        return cls(
            levels={
                k: TemperatureLevel.from_dict(v)
                for k, v in data.get("levels", {}).items()
            },
            global_setpoints=_setpoints(data.get("global_setpoints")),
            day_templates={
                k: DayTemplate.from_dict(v)
                for k, v in data.get("day_templates", {}).items()
            },
            week_templates={
                k: WeekTemplate.from_dict(v)
                for k, v in data.get("week_templates", {}).items()
            },
            scenarios={
                k: Scenario.from_dict(v) for k, v in data.get("scenarios", {}).items()
            },
            zones={k: Zone.from_dict(v) for k, v in data.get("zones", {}).items()},
            overrides={
                k: Override.from_dict(v) for k, v in data.get("overrides", {}).items()
            },
            active_scenario=data.get("active_scenario", DEFAULT_SCENARIO_ID),
        )
