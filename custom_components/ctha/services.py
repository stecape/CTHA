"""Servizi di CTHA per pilotare gli override dalle automazioni.

Sono esposti prima del frontend proprio perché servono a coprire il periodo in
cui l'interfaccia di programmazione non esiste ancora.
"""

from __future__ import annotations

import voluptuous as vol

from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_DURATION,
    ATTR_POLICY,
    ATTR_ZONE_ID,
    DOMAIN,
    MAX_TEMP,
    MIN_TEMP,
    OVERRIDE_POLICIES,
    POLICY_NEXT_SLOT,
    SERVICE_CLEAR_OVERRIDE,
    SERVICE_SET_OVERRIDE,
)
from .coordinator import CthaCoordinator

SET_OVERRIDE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ZONE_ID): cv.string,
        vol.Required(ATTR_TEMPERATURE): vol.All(
            vol.Coerce(float), vol.Range(min=MIN_TEMP, max=MAX_TEMP)
        ),
        vol.Optional(ATTR_POLICY, default=POLICY_NEXT_SLOT): vol.In(OVERRIDE_POLICIES),
        vol.Optional(ATTR_DURATION): cv.time_period,
    }
)

CLEAR_OVERRIDE_SCHEMA = vol.Schema({vol.Required(ATTR_ZONE_ID): cv.string})


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Registra i servizi una sola volta, alla prima config entry."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_OVERRIDE):
        return

    async def _async_set_override(call: ServiceCall) -> None:
        """Imposta un override sulla zona indicata."""
        coordinator = _coordinator(hass)
        await coordinator.async_set_override(
            call.data[ATTR_ZONE_ID],
            call.data[ATTR_TEMPERATURE],
            policy=call.data[ATTR_POLICY],
            duration=call.data.get(ATTR_DURATION),
        )

    async def _async_clear_override(call: ServiceCall) -> None:
        """Rimuove l'override dalla zona indicata."""
        coordinator = _coordinator(hass)
        await coordinator.async_clear_override(call.data[ATTR_ZONE_ID])

    hass.services.async_register(
        DOMAIN, SERVICE_SET_OVERRIDE, _async_set_override, SET_OVERRIDE_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CLEAR_OVERRIDE, _async_clear_override, CLEAR_OVERRIDE_SCHEMA
    )


@callback
def async_unregister_services(hass: HomeAssistant) -> None:
    """Rimuove i servizi quando l'ultima config entry viene scaricata."""
    hass.services.async_remove(DOMAIN, SERVICE_SET_OVERRIDE)
    hass.services.async_remove(DOMAIN, SERVICE_CLEAR_OVERRIDE)


def _coordinator(hass: HomeAssistant) -> CthaCoordinator:
    """Recupera il coordinator condiviso."""
    return hass.data[DOMAIN]["coordinator"]
