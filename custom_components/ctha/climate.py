"""Entità climate del cronotermostato CTHA."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    CONF_NAME,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_COLD_TOLERANCE,
    CONF_HEATER,
    CONF_HOT_TOLERANCE,
    CONF_SENSOR,
    DEFAULT_COLD_TOLERANCE,
    DEFAULT_HOT_TOLERANCE,
    DEFAULT_TEMP_ANTIFREEZE,
    DEFAULT_TEMP_COMFORT,
    DEFAULT_TEMP_ECO,
    DOMAIN,
    MAX_TEMP,
    MIN_TEMP,
    PRESET_ANTIFREEZE,
    PRESET_COMFORT,
    PRESET_ECO,
    TEMP_STEP,
)

_LOGGER = logging.getLogger(__name__)

PRESET_TEMPERATURES: dict[str, float] = {
    PRESET_COMFORT: DEFAULT_TEMP_COMFORT,
    PRESET_ECO: DEFAULT_TEMP_ECO,
    PRESET_ANTIFREEZE: DEFAULT_TEMP_ANTIFREEZE,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crea l'entità climate per la config entry."""
    async_add_entities([CthaThermostat(entry)])


class CthaThermostat(ClimateEntity, RestoreEntity):
    """Termostato con isteresi, base del cronotermostato CTHA."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = False
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_preset_modes = [PRESET_COMFORT, PRESET_ECO, PRESET_ANTIFREEZE]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_target_temperature_step = TEMP_STEP

    def __init__(self, entry: ConfigEntry) -> None:
        """Inizializza il termostato dalla config entry."""
        self._entry = entry
        self._sensor_entity_id: str = entry.data[CONF_SENSOR]
        self._heater_entity_id: str = entry.data[CONF_HEATER]
        self._cold_tolerance: float = entry.options.get(
            CONF_COLD_TOLERANCE, DEFAULT_COLD_TOLERANCE
        )
        self._hot_tolerance: float = entry.options.get(
            CONF_HOT_TOLERANCE, DEFAULT_HOT_TOLERANCE
        )

        self._attr_unique_id = entry.entry_id
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.data[CONF_NAME],
            "manufacturer": "CTHA",
        }

        self._attr_hvac_mode = HVACMode.OFF
        self._attr_preset_mode = PRESET_COMFORT
        self._attr_target_temperature = DEFAULT_TEMP_COMFORT
        self._attr_current_temperature: float | None = None

    async def async_added_to_hass(self) -> None:
        """Ripristina lo stato e si iscrive agli aggiornamenti del sensore."""
        await super().async_added_to_hass()

        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state in (HVACMode.HEAT, HVACMode.OFF):
                self._attr_hvac_mode = HVACMode(last_state.state)
            if (preset := last_state.attributes.get("preset_mode")) in self._attr_preset_modes:
                self._attr_preset_mode = preset
            if (target := last_state.attributes.get(ATTR_TEMPERATURE)) is not None:
                self._attr_target_temperature = float(target)

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._sensor_entity_id], self._async_sensor_changed
            )
        )

        self._async_read_sensor(self.hass.states.get(self._sensor_entity_id))
        await self._async_control_heating()

    @property
    def hvac_action(self) -> HVACAction:
        """Restituisce l'azione in corso, letta dallo stato dell'attuatore."""
        if self._attr_hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        if self._is_heater_active:
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def _is_heater_active(self) -> bool:
        """True se l'attuatore risulta acceso."""
        state = self.hass.states.get(self._heater_entity_id)
        return state is not None and state.state == STATE_ON

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Imposta il setpoint richiesto dall'utente."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        self._attr_target_temperature = float(temperature)
        await self._async_control_heating()
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Accende o spegne il termostato."""
        if hvac_mode not in self._attr_hvac_modes:
            raise ValueError(f"Modalità HVAC non supportata: {hvac_mode}")
        self._attr_hvac_mode = hvac_mode
        await self._async_control_heating()
        self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Applica un preset e il relativo setpoint."""
        if preset_mode not in self._attr_preset_modes:
            raise ValueError(f"Preset non supportato: {preset_mode}")
        self._attr_preset_mode = preset_mode
        self._attr_target_temperature = PRESET_TEMPERATURES[preset_mode]
        await self._async_control_heating()
        self.async_write_ha_state()

    async def _async_sensor_changed(self, event: Event[EventStateChangedData]) -> None:
        """Reagisce a una nuova lettura del sensore di temperatura."""
        self._async_read_sensor(event.data["new_state"])
        await self._async_control_heating()
        self.async_write_ha_state()

    @callback
    def _async_read_sensor(self, state: Any) -> None:
        """Aggiorna la temperatura corrente a partire dallo stato del sensore."""
        if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            self._attr_current_temperature = None
            return
        try:
            self._attr_current_temperature = float(state.state)
        except ValueError:
            _LOGGER.warning(
                "Valore non numerico da %s: %s", self._sensor_entity_id, state.state
            )
            self._attr_current_temperature = None

    async def _async_control_heating(self) -> None:
        """Applica la logica a isteresi sull'attuatore."""
        if self._attr_hvac_mode == HVACMode.OFF:
            await self._async_set_heater(False)
            return

        current = self._attr_current_temperature
        target = self._attr_target_temperature
        if current is None or target is None:
            return

        if current <= target - self._cold_tolerance:
            await self._async_set_heater(True)
        elif current >= target + self._hot_tolerance:
            await self._async_set_heater(False)

    async def _async_set_heater(self, turn_on: bool) -> None:
        """Chiama il servizio sull'attuatore solo se lo stato deve cambiare."""
        if self._is_heater_active == turn_on:
            return

        domain = self._heater_entity_id.split(".")[0]
        await self.hass.services.async_call(
            domain,
            SERVICE_TURN_ON if turn_on else SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: self._heater_entity_id},
            blocking=True,
            context=self._context,
        )
