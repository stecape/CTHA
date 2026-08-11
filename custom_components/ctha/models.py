"""Modello dati di CTHA, serializzabile nello Store di Home Assistant.

Il modello è basato su riferimenti: scenari, week template e day template si
citano per identificatore anziché duplicare i dati, così un template può essere
riusato da più giorni e da più scenari. Il valore `None` non è un "non so": è
la rappresentazione esplicita dell'ereditarietà dal livello superiore.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Self

from .const import (
    DEFAULT_DAY_SLOTS,
    DEFAULT_DAY_TEMPLATE_ID,
    DEFAULT_GLOBAL_SETPOINTS,
    DEFAULT_SCENARIO_ID,
    DEFAULT_WEEK_TEMPLATE_ID,
    INHERIT_CHAR,
    LEVEL_BY_CHAR,
    OVERRIDE_SOURCE_HA,
    POLICY_NEXT_SLOT,
    SLOTS_PER_DAY,
)


class InvalidTemplateError(ValueError):
    """Un template non rispetta il formato atteso."""


def validate_slots(slots: str) -> str:
    """Verifica che una stringa di slot sia lunga 48 e usi caratteri noti."""
    if len(slots) != SLOTS_PER_DAY:
        raise InvalidTemplateError(
            f"Un day template richiede {SLOTS_PER_DAY} caratteri, ricevuti {len(slots)}"
        )
    if unknown := set(slots) - set(LEVEL_BY_CHAR) - {INHERIT_CHAR}:
        raise InvalidTemplateError(
            f"Caratteri non validi nel day template: {sorted(unknown)}"
        )
    return slots


@dataclass(slots=True)
class DayTemplate:
    """Giornata tipo: 48 slot da 30 minuti, un carattere per slot."""

    id: str
    name: str
    slots: str = DEFAULT_DAY_SLOTS

    def __post_init__(self) -> None:
        """Rifiuta subito i template malformati, prima che finiscano nello Store."""
        validate_slots(self.slots)

    def level_at(self, slot: int) -> str | None:
        """Livello dello slot indicato, o `None` se eredita dal globale."""
        char = self.slots[slot % SLOTS_PER_DAY]
        return LEVEL_BY_CHAR.get(char)

    def to_dict(self) -> dict[str, Any]:
        """Serializza il template."""
        return {"id": self.id, "name": self.name, "slots": self.slots}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Ricostruisce il template dallo Store."""
        return cls(id=data["id"], name=data["name"], slots=data["slots"])


@dataclass(slots=True)
class WeekTemplate:
    """Settimana tipo: per ogni giorno (0 = lunedì) l'id di un day template."""

    id: str
    name: str
    days: dict[int, str] = field(default_factory=dict)

    def day_template_id(self, weekday: int) -> str | None:
        """Id del day template associato al giorno, se assegnato."""
        return self.days.get(weekday)

    def to_dict(self) -> dict[str, Any]:
        """Serializza la settimana; le chiavi JSON devono essere stringhe."""
        return {
            "id": self.id,
            "name": self.name,
            "days": {str(day): template for day, template in self.days.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Ricostruisce la settimana dallo Store."""
        return cls(
            id=data["id"],
            name=data["name"],
            days={int(day): template for day, template in data.get("days", {}).items()},
        )


@dataclass(slots=True)
class Scenario:
    """Modalità di esercizio: una settimana tipo più offset termici.

    Lo scenario agisce solo sull'asse termico tramite `offsets`: non cambia il
    livello risolto per lo slot, ma sposta la temperatura che ne deriva.
    """

    id: str
    name: str
    week_template: str = DEFAULT_WEEK_TEMPLATE_ID
    offset: float = 0.0
    zone_offsets: dict[str, float] = field(default_factory=dict)

    def offset_for(self, zone_id: str) -> float:
        """Offset applicabile alla zona, con fallback su quello di scenario."""
        return self.zone_offsets.get(zone_id, self.offset)

    def to_dict(self) -> dict[str, Any]:
        """Serializza lo scenario."""
        return {
            "id": self.id,
            "name": self.name,
            "week_template": self.week_template,
            "offset": self.offset,
            "zone_offsets": dict(self.zone_offsets),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Ricostruisce lo scenario dallo Store."""
        return cls(
            id=data["id"],
            name=data["name"],
            week_template=data.get("week_template", DEFAULT_WEEK_TEMPLATE_ID),
            offset=data.get("offset", 0.0),
            zone_offsets=dict(data.get("zone_offsets", {})),
        )


@dataclass(slots=True)
class Zone:
    """Zona termica: setpoint propri (o ereditati) e week template opzionale.

    `setpoints` mappa livello -> temperatura; un livello assente, o mappato a
    `None`, eredita dal setpoint globale.
    """

    id: str
    name: str
    setpoints: dict[str, float | None] = field(default_factory=dict)
    week_template: str | None = None

    def setpoint_for(self, level: str) -> float | None:
        """Setpoint proprio della zona per il livello, se non eredita."""
        return self.setpoints.get(level)

    def to_dict(self) -> dict[str, Any]:
        """Serializza la zona."""
        return {
            "id": self.id,
            "name": self.name,
            "setpoints": dict(self.setpoints),
            "week_template": self.week_template,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Ricostruisce la zona dallo Store."""
        return cls(
            id=data["id"],
            name=data["name"],
            setpoints=dict(data.get("setpoints", {})),
            week_template=data.get("week_template"),
        )


@dataclass(slots=True)
class Override:
    """Scostamento temporaneo dal programma per una zona.

    `source` distingue chi lo ha prodotto (noi, un'app esterna, la manopola
    fisica) perché i tre casi si trattano in modo diverso; `policy` e
    `expires_at` descrivono quando decade.
    """

    zone_id: str
    temperature: float
    source: str = OVERRIDE_SOURCE_HA
    policy: str = POLICY_NEXT_SLOT
    created_at: datetime | None = None
    expires_at: datetime | None = None
    scenario_id: str | None = None

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
        )


def _parse_dt(value: str | None) -> datetime | None:
    """Converte una stringa ISO in datetime, tollerando valori assenti."""
    return datetime.fromisoformat(value) if value else None


@dataclass(slots=True)
class CthaData:
    """Radice del modello: tutto ciò che CTHA persiste."""

    global_setpoints: dict[str, float] = field(
        default_factory=lambda: dict(DEFAULT_GLOBAL_SETPOINTS)
    )
    day_templates: dict[str, DayTemplate] = field(default_factory=dict)
    week_templates: dict[str, WeekTemplate] = field(default_factory=dict)
    scenarios: dict[str, Scenario] = field(default_factory=dict)
    zones: dict[str, Zone] = field(default_factory=dict)
    overrides: dict[str, Override] = field(default_factory=dict)
    active_scenario: str = DEFAULT_SCENARIO_ID

    @classmethod
    def default(cls) -> Self:
        """Costruisce un modello minimo ma già funzionante al primo avvio."""
        day = DayTemplate(
            id=DEFAULT_DAY_TEMPLATE_ID, name="Giornata tipo", slots=DEFAULT_DAY_SLOTS
        )
        week = WeekTemplate(
            id=DEFAULT_WEEK_TEMPLATE_ID,
            name="Settimana tipo",
            days={weekday: DEFAULT_DAY_TEMPLATE_ID for weekday in range(7)},
        )
        scenario = Scenario(
            id=DEFAULT_SCENARIO_ID, name="Normale", week_template=week.id
        )
        return cls(
            day_templates={day.id: day},
            week_templates={week.id: week},
            scenarios={scenario.id: scenario},
        )

    def active(self) -> Scenario | None:
        """Scenario attivo, se ancora esistente."""
        return self.scenarios.get(self.active_scenario)

    def to_dict(self) -> dict[str, Any]:
        """Serializza l'intero modello per lo Store."""
        return {
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
            global_setpoints={
                **DEFAULT_GLOBAL_SETPOINTS,
                **data.get("global_setpoints", {}),
            },
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
