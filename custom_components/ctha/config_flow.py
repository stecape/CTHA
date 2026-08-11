"""Config flow e options flow per CTHA."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_COLD_TOLERANCE,
    CONF_HEATER,
    CONF_HOT_TOLERANCE,
    CONF_SENSOR,
    DEFAULT_COLD_TOLERANCE,
    DEFAULT_HOT_TOLERANCE,
    DOMAIN,
)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME, default="Cronotermostato"): selector.TextSelector(),
        vol.Required(CONF_SENSOR): selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor", device_class="temperature")
        ),
        vol.Required(CONF_HEATER): selector.EntitySelector(
            selector.EntitySelectorConfig(
                domain=["switch", "input_boolean", "climate"]
            )
        ),
    }
)


def _options_schema(defaults: dict[str, Any]) -> vol.Schema:
    """Schema delle opzioni, precompilato con i valori correnti."""
    return vol.Schema(
        {
            vol.Required(
                CONF_COLD_TOLERANCE,
                default=defaults.get(CONF_COLD_TOLERANCE, DEFAULT_COLD_TOLERANCE),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.1, max=5, step=0.1, unit_of_measurement="°C")
            ),
            vol.Required(
                CONF_HOT_TOLERANCE,
                default=defaults.get(CONF_HOT_TOLERANCE, DEFAULT_HOT_TOLERANCE),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(min=0.1, max=5, step=0.1, unit_of_measurement="°C")
            ),
        }
    )


class CthaConfigFlow(ConfigFlow, domain=DOMAIN):
    """Gestisce la configurazione iniziale di un cronotermostato CTHA."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Primo (e unico) step: sensore di temperatura e attuatore."""
        if user_input is None:
            return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA)

        self._async_abort_entries_match({CONF_HEATER: user_input[CONF_HEATER]})
        return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> CthaOptionsFlow:
        """Restituisce l'options flow associato."""
        return CthaOptionsFlow()


class CthaOptionsFlow(OptionsFlow):
    """Permette di rivedere l'isteresi dopo la configurazione."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Mostra e salva le opzioni."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(dict(self.config_entry.options)),
        )
