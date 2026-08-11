"""Gestione degli override: classificazione, soppressione echo, scadenza.

Tre sorgenti che sembrano lo stesso evento — "il setpoint di una zona è
cambiato" — ma richiedono trattamenti opposti:

* **HA** — l'abbiamo scritto noi. Ritorna indietro dal bus come cambio di
  stato e va soppresso, altrimenti si genera un loop di feedback fra override
  e riscritture.
* **esterno** — app del costruttore o unità centrale. È un override vero, si
  registra e scade secondo la sua policy.
* **hardware** — manopola del termostato fisico. Nessun comando software può
  annullarlo: si può solo compensarlo o mostrarlo, quindi non gli si applica
  una scadenza.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .const import (
    ECHO_DEADBAND,
    ECHO_WINDOW,
    OVERRIDE_SOURCE_EXTERNAL,
    OVERRIDE_SOURCE_HA,
    OVERRIDE_SOURCE_HARDWARE,
    POLICY_DURATION,
    POLICY_NEXT_SLOT,
    POLICY_STICKY,
    POLICY_UNTIL_SCENARIO_CHANGE,
)
from .models import CthaData, Override
from .resolve import next_slot_start


@dataclass(frozen=True, slots=True)
class PendingWrite:
    """Scrittura che abbiamo appena inviato, in attesa della propria eco."""

    temperature: float
    written_at: datetime


def expiry_for(
    policy: str, now: datetime, duration: timedelta | None = None
) -> datetime | None:
    """Istante di scadenza per una policy, o `None` se non scade da sola."""
    if policy == POLICY_NEXT_SLOT:
        return next_slot_start(now)
    if policy == POLICY_DURATION:
        return now + (duration or timedelta(hours=1))
    # sticky e until_scenario_change non hanno una scadenza temporale.
    return None


def is_expired(override: Override, now: datetime, active_scenario: str) -> bool:
    """Dice se un override ha esaurito la propria validità."""
    if override.source == OVERRIDE_SOURCE_HARDWARE or override.policy == POLICY_STICKY:
        return False
    if override.policy == POLICY_UNTIL_SCENARIO_CHANGE:
        return override.scenario_id != active_scenario
    return override.expires_at is not None and now >= override.expires_at


class OverrideManager:
    """Tiene il registro degli override e riconosce le eco delle nostre scritture."""

    def __init__(self, data: CthaData) -> None:
        """Lavora sullo stesso modello persistito, senza copiarlo."""
        self._data = data
        self._pending: dict[str, list[PendingWrite]] = {}

    def note_write(self, zone_id: str, temperature: float, now: datetime) -> None:
        """Registra una scrittura nostra, così da riconoscerne l'eco."""
        pending = self._prune(zone_id, now)
        pending.append(PendingWrite(temperature, now))

    def is_echo(self, zone_id: str, temperature: float, now: datetime) -> bool:
        """True se la variazione osservata combacia con una nostra scrittura recente."""
        return any(
            abs(write.temperature - temperature) <= ECHO_DEADBAND
            for write in self._prune(zone_id, now)
        )

    def classify(self, zone_id: str, temperature: float, now: datetime) -> str:
        """Attribuisce una variazione osservata a una delle tre sorgenti.

        Senza informazioni dal bus non si distingue un'app esterna dalla
        manopola fisica: chi ha quel dettaglio (l'adattatore MyHOME) può
        registrare l'override direttamente come `hardware`.
        """
        if self.is_echo(zone_id, temperature, now):
            return OVERRIDE_SOURCE_HA
        return OVERRIDE_SOURCE_EXTERNAL

    def set(
        self,
        zone_id: str,
        temperature: float,
        now: datetime,
        source: str = OVERRIDE_SOURCE_HA,
        policy: str = POLICY_NEXT_SLOT,
        duration: timedelta | None = None,
    ) -> Override:
        """Crea o sostituisce l'override di una zona."""
        override = Override(
            zone_id=zone_id,
            temperature=temperature,
            source=source,
            policy=policy,
            created_at=now,
            expires_at=expiry_for(policy, now, duration),
            scenario_id=self._data.active_scenario,
        )
        self._data.overrides[zone_id] = override
        return override

    def clear(self, zone_id: str) -> Override | None:
        """Rimuove l'override di una zona, restituendo quello eliminato."""
        return self._data.overrides.pop(zone_id, None)

    def get(self, zone_id: str) -> Override | None:
        """Override attualmente registrato per la zona, se presente."""
        return self._data.overrides.get(zone_id)

    def purge_expired(self, now: datetime) -> list[str]:
        """Elimina gli override scaduti, restituendo le zone interessate."""
        active = self._data.active_scenario
        expired = [
            zone_id
            for zone_id, override in self._data.overrides.items()
            if is_expired(override, now, active)
        ]
        for zone_id in expired:
            del self._data.overrides[zone_id]
        return expired

    def _prune(self, zone_id: str, now: datetime) -> list[PendingWrite]:
        """Scarta le scritture troppo vecchie per giustificare un'eco."""
        pending = [
            write
            for write in self._pending.get(zone_id, [])
            if now - write.written_at <= ECHO_WINDOW
        ]
        self._pending[zone_id] = pending
        return pending
