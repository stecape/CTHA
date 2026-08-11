"""Integrazione CTHA: cronotermostato multi-zona per Home Assistant.

Ogni config entry descrive una zona, ma programma, scenari e override sono
condivisi: Store, coordinator e servizi sono quindi istanze uniche, create
alla prima entry e smontate con l'ultima.
"""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import CthaCoordinator, async_get_coordinator
from .services import async_register_services, async_unregister_services
from .store import async_get_store

PLATFORMS: list[Platform] = [Platform.CLIMATE]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Configura una zona CTHA, avviando il runtime condiviso se serve."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    store = async_get_store(hass)
    coordinator = async_get_coordinator(hass, store)

    if not domain_data.get("initialized"):
        await coordinator.async_initialize()
        domain_data["initialized"] = True

    async_register_services(hass)
    domain_data.setdefault("entries", set()).add(entry.entry_id)
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Scarica una zona e, se era l'ultima, ferma il runtime condiviso."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False

    domain_data = hass.data.get(DOMAIN, {})
    entries: set[str] = domain_data.get("entries", set())
    entries.discard(entry.entry_id)

    if not entries:
        coordinator: CthaCoordinator | None = domain_data.get("coordinator")
        if coordinator is not None:
            await coordinator.async_shutdown()
        async_unregister_services(hass)
        hass.data.pop(DOMAIN, None)

    return True


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Elimina dal modello la zona rimossa, per non lasciare dati orfani."""
    store = async_get_store(hass)
    if not hass.data.get(DOMAIN, {}).get("initialized"):
        await store.async_load()

    store.data.zones.pop(entry.entry_id, None)
    store.data.overrides.pop(entry.entry_id, None)
    await store.async_save()


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Ricarica la entry quando cambiano le opzioni."""
    await hass.config_entries.async_reload(entry.entry_id)
