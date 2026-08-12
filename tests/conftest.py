"""Rende importabile il nucleo puro di CTHA senza Home Assistant.

`custom_components/ctha/__init__.py` importa `homeassistant`, quindi un
`import ctha.models` normale trascinerebbe dentro l'intero framework. Qui il
package viene registrato a mano come modulo fittizio con il solo `__path__`:
i sottomoduli si importano regolarmente, gli import relativi funzionano, e
l'`__init__.py` vero non viene mai eseguito.

Vale solo per i moduli che non toccano HA — `const`, `models`, `resolve`,
`override`, `program`. Il resto del componente va testato con
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

from ctha import models  # noqa: E402  (dipende dallo stub registrato sopra)
from ctha.const import LEVEL_COMFORT  # noqa: E402

# Martedì, così il weekday (1) non coincide con lo slot né con l'indice zero.
MORNING = datetime(2026, 8, 11, 7, 0)
NIGHT = datetime(2026, 8, 11, 3, 0)


@pytest.fixture
def data() -> models.CthaData:
    """Modello di default con una zona registrata, come dopo la prima entry."""
    model = models.CthaData.default()
    model.zones["z1"] = models.Zone(id="z1", name="Soggiorno")
    return model


@pytest.fixture
def zone(data: models.CthaData) -> models.Zone:
    """La zona di prova contenuta nel modello."""
    return data.zones["z1"]


@pytest.fixture
def comfort() -> str:
    """Livello usato dalla maggior parte dei casi sull'asse termico."""
    return LEVEL_COMFORT
