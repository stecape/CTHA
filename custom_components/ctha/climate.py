"""Entità climate di CTHA: una zona termica pilotata dal programma.

L'entità non decide più da sola quale temperatura tenere: il setpoint arriva
dal coordinator (programma settimanale più eventuale override) e qui resta
solo l'attuazione — isteresi sull'attuatore e lettura del sensore.
"""

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
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_COLD_TOLERANCE,
    CONF_HEATER,
    CONF_HOT_TOLERANCE,
    CONF_SENSOR,
    DEFAULT_COLD_TOLERANCE,
    DEFAULT_HOT_TOLERANCE,
    DOMAIN,
    LEVEL_ANTIFREEZE,
    LEVEL_COMFORT,
    LEVEL_ECO,
    MAX_TEMP,
    MIN_TEMP,
    POLICY_NEXT_SLOT,
    TEMP_STEP,
)
from .coordinator import CthaCoordinator
from .resolve import resolve_temperature

_LOGGER = logging.getLogger(__name__)

ATTR_LEVEL = "level"
ATTR_SETPOINT_SOURCE = "setpoint_source"
ATTR_SCENARIO = "scenario"
ATTR_OVERRIDE_SOURCE = "override_source"
ATTR_OVERRIDE_POLICY = "override_policy"
ATTR_OVERRIDE_EXPIRES = "override_expires_at"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crea l'entità climate della zona descritta dalla config entry."""
    coordinator: CthaCoordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities([CthaThermostat(coordinator, entry)])


class CthaThermostat(CoordinatorEntity[CthaCoordinator], ClimateEntity, RestoreEntity):
    """Zona termica: applica il setpoint del programma con controllo a isteresi."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
    _attr_preset_modes = [LEVEL_COMFORT, LEVEL_ECO, LEVEL_ANTIFREEZE]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_target_temperature_step = TEMP_STEP

    def __init__(self, coordinator: CthaCoordinator, entry: ConfigEntry) -> None:
        """Lega l'entità alla zona corrispondente alla config entry."""
        super().__init__(coordinator)
        self._entry = entry
        self._zone_id = entry.entry_id
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
        self._attr_target_temperature: float | None = None
        self._attr_current_temperature: float | None = None

    async def async_added_to_hass(self) -> None:
        """Registra la zona, ripristina lo stato e si aggancia al sensore."""
        await super().async_added_to_hass()

        self.coordinator.register_zone(self._zone_id, self._entry.data[CONF_NAME])
        self.async_on_remove(
            self.coordinator.register_writer(self._zone_id, self._async_apply_setpoint)
        )

        if (last_state := await self.async_get_last_state()) is not None:
            if last_state.state in (HVACMode.HEAT, HVACMode.OFF):
                self._attr_hvac_mode = HVACMode(last_state.state)

        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._sensor_entity_id], self._async_sensor_changed
            )
        )

        self._async_read_sensor(self.hass.states.get(self._sensor_entity_id))
        self._attr_target_temperature = self.coordinator.target_for(self._zone_id)
        await self._async_control_heating()

    @property
    def hvac_action(self) -> HVACAction:
        """Azione in corso, dedotta dallo stato reale dell'attuatore."""
        if self._attr_hvac_mode == HVACMode.OFF:
            return HVACAction.OFF
        if self._is_heater_active:
            return HVACAction.HEATING
        return HVACAction.IDLE

    @property
    def preset_mode(self) -> str | None:
        """Livello risolto dal programma; `None` mentre un override è attivo."""
        if self.coordinator.overrides.get(self._zone_id) is not None:
            return None
        return self.coordinator.resolution_for(self._zone_id).level

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Espone provenienza del setpoint e stato dell'override.

        Serve a rendere leggibile l'ereditarietà: senza questi attributi non
        si distingue un setpoint proprio della zona da uno globale, né si vede
        quando un override decadrà.
        """
        resolution = self.coordinator.resolution_for(self._zone_id)
        attributes: dict[str, Any] = {
            ATTR_LEVEL: resolution.level,
            ATTR_SETPOINT_SOURCE: resolution.source,
            ATTR_SCENARIO: self.coordinator.data.active_scenario,
        }
        if (override := self.coordinator.overrides.get(self._zone_id)) is not None:
            attributes[ATTR_OVERRIDE_SOURCE] = override.source
            attributes[ATTR_OVERRIDE_POLICY] = override.policy
            attributes[ATTR_OVERRIDE_EXPIRES] = (
                override.expires_at.isoformat() if override.expires_at else None
            )
        return attributes

    @property
    def _is_heater_active(self) -> bool:
        """True se l'attuatore risulta acceso."""
        state = self.hass.states.get(self._heater_entity_id)
        return state is not None and state.state == STATE_ON

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Un setpoint scelto a mano è un override, non una modifica al programma."""
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        await self.coordinator.async_set_override(
            self._zone_id, float(temperature), policy=POLICY_NEXT_SLOT
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Accende o spegne la zona."""
        if hvac_mode not in self._attr_hvac_modes:
            raise ValueError(f"Modalità HVAC non supportata: {hvac_mode}")
        self._attr_hvac_mode = hvac_mode
        await self._async_control_heating()
        self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Forza un livello: si traduce nell'override della sua temperatura."""
        if preset_mode not in self._attr_preset_modes:
            raise ValueError(f"Preset non supportato: {preset_mode}")

        zone = self.coordinator.data.zones.get(self._zone_id)
        if zone is None:
            return

        resolution = resolve_temperature(
            self.coordinator.data, zone, preset_mode, self.coordinator.data.active()
        )
        if resolution.temperature is None:
            _LOGGER.warning("Nessun setpoint definito per il livello %s", preset_mode)
            return

        await self.coordinator.async_set_override(
            self._zone_id, resolution.temperature, policy=POLICY_NEXT_SLOT
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Recepisce un nuovo setpoint deciso dal coordinator."""
        self._attr_target_temperature = self.coordinator.target_for(self._zone_id)
        super()._handle_coordinator_update()

    async def _async_apply_setpoint(self, temperature: float) -> None:
        """Writer registrato nel coordinator: riceve il setpoint da tenere."""
        self._attr_target_temperature = temperature
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
