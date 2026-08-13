"""Config flow per CTHA: una zona è un termostato già esistente."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components.climate import DOMAIN as CLIMATE_DOMAIN
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_NAME
from homeassistant.helpers import selector

from .const import CONF_TARGET, DOMAIN

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME, default="Zona"): selector.TextSelector(),
        vol.Required(CONF_TARGET): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=CLIMATE_DOMAIN)
        ),
    }
)


class CthaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Configura una zona CTHA sopra a un termostato esistente.

    Non si chiedono sensore e attuatore: il termostato di zona (per BTicino
    l'F430/4 esposto da MyHOME) misura già la temperatura e comanda già la
    valvola. Quello che manca, e che CTHA aggiunge, è *quale setpoint tenere e
    quando*.
    """

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Primo e unico step: nome della zona e termostato da pilotare."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA)

        # Una zona per termostato: due entry sullo stesso non farebbero altro
        # che scrivere setpoint diversi sullo stesso indirizzo del bus.
        self._async_abort_entries_match({CONF_TARGET: user_input[CONF_TARGET]})
        return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)
