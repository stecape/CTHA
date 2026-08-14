"""Migrazione dei dati persistiti fra versioni dello Store.

Funzioni pure da dizionario a dizionario, senza Home Assistant: lo Store
consegna il contenuto grezzo del file e si aspetta indietro la stessa cosa,
nella forma della versione corrente. Lavorare sui dizionari e non sul modello è
deliberato — il modello di oggi non sa più leggere quello di ieri, ed è proprio
questa la ragione per cui la migrazione esiste.
"""

from __future__ import annotations

from typing import Any

from .const import MAX_TEMP, MIN_TEMP

# I tre livelli fissi della versione 1, con i colori che il pannello dava loro.
# Diventano livelli come gli altri: stessi caratteri, così le giornate tipo già
# dipinte continuano a voler dire quello che volevano dire.
V1_LEVELS: tuple[tuple[str, str, str, str], ...] = (
    ("comfort", "Comfort", "c", "#e0703c"),
    ("eco", "Eco", "e", "#3f9d7c"),
    ("antifreeze", "Antigelo", "a", "#4a7fbf"),
)


def migrate_v1_to_v2(data: dict[str, Any]) -> dict[str, Any]:
    """Porta il modello della versione 1 alla forma della versione 2.

    Tre cambiamenti di sostanza:

    * i livelli diventano dati, e i tre di prima vengono ricreati tali e quali;
    * lo scenario non ha più *una* settimana tipo ma la mappa zona → settimana:
      quella dello scenario diventa il valore per tutte le zone, e la settimana
      propria di una zona ha la precedenza, che è ciò che significava;
    * gli offset diventano sovrascritture. Quello generale dello scenario si
      riscrive come temperature esplicite dello scenario; le eccezioni per zona
      non hanno un posto nella nuova gerarchia — una zona ha una tabella sola,
      valida in tutti gli scenari — e vanno perse.
    """
    levels = {
        level_id: {"id": level_id, "name": name, "char": char, "color": color}
        for level_id, name, char, color in V1_LEVELS
    }
    global_setpoints = {
        level: float(value)
        for level, value in (data.get("global_setpoints") or {}).items()
        if value is not None
    }

    zones = {
        zone_id: {
            "id": zone.get("id", zone_id),
            "name": zone.get("name", zone_id),
            "setpoints": _clean(zone.get("setpoints")),
        }
        for zone_id, zone in (data.get("zones") or {}).items()
    }
    zone_weeks = {
        zone_id: zone.get("week_template")
        for zone_id, zone in (data.get("zones") or {}).items()
    }

    scenarios = {
        scenario_id: _migrate_scenario(scenario, scenario_id, zone_weeks, global_setpoints)
        for scenario_id, scenario in (data.get("scenarios") or {}).items()
    }

    return {
        "levels": levels,
        "global_setpoints": global_setpoints,
        "day_templates": {
            template_id: {**template, "setpoints": {}}
            for template_id, template in (data.get("day_templates") or {}).items()
        },
        "week_templates": {
            template_id: {**template, "setpoints": {}}
            for template_id, template in (data.get("week_templates") or {}).items()
        },
        "scenarios": scenarios,
        "zones": zones,
        "overrides": dict(data.get("overrides") or {}),
        "active_scenario": data.get("active_scenario", "default"),
    }


def _migrate_scenario(
    scenario: dict[str, Any],
    scenario_id: str,
    zone_weeks: dict[str, str | None],
    global_setpoints: dict[str, float],
) -> dict[str, Any]:
    """Uno scenario della versione 1, riscritto come configurazione delle zone."""
    default_week = scenario.get("week_template")
    zones = {
        zone_id: own or default_week
        for zone_id, own in zone_weeks.items()
        if (own or default_week)
    }

    offset = float(scenario.get("offset") or 0.0)
    setpoints = (
        {
            level: _clamp(value + offset)
            for level, value in global_setpoints.items()
        }
        if offset
        else {}
    )

    return {
        "id": scenario.get("id", scenario_id),
        "name": scenario.get("name", scenario_id),
        "zones": zones,
        "setpoints": setpoints,
    }


def _clean(setpoints: Any) -> dict[str, float]:
    """Tabella di setpoint senza i `null`, che nella v2 sono semplici assenze."""
    if not isinstance(setpoints, dict):
        return {}
    return {
        level: float(value) for level, value in setpoints.items() if value is not None
    }


def _clamp(temperature: float) -> float:
    """Un offset applicato al globale può uscire di scala: qui rientra."""
    return min(MAX_TEMP, max(MIN_TEMP, temperature))
