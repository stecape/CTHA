"""Runtime condiviso di CTHA: programma, override e riconciliazione.

Il coordinator è unico per installazione e non per zona: il programma
settimanale è condiviso, e la riconciliazione deve poter scaglionare le
scritture di tutte le zone su un unico bus.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import program
from .const import (
    APPLY_DEBOUNCE_SECONDS,
    DOMAIN,
    OVERRIDE_SOURCE_HA,
    POLICY_NEXT_SLOT,
    RECONCILE_INTERVAL,
    SLOT_MINUTES,
    WRITE_STAGGER_SECONDS,
)
from .models import CthaData, Override
from .override import OverrideManager
from .resolve import Chain, Resolution, resolve_chain, resolve_setpoint
from .store import CthaStore

_LOGGER = logging.getLogger(__name__)

ZoneWriter = Callable[[float], Awaitable[None]]
ProgramEdit = Callable[[CthaData], Any]


class CthaCoordinator(DataUpdateCoordinator[CthaData]):
    """Tiene insieme modello, override e i due timer che li fanno vivere."""

    def __init__(self, hass: HomeAssistant, store: CthaStore) -> None:
        """Prepara il coordinator; i dati arrivano con `async_initialize`."""
        super().__init__(hass, _LOGGER, name=DOMAIN, update_interval=None)
        self._store = store
        self._writers: dict[str, ZoneWriter] = {}
        self._unsubscribers: list[Callable[[], None]] = []
        self._apply_unsubscribe: Callable[[], None] | None = None
        self.entity_ids: dict[str, str] = {}
        self.overrides = OverrideManager(store.data)

    async def _async_update_data(self) -> CthaData:
        """Il modello è locale: non c'è nulla da interrogare, si rilegge lo Store."""
        return self._store.data

    async def async_initialize(self) -> None:
        """Carica il modello e avvia i timer di slot e riconciliazione."""
        data = await self._store.async_load()
        self.overrides = OverrideManager(data)
        self.async_set_updated_data(data)

        self._unsubscribers.append(
            async_track_time_change(
                self.hass,
                self._async_slot_tick,
                minute=list(range(0, 60, SLOT_MINUTES)),
                second=0,
            )
        )
        self._unsubscribers.append(
            async_track_time_interval(
                self.hass, self._async_reconcile, RECONCILE_INTERVAL
            )
        )

    async def async_shutdown(self) -> None:
        """Ferma i timer quando l'ultima entry viene rimossa."""
        while self._unsubscribers:
            self._unsubscribers.pop()()
        if self._apply_unsubscribe is not None:
            self._apply_unsubscribe()
            self._apply_unsubscribe = None
        await super().async_shutdown()

    # --- Registrazione delle zone -------------------------------------------

    def register_zone(self, zone_id: str, name: str) -> None:
        """Assicura che la zona esista e sia programmata in ogni scenario."""
        if program.ensure_zone(self.data, zone_id, name):
            self._store.async_schedule_save()
            self.async_update_listeners()

    @callback
    def register_writer(self, zone_id: str, writer: ZoneWriter) -> Callable[[], None]:
        """Registra la funzione che applica un setpoint alla zona."""
        self._writers[zone_id] = writer

        @callback
        def _unregister() -> None:
            self._writers.pop(zone_id, None)

        return _unregister

    @callback
    def register_entity(self, zone_id: str, entity_id: str) -> Callable[[], None]:
        """Ricorda quale entità rappresenta la zona.

        Serve al pannello: la temperatura misurata sta nello stato dell'entità
        climate, non nel modello, e senza questa corrispondenza il frontend non
        saprebbe quale entità leggere per una zona.
        """
        self.entity_ids[zone_id] = entity_id

        @callback
        def _unregister() -> None:
            self.entity_ids.pop(zone_id, None)

        return _unregister

    # --- Lettura del programma ----------------------------------------------

    def resolution_for(self, zone_id: str, now: datetime | None = None) -> Resolution:
        """Risoluzione da programma per la zona, senza considerare gli override."""
        return resolve_setpoint(self.data, zone_id, now or dt_util.now())

    def chain_for(self, zone_id: str, now: datetime | None = None) -> Chain:
        """Percorso che la zona sta seguendo: scenario, settimana, giornata.

        Il pannello ha bisogno di nominarlo — «segue Invernale, oggi Feriale» —
        e la catena è già calcolata durante la risoluzione.
        """
        return resolve_chain(self.data, zone_id, now or dt_util.now())

    def target_for(self, zone_id: str, now: datetime | None = None) -> float | None:
        """Setpoint effettivo: l'override attivo se c'è, altrimenti il programma."""
        if (override := self.overrides.get(zone_id)) is not None:
            return override.temperature
        return self.resolution_for(zone_id, now).temperature

    # --- Scrittura ----------------------------------------------------------

    async def async_apply_zone(self, zone_id: str, now: datetime | None = None) -> None:
        """Applica alla zona il setpoint corrente, annotando la scrittura."""
        if (writer := self._writers.get(zone_id)) is None:
            return
        if (target := self.target_for(zone_id, now)) is None:
            return

        self.overrides.note_write(zone_id, target, now or dt_util.now())
        await writer(target)

    async def async_apply_all(self, now: datetime | None = None) -> None:
        """Riscrive tutte le zone scaglionando le scritture sul bus."""
        for index, zone_id in enumerate(list(self._writers)):
            if index:
                await asyncio.sleep(WRITE_STAGGER_SECONDS)
            try:
                await self.async_apply_zone(zone_id, now)
            except Exception:  # noqa: BLE001 - una zona non deve fermare le altre
                _LOGGER.exception("Riconciliazione fallita per la zona %s", zone_id)

    @callback
    def async_schedule_apply(self) -> None:
        """Riscrive tutte le zone a raffica finita.

        Una riscrittura completa impegna il bus per `WRITE_STAGGER_SECONDS` per
        zona: farla partire a ogni modifica renderebbe l'editing del programma
        lento quanto il bus. Ogni nuova modifica rimanda l'attesa.
        """
        if self._apply_unsubscribe is not None:
            self._apply_unsubscribe()
        self._apply_unsubscribe = async_call_later(
            self.hass, APPLY_DEBOUNCE_SECONDS, self._async_apply_pending
        )

    async def _async_apply_pending(self, now: datetime) -> None:
        """Riscrittura differita richiesta da `async_schedule_apply`."""
        self._apply_unsubscribe = None
        await self.async_apply_all(now)

    # --- Modifica del programma ---------------------------------------------

    async def async_edit(self, edit: ProgramEdit) -> Any:
        """Applica una modifica al programma, la persiste e riallinea le zone.

        Le operazioni vivono in `program.py` come funzioni pure sul modello:
        qui si aggiunge solo ciò che è di Home Assistant — persistenza,
        riscrittura delle zone, notifica alle entità. Gli errori di `program`
        risalgono al chiamante, che li traduce per l'utente.
        """
        result = edit(self.data)
        self._store.async_schedule_save()
        self.async_schedule_apply()
        self.async_update_listeners()
        return result

    # --- Override -----------------------------------------------------------

    async def async_set_override(
        self,
        zone_id: str,
        temperature: float,
        policy: str = POLICY_NEXT_SLOT,
        duration: timedelta | None = None,
        source: str = OVERRIDE_SOURCE_HA,
    ) -> Override:
        """Registra un override e lo applica subito alla zona."""
        override = self.overrides.set(
            zone_id,
            temperature,
            dt_util.now(),
            source=source,
            policy=policy,
            duration=duration,
        )
        self._store.async_schedule_save()
        await self.async_apply_zone(zone_id)
        self.async_update_listeners()
        return override

    async def async_clear_override(self, zone_id: str) -> None:
        """Rimuove l'override e riporta la zona al programma."""
        if self.overrides.clear(zone_id) is None:
            return
        self._store.async_schedule_save()
        await self.async_apply_zone(zone_id)
        self.async_update_listeners()

    async def async_set_active_scenario(self, scenario_id: str) -> None:
        """Cambia scenario, facendo decadere gli override legati al precedente."""

        def _edit(data: CthaData) -> None:
            program.set_active_scenario(data, scenario_id)
            self.overrides.purge_expired(dt_util.now())

        await self.async_edit(_edit)

    # --- Timer --------------------------------------------------------------

    async def _async_slot_tick(self, now: datetime) -> None:
        """A ogni confine di slot: scadenze degli override e nuovi setpoint."""
        if self.overrides.purge_expired(now):
            self._store.async_schedule_save()
        await self.async_apply_all(now)
        self.async_update_listeners()

    async def _async_reconcile(self, now: datetime) -> None:
        """Watchdog: riafferma i setpoint desiderati contro chi li sovrascrive."""
        await self.async_apply_all(now)


def async_get_coordinator(hass: HomeAssistant, store: CthaStore) -> CthaCoordinator:
    """Restituisce il coordinator condiviso, creandolo alla prima entry."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if (coordinator := domain_data.get("coordinator")) is None:
        coordinator = domain_data["coordinator"] = CthaCoordinator(hass, store)
    return coordinator
