"""Persistenza del modello CTHA tramite lo Store helper di Home Assistant.

Il programma settimanale non sta nelle opzioni della config entry: è un dato
condiviso fra tutte le zone e cambia molto più spesso della configurazione
hardware, quindi vive in uno Store dedicato con il proprio versionamento.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, STORAGE_KEY, STORAGE_VERSION
from .models import CthaData


class CthaStore:
    """Carica e salva il modello CTHA, con debounce sui salvataggi."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Prepara lo Store senza ancora leggere da disco."""
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY, private=True
        )
        self.data = CthaData.default()

    async def async_load(self) -> CthaData:
        """Legge il modello persistito, o ne crea uno di default al primo avvio."""
        raw = await self._store.async_load()
        self.data = CthaData.from_dict(raw) if raw else CthaData.default()
        return self.data

    async def async_save(self) -> None:
        """Persiste il modello corrente."""
        await self._store.async_save(self.data.to_dict())

    def async_schedule_save(self) -> None:
        """Persiste in modo differito: le modifiche dalla UI arrivano a raffica."""
        self._store.async_delay_save(self.data.to_dict, 10)

    async def async_remove(self) -> None:
        """Cancella i dati persistiti quando l'integrazione viene rimossa."""
        await self._store.async_remove()


def async_get_store(hass: HomeAssistant) -> CthaStore:
    """Restituisce lo Store condiviso dell'integrazione, creandolo se serve."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if (store := domain_data.get("store")) is None:
        store = domain_data["store"] = CthaStore(hass)
    return store
