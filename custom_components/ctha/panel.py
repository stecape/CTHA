"""Registrazione del pannello CTHA nella sidebar di Home Assistant.

L'interfaccia di programmazione è un pannello e non una card: una griglia
settimanale da 48 slot per sette giorni non sta in una card di dashboard, e
soprattutto non ha senso duplicarla su più dashboard — è uno strumento di
configurazione, non una vista di stato.

Il bundle React è servito da un percorso statico dedicato e caricato come
modulo ESM. L'url porta la versione dell'integrazione come query string: senza,
dopo un aggiornamento il browser continuerebbe a servire il bundle vecchio
dalla cache.
"""

from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from .const import (
    DOMAIN,
    PANEL_ELEMENT,
    PANEL_ICON,
    PANEL_MODULE,
    PANEL_PATH,
    PANEL_TITLE,
    PANEL_URL,
)

FRONTEND_DIR = Path(__file__).parent / "frontend"

# Le rotte di aiohttp non si possono rimuovere: una volta servito, il bundle
# resta servito per tutta la vita del processo. Il flag è a livello di modulo
# perché è esattamente la stessa durata, e ricaricare l'integrazione senza di
# esso farebbe fallire la seconda registrazione della stessa rotta.
_static_registered = False


async def async_register_panel(hass: HomeAssistant) -> None:
    """Serve il bundle e aggiunge la voce in sidebar, una sola volta."""
    global _static_registered  # noqa: PLW0603 - vedi il commento sopra

    integration = await async_get_integration(hass, DOMAIN)

    if not _static_registered:
        await hass.http.async_register_static_paths(
            [StaticPathConfig(PANEL_URL, str(FRONTEND_DIR), cache_headers=False)]
        )
        _static_registered = True

    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_PATH,
        webcomponent_name=PANEL_ELEMENT,
        module_url=f"{PANEL_MODULE}?v={integration.version}",
        sidebar_title=PANEL_TITLE,
        sidebar_icon=PANEL_ICON,
        require_admin=True,
    )


def async_remove_panel(hass: HomeAssistant) -> None:
    """Toglie la voce dalla sidebar quando l'ultima zona viene rimossa."""
    frontend.async_remove_panel(hass, PANEL_PATH)
