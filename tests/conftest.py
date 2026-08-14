"""Rende importabile il nucleo puro di CTHA senza Home Assistant.

`custom_components/ctha/__init__.py` importa `homeassistant`, quindi un
`import ctha.models` normale trascinerebbe dentro l'intero framework. Qui il
package viene registrato a mano come modulo fittizio con il solo `__path__`:
i sottomoduli si importano regolarmente, gli import relativi funzionano, e
l'`__init__.py` vero non viene mai eseguito.

Vale solo per i moduli che non toccano HA — `const`, `models`, `resolve`,
`override`, `program`, `migrate`. Il resto del componente va testato con
`pytest-homeassistant-custom-component`.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime
from pathlib import Path

import pytest

PACKAGE_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "ctha"

if "ctha" not in sys.modules:
    _stub = types.ModuleType("ctha")
    _stub.__path__ = [str(PACKAGE_DIR)]
    sys.modules["ctha"] = _stub

from ctha import models, program  # noqa: E402  (dipende dallo stub registrato sopra)

# Martedì, così il weekday (1) non coincide con lo slot né con l'indice zero.
# Alle 07:00 la giornata tipo di default è «alta», alle 03:00 «bassa».
MORNING = datetime(2026, 8, 11, 7, 0)
NIGHT = datetime(2026, 8, 11, 3, 0)

# I livelli iniziali, quelli che `CthaData.default()` crea.
HIGH = "alta"
MEDIUM = "media"
LOW = "bassa"
ANTIFREEZE = "antigelo"


@pytest.fixture
def data() -> models.CthaData:
    """Modello di default con una zona registrata, come dopo la prima entry."""
    model = models.CthaData.default()
    program.ensure_zone(model, "z1", "Soggiorno")
    return model


@pytest.fixture
def zone(data: models.CthaData) -> models.Zone:
    """La zona di prova contenuta nel modello."""
    return data.zones["z1"]


@pytest.fixture
def scenario(data: models.CthaData) -> models.Scenario:
    """Lo scenario attivo, cioè la configurazione delle zone in vigore."""
    active = data.active()
    assert active is not None
    return active
