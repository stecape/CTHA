"""API websocket per il pannello: lettura del modello e push degli aggiornamenti.

Il pannello legge da qui e scrive tramite i servizi: la validazione e
l'integrità referenziale stanno già lì, e duplicarle in comandi websocket
significherebbe mantenerne due copie. Quindi questo modulo è di sola lettura.

Lo snapshot unisce due cose che il frontend non può ricavare da solo:

* il **modello** persistito, così com'è nello Store — template, scenari, zone,
  setpoint, override;
* il **runtime**, cioè la risoluzione corrente di ogni zona con la sua
  provenienza, che è il risultato di `resolve_setpoint` e non è deducibile dal
  solo modello senza reimplementare la risoluzione in TypeScript.
"""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    INHERIT_CHAR,
    MAX_TEMP,
    MIN_TEMP,
    OVERRIDE_POLICIES,
    SETPOINT_LAYERS,
    SLOT_MINUTES,
    SLOTS_PER_DAY,
    TEMP_STEP,
    WS_GET,
    WS_SUBSCRIBE,
)
from .coordinator import CthaCoordinator


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    """Registra i comandi websocket del dominio."""
    websocket_api.async_register_command(hass, websocket_get)
    websocket_api.async_register_command(hass, websocket_subscribe)


@websocket_api.websocket_command({vol.Required("type"): WS_GET})
@callback
def websocket_get(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Restituisce lo snapshot corrente, una volta sola."""
    connection.send_result(msg["id"], _snapshot(_coordinator(hass)))


@websocket_api.websocket_command({vol.Required("type"): WS_SUBSCRIBE})
@callback
def websocket_subscribe(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Iscrive il pannello agli aggiornamenti del coordinator.

    Il primo evento parte subito dopo l'ack: chi si iscrive non deve anche
    chiedere lo stato iniziale per poter disegnare qualcosa.
    """
    coordinator = _coordinator(hass)

    @callback
    def _forward() -> None:
        connection.send_message(
            websocket_api.event_message(msg["id"], _snapshot(coordinator))
        )

    connection.subscriptions[msg["id"]] = coordinator.async_add_listener(_forward)
    connection.send_result(msg["id"])
    _forward()


def _snapshot(coordinator: CthaCoordinator) -> dict[str, Any]:
    """Modello persistito, risoluzione corrente delle zone e costanti utili."""
    return {
        "program": coordinator.data.to_dict(),
        "runtime": {
            zone_id: _zone_runtime(coordinator, zone_id)
            for zone_id in coordinator.data.zones
        },
        "meta": {
            # La gerarchia dei setpoint viaggia col resto: il pannello deve
            # mostrare *quale* livello ha deciso un valore, e l'ordine è uno
            # solo — quello di `resolve.py`.
            "layers": list(SETPOINT_LAYERS),
            "policies": list(OVERRIDE_POLICIES),
            "slots_per_day": SLOTS_PER_DAY,
            "slot_minutes": SLOT_MINUTES,
            "inherit_char": INHERIT_CHAR,
            "min_temp": MIN_TEMP,
            "max_temp": MAX_TEMP,
            "temp_step": TEMP_STEP,
        },
    }


def _zone_runtime(coordinator: CthaCoordinator, zone_id: str) -> dict[str, Any]:
    """Cosa sta tenendo la zona in questo momento, e da dove viene il valore."""
    resolution = coordinator.resolution_for(zone_id)
    chain = coordinator.chain_for(zone_id)
    override = coordinator.overrides.active(zone_id, dt_util.now())
    return {
        "entity_id": coordinator.entity_ids.get(zone_id),
        "level": resolution.level,
        "source": resolution.source,
        "scheduled": resolution.temperature,
        "target": coordinator.target_for(zone_id),
        "week_template": chain.week.id if chain.week else None,
        "day_template": chain.day.id if chain.day else None,
        "slot": chain.slot,
        "override": override.to_dict() if override is not None else None,
    }


def _coordinator(hass: HomeAssistant) -> CthaCoordinator:
    """Recupera il coordinator condiviso."""
    return hass.data[DOMAIN]["coordinator"]
