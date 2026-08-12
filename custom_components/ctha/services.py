"""Servizi di CTHA: override e modifica del programma.

Sono la superficie di scrittura del componente. Esistono prima del frontend
perché senza di essi il modello si può solo leggere: creare uno scenario o
ritoccare una giornata tipo richiederebbe già la UI. Sono anche l'API su cui la
griglia di programmazione si appoggerà, ed è la ragione per cui `paint_slots`
prende un intervallo e non uno slot.

Ogni servizio è un guscio sottile: valida gli argomenti, chiama la funzione
pura di `program.py` tramite `coordinator.async_edit` e traduce gli errori del
modello in errori mostrabili all'utente.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from typing import Any

import voluptuous as vol

from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv

from . import program
from .const import (
    ATTR_DAYS,
    ATTR_DURATION,
    ATTR_END_SLOT,
    ATTR_LEVEL,
    ATTR_NAME,
    ATTR_NEW_ID,
    ATTR_OFFSET,
    ATTR_POLICY,
    ATTR_SCENARIO_ID,
    ATTR_SLOTS,
    ATTR_START_SLOT,
    ATTR_TEMPLATE_ID,
    ATTR_WEEK_TEMPLATE,
    ATTR_ZONE_ID,
    ATTR_ZONE_OFFSETS,
    DAYS_PER_WEEK,
    DOMAIN,
    LEVELS,
    MAX_TEMP,
    MIN_TEMP,
    OVERRIDE_POLICIES,
    POLICY_NEXT_SLOT,
    SERVICE_ACTIVATE_SCENARIO,
    SERVICE_CLEAR_OVERRIDE,
    SERVICE_DELETE_DAY_TEMPLATE,
    SERVICE_DELETE_SCENARIO,
    SERVICE_DELETE_WEEK_TEMPLATE,
    SERVICE_DUPLICATE_DAY_TEMPLATE,
    SERVICE_PAINT_SLOTS,
    SERVICE_SET_DAY_TEMPLATE,
    SERVICE_SET_OVERRIDE,
    SERVICE_SET_SCENARIO,
    SERVICE_SET_SETPOINT,
    SERVICE_SET_WEEK_TEMPLATE,
    SERVICE_SET_ZONE_WEEK_TEMPLATE,
    SLOTS_PER_DAY,
)
from .coordinator import CthaCoordinator

_SLOT = vol.All(vol.Coerce(int), vol.Range(min=0, max=SLOTS_PER_DAY - 1))
_WEEKDAY = vol.All(vol.Coerce(int), vol.Range(min=0, max=DAYS_PER_WEEK - 1))
_TEMPERATURE = vol.All(vol.Coerce(float), vol.Range(min=MIN_TEMP, max=MAX_TEMP))

SET_OVERRIDE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ZONE_ID): cv.string,
        vol.Required(ATTR_TEMPERATURE): _TEMPERATURE,
        vol.Optional(ATTR_POLICY, default=POLICY_NEXT_SLOT): vol.In(OVERRIDE_POLICIES),
        vol.Optional(ATTR_DURATION): cv.time_period,
    }
)

CLEAR_OVERRIDE_SCHEMA = vol.Schema({vol.Required(ATTR_ZONE_ID): cv.string})

SET_DAY_TEMPLATE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TEMPLATE_ID): cv.string,
        vol.Optional(ATTR_NAME): cv.string,
        vol.Optional(ATTR_SLOTS): vol.All(
            cv.string, vol.Length(min=SLOTS_PER_DAY, max=SLOTS_PER_DAY)
        ),
    }
)

PAINT_SLOTS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TEMPLATE_ID): cv.string,
        vol.Required(ATTR_START_SLOT): _SLOT,
        vol.Optional(ATTR_END_SLOT): _SLOT,
        # Nessun livello significa "dipingi l'ereditarietà dal globale".
        vol.Optional(ATTR_LEVEL): vol.Any(None, vol.In(LEVELS)),
    }
)

DUPLICATE_DAY_TEMPLATE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TEMPLATE_ID): cv.string,
        vol.Optional(ATTR_NEW_ID): cv.string,
        vol.Optional(ATTR_NAME): cv.string,
        vol.Optional(ATTR_WEEK_TEMPLATE): cv.string,
        vol.Optional(ATTR_DAYS): vol.All(cv.ensure_list, [_WEEKDAY]),
    }
)

DELETE_DAY_TEMPLATE_SCHEMA = vol.Schema({vol.Required(ATTR_TEMPLATE_ID): cv.string})

SET_WEEK_TEMPLATE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TEMPLATE_ID): cv.string,
        vol.Optional(ATTR_NAME): cv.string,
        # Valore nullo: il giorno resta scoperto.
        vol.Optional(ATTR_DAYS): vol.Schema({_WEEKDAY: vol.Any(None, cv.string)}),
    }
)

DELETE_WEEK_TEMPLATE_SCHEMA = vol.Schema({vol.Required(ATTR_TEMPLATE_ID): cv.string})

SET_SCENARIO_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_SCENARIO_ID): cv.string,
        vol.Optional(ATTR_NAME): cv.string,
        vol.Optional(ATTR_WEEK_TEMPLATE): cv.string,
        vol.Optional(ATTR_OFFSET): vol.Coerce(float),
        # Valore nullo: la zona torna all'offset generale dello scenario.
        vol.Optional(ATTR_ZONE_OFFSETS): vol.Schema(
            {cv.string: vol.Any(None, vol.Coerce(float))}
        ),
    }
)

DELETE_SCENARIO_SCHEMA = vol.Schema({vol.Required(ATTR_SCENARIO_ID): cv.string})

ACTIVATE_SCENARIO_SCHEMA = vol.Schema({vol.Required(ATTR_SCENARIO_ID): cv.string})

SET_SETPOINT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_LEVEL): vol.In(LEVELS),
        # Assente o nullo su una zona: torna a ereditare dal globale.
        vol.Optional(ATTR_TEMPERATURE): vol.Any(None, _TEMPERATURE),
        vol.Optional(ATTR_ZONE_ID): cv.string,
    }
)

SET_ZONE_WEEK_TEMPLATE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_ZONE_ID): cv.string,
        # Assente o nullo: la zona torna a seguire lo scenario.
        vol.Optional(ATTR_TEMPLATE_ID): vol.Any(None, cv.string),
    }
)


@callback
def async_register_services(hass: HomeAssistant) -> None:
    """Registra i servizi una sola volta, alla prima config entry."""
    if hass.services.has_service(DOMAIN, SERVICE_SET_OVERRIDE):
        return

    # --- Override -----------------------------------------------------------

    async def _async_set_override(call: ServiceCall) -> None:
        """Imposta un override sulla zona indicata."""
        await _coordinator(hass).async_set_override(
            call.data[ATTR_ZONE_ID],
            call.data[ATTR_TEMPERATURE],
            policy=call.data[ATTR_POLICY],
            duration=call.data.get(ATTR_DURATION),
        )

    async def _async_clear_override(call: ServiceCall) -> None:
        """Rimuove l'override dalla zona indicata."""
        await _coordinator(hass).async_clear_override(call.data[ATTR_ZONE_ID])

    # --- Giornate tipo ------------------------------------------------------

    async def _async_set_day_template(call: ServiceCall) -> None:
        """Crea o aggiorna una giornata tipo."""
        await _edit(
            hass,
            partial(
                program.set_day_template,
                template_id=call.data[ATTR_TEMPLATE_ID],
                name=call.data.get(ATTR_NAME),
                slots=call.data.get(ATTR_SLOTS),
            ),
        )

    async def _async_paint_slots(call: ServiceCall) -> None:
        """Dipinge un livello su un intervallo di slot."""
        await _edit(
            hass,
            partial(
                program.paint_day_template,
                template_id=call.data[ATTR_TEMPLATE_ID],
                level=call.data.get(ATTR_LEVEL),
                start_slot=call.data[ATTR_START_SLOT],
                end_slot=call.data.get(ATTR_END_SLOT),
            ),
        )

    async def _async_duplicate_day_template(call: ServiceCall) -> ServiceResponse:
        """Duplica una giornata tipo e restituisce l'id della copia."""
        copy = await _edit(
            hass,
            partial(
                program.duplicate_day_template,
                template_id=call.data[ATTR_TEMPLATE_ID],
                new_id=call.data.get(ATTR_NEW_ID),
                name=call.data.get(ATTR_NAME),
                week_template=call.data.get(ATTR_WEEK_TEMPLATE),
                days=call.data.get(ATTR_DAYS),
            ),
        )
        return {"template_id": copy.id, "name": copy.name, "slots": copy.slots}

    async def _async_delete_day_template(call: ServiceCall) -> None:
        """Elimina una giornata tipo non più usata."""
        await _edit(
            hass,
            partial(
                program.delete_day_template, template_id=call.data[ATTR_TEMPLATE_ID]
            ),
        )

    # --- Settimane tipo -----------------------------------------------------

    async def _async_set_week_template(call: ServiceCall) -> None:
        """Crea o aggiorna una settimana tipo."""
        await _edit(
            hass,
            partial(
                program.set_week_template,
                template_id=call.data[ATTR_TEMPLATE_ID],
                name=call.data.get(ATTR_NAME),
                days=call.data.get(ATTR_DAYS),
            ),
        )

    async def _async_delete_week_template(call: ServiceCall) -> None:
        """Elimina una settimana tipo non più usata."""
        await _edit(
            hass,
            partial(
                program.delete_week_template, template_id=call.data[ATTR_TEMPLATE_ID]
            ),
        )

    # --- Scenari ------------------------------------------------------------

    async def _async_set_scenario(call: ServiceCall) -> None:
        """Crea o aggiorna uno scenario."""
        await _edit(
            hass,
            partial(
                program.set_scenario,
                scenario_id=call.data[ATTR_SCENARIO_ID],
                name=call.data.get(ATTR_NAME),
                week_template=call.data.get(ATTR_WEEK_TEMPLATE),
                offset=call.data.get(ATTR_OFFSET),
                zone_offsets=call.data.get(ATTR_ZONE_OFFSETS),
            ),
        )

    async def _async_delete_scenario(call: ServiceCall) -> None:
        """Elimina uno scenario non attivo."""
        await _edit(
            hass,
            partial(program.delete_scenario, scenario_id=call.data[ATTR_SCENARIO_ID]),
        )

    async def _async_activate_scenario(call: ServiceCall) -> None:
        """Rende attivo uno scenario, facendo decadere gli override legati al precedente."""
        try:
            await _coordinator(hass).async_set_active_scenario(
                call.data[ATTR_SCENARIO_ID]
            )
        except program.ProgramError as err:
            raise ServiceValidationError(str(err)) from err

    # --- Setpoint e zone ----------------------------------------------------

    async def _async_set_setpoint(call: ServiceCall) -> None:
        """Imposta un setpoint globale o di zona."""
        await _edit(
            hass,
            partial(
                program.set_setpoint,
                level=call.data[ATTR_LEVEL],
                temperature=call.data.get(ATTR_TEMPERATURE),
                zone_id=call.data.get(ATTR_ZONE_ID),
            ),
        )

    async def _async_set_zone_week_template(call: ServiceCall) -> None:
        """Dà a una zona un programma proprio, o la riporta a quello di scenario."""
        await _edit(
            hass,
            partial(
                program.set_zone_week_template,
                zone_id=call.data[ATTR_ZONE_ID],
                template_id=call.data.get(ATTR_TEMPLATE_ID),
            ),
        )

    _register(hass, SERVICE_SET_OVERRIDE, _async_set_override, SET_OVERRIDE_SCHEMA)
    _register(
        hass, SERVICE_CLEAR_OVERRIDE, _async_clear_override, CLEAR_OVERRIDE_SCHEMA
    )
    _register(
        hass, SERVICE_SET_DAY_TEMPLATE, _async_set_day_template, SET_DAY_TEMPLATE_SCHEMA
    )
    _register(hass, SERVICE_PAINT_SLOTS, _async_paint_slots, PAINT_SLOTS_SCHEMA)
    _register(
        hass,
        SERVICE_DUPLICATE_DAY_TEMPLATE,
        _async_duplicate_day_template,
        DUPLICATE_DAY_TEMPLATE_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    _register(
        hass,
        SERVICE_DELETE_DAY_TEMPLATE,
        _async_delete_day_template,
        DELETE_DAY_TEMPLATE_SCHEMA,
    )
    _register(
        hass,
        SERVICE_SET_WEEK_TEMPLATE,
        _async_set_week_template,
        SET_WEEK_TEMPLATE_SCHEMA,
    )
    _register(
        hass,
        SERVICE_DELETE_WEEK_TEMPLATE,
        _async_delete_week_template,
        DELETE_WEEK_TEMPLATE_SCHEMA,
    )
    _register(hass, SERVICE_SET_SCENARIO, _async_set_scenario, SET_SCENARIO_SCHEMA)
    _register(
        hass, SERVICE_DELETE_SCENARIO, _async_delete_scenario, DELETE_SCENARIO_SCHEMA
    )
    _register(
        hass,
        SERVICE_ACTIVATE_SCENARIO,
        _async_activate_scenario,
        ACTIVATE_SCENARIO_SCHEMA,
    )
    _register(hass, SERVICE_SET_SETPOINT, _async_set_setpoint, SET_SETPOINT_SCHEMA)
    _register(
        hass,
        SERVICE_SET_ZONE_WEEK_TEMPLATE,
        _async_set_zone_week_template,
        SET_ZONE_WEEK_TEMPLATE_SCHEMA,
    )


@callback
def async_unregister_services(hass: HomeAssistant) -> None:
    """Rimuove i servizi quando l'ultima config entry viene scaricata."""
    for service in (
        SERVICE_SET_OVERRIDE,
        SERVICE_CLEAR_OVERRIDE,
        SERVICE_SET_DAY_TEMPLATE,
        SERVICE_PAINT_SLOTS,
        SERVICE_DUPLICATE_DAY_TEMPLATE,
        SERVICE_DELETE_DAY_TEMPLATE,
        SERVICE_SET_WEEK_TEMPLATE,
        SERVICE_DELETE_WEEK_TEMPLATE,
        SERVICE_SET_SCENARIO,
        SERVICE_DELETE_SCENARIO,
        SERVICE_ACTIVATE_SCENARIO,
        SERVICE_SET_SETPOINT,
        SERVICE_SET_ZONE_WEEK_TEMPLATE,
    ):
        hass.services.async_remove(DOMAIN, service)


@callback
def _register(
    hass: HomeAssistant,
    service: str,
    handler: Callable[[ServiceCall], Any],
    schema: vol.Schema,
    supports_response: SupportsResponse = SupportsResponse.NONE,
) -> None:
    """Registra un servizio del dominio con la sua firma."""
    hass.services.async_register(
        DOMAIN, service, handler, schema, supports_response=supports_response
    )


async def _edit(hass: HomeAssistant, edit: Callable[[Any], Any]) -> Any:
    """Esegue una modifica al programma traducendone gli errori per l'utente.

    `ProgramError` non è un bug: è l'utente che ha chiesto qualcosa di non
    ammissibile (un template inesistente, una cancellazione che spezzerebbe il
    programma). Va mostrato come errore di validazione, non come traccia di
    stack nel log.
    """
    try:
        return await _coordinator(hass).async_edit(edit)
    except program.ProgramError as err:
        raise ServiceValidationError(str(err)) from err


def _coordinator(hass: HomeAssistant) -> CthaCoordinator:
    """Recupera il coordinator condiviso."""
    return hass.data[DOMAIN]["coordinator"]
