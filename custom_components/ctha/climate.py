"""Entità climate di CTHA: una zona programmata sopra a un termostato esistente.

CTHA non regola nulla da sé. L'impianto misura già la temperatura e comanda già
le valvole — sull'impianto BTicino la sonda di zona misura, la centrale 3550
confronta col setpoint e pilota le testine attraverso gli attuatori. Quello che
manca è *quale setpoint tenere e quando*, ed è l'unica cosa che questa entità
fornisce, scrivendo `climate.set_temperature` sull'entità di zona di MyHOME.

Da qui discendono due comportamenti che sembrano dettagli e non lo sono:

* si scrive solo se il valore desiderato è diverso da quello già sul bus. Il
  watchdog passa su tutte le zone ogni pochi minuti, e senza questo confronto
  riasserirebbe all'infinito valori già corretti;
* ogni cambio del setpoint che non sia l'eco di una nostra scrittura è
  qualcun altro che ha messo mano alla zona — la manopola, l'app, la centrale.
  Diventa un override, non un errore da correggere subito.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.components.climate.const import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_HVAC_ACTION,
    ATTR_HVAC_MODE,
    ATTR_HVAC_MODES,
    DOMAIN as CLIMATE_DOMAIN,
    SERVICE_SET_HVAC_MODE,
    SERVICE_SET_TEMPERATURE,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    CONF_NAME,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import (
    CONF_TARGET,
    DOMAIN,
    MAX_TEMP,
    MIN_TEMP,
    OVERRIDE_SOURCE_EXTERNAL,
    POLICY_UNTIL_LEVEL_CHANGE,
    TEMP_STEP,
    WRITE_ATTEMPTS,
    WRITE_DEADBAND,
    WRITE_RETRY_SECONDS,
    WRITE_VERIFY_SECONDS,
)
from .coordinator import CthaCoordinator
from .resolve import resolve_level_temperature

_LOGGER = logging.getLogger(__name__)

ATTR_LEVEL = "level"
ATTR_SETPOINT_SOURCE = "setpoint_source"
ATTR_SCENARIO = "scenario"
ATTR_TARGET_ENTITY = "target_entity_id"
ATTR_OVERRIDE_SOURCE = "override_source"
ATTR_OVERRIDE_POLICY = "override_policy"
ATTR_OVERRIDE_EXPIRES = "override_expires_at"

UNUSABLE_STATES = (STATE_UNKNOWN, STATE_UNAVAILABLE)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Crea l'entità climate della zona descritta dalla config entry."""
    coordinator: CthaCoordinator = hass.data[DOMAIN]["coordinator"]
    async_add_entities([CthaThermostat(coordinator, entry)])


class CthaThermostat(CoordinatorEntity[CthaCoordinator], ClimateEntity):
    """Zona termica: programma il setpoint del termostato sottostante."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.HEAT, HVACMode.OFF]
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
        """Lega l'entità alla zona e al termostato che la governa."""
        super().__init__(coordinator)
        self._entry = entry
        self._zone_id = entry.entry_id
        self._target_entity_id: str = entry.data[CONF_TARGET]

        self._attr_unique_id = entry.entry_id
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.data[CONF_NAME],
            "manufacturer": "CTHA",
        }

        self._attr_target_temperature: float | None = None
        self._write_lock = asyncio.Lock()

    async def async_added_to_hass(self) -> None:
        """Registra la zona, si aggancia al termostato e applica il programma."""
        await super().async_added_to_hass()

        self.coordinator.register_zone(self._zone_id, self._entry.data[CONF_NAME])
        self.async_on_remove(
            self.coordinator.register_writer(self._zone_id, self._async_apply_setpoint)
        )
        self.async_on_remove(
            self.coordinator.register_entity(self._zone_id, self.entity_id)
        )
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self._target_entity_id], self._async_target_changed
            )
        )

        self._attr_target_temperature = self.coordinator.target_for(self._zone_id)
        await self.coordinator.async_apply_zone(self._zone_id)

    # --- Stato rispecchiato dal termostato sottostante ----------------------

    @property
    def _target_state(self) -> State | None:
        """Stato del termostato pilotato, se utilizzabile."""
        state = self.hass.states.get(self._target_entity_id)
        if state is None or state.state in UNUSABLE_STATES:
            return None
        return state

    @property
    def available(self) -> bool:
        """La zona esiste finché esiste il termostato che la rappresenta."""
        return self._target_state is not None

    @property
    def current_temperature(self) -> float | None:
        """Temperatura misurata nella zona, così come la riporta il bus."""
        state = self._target_state
        if state is None:
            return None
        return _as_float(state.attributes.get(ATTR_CURRENT_TEMPERATURE))

    @property
    def hvac_mode(self) -> HVACMode:
        """Acceso o spento: lo decide il termostato, noi lo rispecchiamo."""
        state = self._target_state
        if state is None or state.state == HVACMode.OFF:
            return HVACMode.OFF
        return HVACMode.HEAT

    @property
    def hvac_action(self) -> HVACAction | None:
        """Azione in corso secondo il termostato: è lui che comanda la valvola."""
        state = self._target_state
        if state is None:
            return None
        action = state.attributes.get(ATTR_HVAC_ACTION)
        try:
            return HVACAction(action) if action is not None else None
        except ValueError:
            return None

    @property
    def preset_modes(self) -> list[str]:
        """I livelli di temperatura esistenti: sono definibili dall'utente.

        L'elenco cambia quando si crea o si elimina un livello, quindi non può
        essere una costante di classe come su un termostato a preset fissi.
        """
        return list(self.coordinator.data.levels)

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
            ATTR_TARGET_ENTITY: self._target_entity_id,
        }
        if (override := self.coordinator.overrides.get(self._zone_id)) is not None:
            attributes[ATTR_OVERRIDE_SOURCE] = override.source
            attributes[ATTR_OVERRIDE_POLICY] = override.policy
            attributes[ATTR_OVERRIDE_EXPIRES] = (
                override.expires_at.isoformat() if override.expires_at else None
            )
        return attributes

    # --- Comandi ------------------------------------------------------------

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Un setpoint scelto a mano è un override, non una modifica al programma.

        Vale per tutta la fascia in corso: chi alza la temperatura alle 07:05
        la vuole per la mattina, non per venticinque minuti. Al cambio di fascia
        il programma riprende, che è il momento in cui l'utente si aspetta che
        la casa cambi comportamento da sola.
        """
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is None:
            return
        await self.coordinator.async_set_override(
            self._zone_id, float(temperature), policy=POLICY_UNTIL_LEVEL_CHANGE
        )

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Forza un livello: si traduce nell'override della sua temperatura.

        I gradi si risolvono lungo la catena della zona in questo momento, non
        sul globale: «alta» vale quello che vale *qui e adesso*, ed è l'unico
        numero che l'utente si aspetta di vedere comparire.
        """
        if preset_mode not in self.preset_modes:
            raise ValueError(f"Preset non supportato: {preset_mode}")

        resolution = resolve_level_temperature(
            self.coordinator.data, self._zone_id, preset_mode, dt_util.now()
        )
        if resolution.temperature is None:
            _LOGGER.warning("Nessun setpoint definito per il livello %s", preset_mode)
            return

        await self.coordinator.async_set_override(
            self._zone_id, resolution.temperature, policy=POLICY_UNTIL_LEVEL_CHANGE
        )

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Accende o spegne la zona sul termostato sottostante."""
        if hvac_mode not in self._attr_hvac_modes:
            raise ValueError(f"Modalità HVAC non supportata: {hvac_mode}")

        await self.hass.services.async_call(
            CLIMATE_DOMAIN,
            SERVICE_SET_HVAC_MODE,
            {
                ATTR_ENTITY_ID: self._target_entity_id,
                ATTR_HVAC_MODE: (
                    HVACMode.OFF if hvac_mode == HVACMode.OFF else self._heating_mode()
                ),
            },
            blocking=True,
            context=self._context,
        )

        if hvac_mode != HVACMode.OFF:
            await self.coordinator.async_apply_zone(self._zone_id)

    def _heating_mode(self) -> str:
        """Modalità con cui riaccendere la zona.

        Si preferisce `heat`, cioè il funzionamento a setpoint: `auto` su un
        impianto BTicino significa "segui il programma della centrale", che è
        esattamente ciò che CTHA sta sostituendo.
        """
        state = self.hass.states.get(self._target_entity_id)
        modes = state.attributes.get(ATTR_HVAC_MODES, []) if state else []
        if HVACMode.HEAT in modes or not modes:
            return HVACMode.HEAT
        return next((mode for mode in modes if mode != HVACMode.OFF), HVACMode.HEAT)

    # --- Scrittura sul bus --------------------------------------------------

    async def _async_apply_setpoint(self, temperature: float) -> None:
        """Writer registrato nel coordinator: porta il setpoint sul termostato.

        Scrive, verifica, e se serve riprova. La chiamata al servizio che riesce
        non dimostra che il setpoint sia arrivato: ha solo consegnato il comando
        al gateway, e sul bus da lì in poi può perdersi in silenzio. L'unica
        prova è che il termostato riporti il valore chiesto.

        Senza questo, una scrittura persa restava tale fino al giro successivo
        del watchdog — fino a dodici minuti di zona ferma sul valore sbagliato,
        senza una riga di log.
        """
        # Un lock per zona: il tick di slot e il watchdog possono sovrapporsi, e
        # due cicli di scrittura intrecciati sullo stesso termostato si
        # verificherebbero a vicenda il valore dell'altro.
        async with self._write_lock:
            self._attr_target_temperature = temperature

            if self.hvac_mode == HVACMode.OFF:
                # Una zona spenta a mano resta spenta: scriverle un setpoint la
                # riaccenderebbe, e nessuno l'ha chiesto. Vale anche per una
                # zona irraggiungibile, che da qui è indistinguibile da una
                # spenta — e questo va detto, perché una zona saltata in
                # silenzio resta indietro senza che nessuno se ne accorga.
                _LOGGER.debug(
                    "Nessuna scrittura su %s: %s",
                    self._target_entity_id,
                    "termostato non disponibile"
                    if self._target_state is None
                    else "zona spenta",
                )
                self.async_write_ha_state()
                return

            for attempt in range(1, WRITE_ATTEMPTS + 1):
                if not self._needs_write(temperature):
                    break
                if attempt > 1:
                    await asyncio.sleep(WRITE_RETRY_SECONDS)
                    _LOGGER.debug(
                        "Il setpoint %.1f °C non è arrivato su %s: tentativo %d di %d",
                        temperature,
                        self._target_entity_id,
                        attempt,
                        WRITE_ATTEMPTS,
                    )
                await self._async_write_setpoint(temperature)
                # Il valore torna dal bus come cambio di stato, non come esito
                # della chiamata: senza questa attesa si verificherebbe sempre
                # il valore vecchio, e si riproverebbe sempre.
                await asyncio.sleep(WRITE_VERIFY_SECONDS)

            if self._needs_write(temperature):
                _LOGGER.warning(
                    "Il setpoint %.1f °C non è arrivato su %s dopo %d tentativi: "
                    "sul bus resta %s",
                    temperature,
                    self._target_entity_id,
                    WRITE_ATTEMPTS,
                    self._bus_setpoint(),
                )

            self.async_write_ha_state()

    async def _async_write_setpoint(self, temperature: float) -> None:
        """Manda il comando al termostato, senza fermare il ciclo se fallisce.

        Un errore qui è un tentativo andato male, non la fine: quello dopo può
        riuscire, e la decisione se insistere è di chi tiene il ciclo.
        """
        try:
            await self.hass.services.async_call(
                CLIMATE_DOMAIN,
                SERVICE_SET_TEMPERATURE,
                {ATTR_ENTITY_ID: self._target_entity_id, ATTR_TEMPERATURE: temperature},
                blocking=True,
                context=self._context,
            )
        except Exception as err:  # noqa: BLE001 - il ciclo decide se riprovare
            _LOGGER.debug(
                "Scrittura di %.1f °C su %s non riuscita: %s",
                temperature,
                self._target_entity_id,
                err,
            )

    def _bus_setpoint(self) -> float | None:
        """Setpoint che il termostato riporta adesso, per i messaggi d'errore."""
        state = self._target_state
        return None if state is None else _as_float(state.attributes.get(ATTR_TEMPERATURE))

    def _needs_write(self, temperature: float) -> bool:
        """True se il bus non ha già il valore voluto."""
        state = self._target_state
        if state is None:
            return False
        current = _as_float(state.attributes.get(ATTR_TEMPERATURE))
        return current is None or abs(current - temperature) > WRITE_DEADBAND

    # --- Ascolto del termostato --------------------------------------------

    async def _async_target_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Recepisce ciò che succede sul termostato, incluse le mani altrui.

        Un cambio di setpoint si riconosce solo confrontando due valori noti.
        Quando il termostato *compare* — avvio di Home Assistant, MyHOME che si
        ricollega — non c'è nulla da confrontare, e prendere per buono ciò che
        si trova sul bus vorrebbe dire accettare come override il valore
        lasciato lì dalla centrale. Lì si riafferma il programma, non lo si
        subisce.
        """
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]

        if new_state is None or new_state.state in UNUSABLE_STATES:
            self.async_write_ha_state()
            return

        if old_state is None or old_state.state in UNUSABLE_STATES:
            # Il termostato è appena comparso: niente da confrontare.
            await self.coordinator.async_apply_zone(self._zone_id)
            self.async_write_ha_state()
            return

        if old_state.state == HVACMode.OFF and new_state.state != HVACMode.OFF:
            # Riacceso da fuori: la zona torna sotto il programma.
            await self.coordinator.async_apply_zone(self._zone_id)
            self.async_write_ha_state()
            return

        old_setpoint = _as_float(old_state.attributes.get(ATTR_TEMPERATURE))
        new_setpoint = _as_float(new_state.attributes.get(ATTR_TEMPERATURE))
        if (
            old_setpoint is not None
            and new_setpoint is not None
            and abs(old_setpoint - new_setpoint) > WRITE_DEADBAND
        ):
            await self._async_note_external(new_setpoint)

        self.async_write_ha_state()

    async def _async_note_external(self, setpoint: float) -> None:
        """Registra come override un setpoint che non abbiamo scritto noi.

        Non si distingue la manopola dall'app né dalla centrale: dal bus
        arrivano uguali. L'unica cosa che si può dire è "non l'ho scritto io",
        e la risposta ragionevole è tenerlo per la fascia in corso invece di
        sovrascriverlo subito.

        Il rovescio della medaglia: se a scrivere è la centrale 3550 che
        riafferma il proprio programma, anche *quella* resta per tutta la
        fascia. Litigarci ogni minuto sarebbe peggio, ma il rimedio vero resta
        appiattire il programma della centrale — finché non è appiattito, una
        sua riasserzione costa più di prima.
        """
        if self.coordinator.overrides.is_echo(self._zone_id, setpoint, dt_util.now()):
            return

        desired = self.coordinator.target_for(self._zone_id)
        if desired is not None and abs(desired - setpoint) <= WRITE_DEADBAND:
            return

        existing = self.coordinator.overrides.get(self._zone_id)
        if existing is not None and abs(existing.temperature - setpoint) <= WRITE_DEADBAND:
            return

        _LOGGER.debug(
            "Setpoint esterno su %s: %.1f °C (atteso %s)",
            self._target_entity_id,
            setpoint,
            desired,
        )
        await self.coordinator.async_set_override(
            self._zone_id,
            setpoint,
            policy=POLICY_UNTIL_LEVEL_CHANGE,
            source=OVERRIDE_SOURCE_EXTERNAL,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        """Recepisce un nuovo setpoint deciso dal coordinator."""
        self._attr_target_temperature = self.coordinator.target_for(self._zone_id)
        super()._handle_coordinator_update()


def _as_float(value: Any) -> float | None:
    """Converte un attributo in float, tollerando assenza e valori sporchi."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
