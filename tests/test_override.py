"""Override: politiche di scadenza, soppressione echo, purge."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from conftest import HIGH, LOW
from ctha import models, override as override_mod, program
from ctha.const import (
    INHERIT_CHAR,
    OVERRIDE_SOURCE_EXTERNAL,
    OVERRIDE_SOURCE_HA,
    OVERRIDE_SOURCE_HARDWARE,
    POLICY_DURATION,
    POLICY_NEXT_SLOT,
    POLICY_STICKY,
    POLICY_UNTIL_LEVEL_CHANGE,
    POLICY_UNTIL_SCENARIO_CHANGE,
    SLOTS_PER_DAY,
)

# Martedì mattina: la giornata tipo di default tiene «alta» dalle 06:00 alle
# 08:30, poi passa a «media». Le due fasce servono a far scadere l'override.
NOW = datetime(2026, 8, 11, 7, 10)
SAME_BAND = datetime(2026, 8, 11, 8, 0)
NEXT_BAND = datetime(2026, 8, 11, 9, 0)


@pytest.fixture
def manager(data: models.CthaData) -> override_mod.OverrideManager:
    """Manager che lavora sullo stesso modello persistito, senza copiarlo."""
    return override_mod.OverrideManager(data)


# --- politiche di scadenza --------------------------------------------------


def test_next_slot_scade_al_confine(
    manager: override_mod.OverrideManager,
) -> None:
    """La policy di default dura fino alla fine della mezz'ora corrente."""
    override = manager.set("z1", 24.0, NOW, policy=POLICY_NEXT_SLOT)

    assert override.expires_at == datetime(2026, 8, 11, 7, 30)
    assert not override_mod.is_expired(override, NOW, "default")
    assert override_mod.is_expired(override, datetime(2026, 8, 11, 7, 30), "default")


def test_duration_scade_dopo_l_intervallo(
    manager: override_mod.OverrideManager,
) -> None:
    """Con `duration` la scadenza è esattamente l'intervallo richiesto."""
    override = manager.set(
        "z1", 24.0, NOW, policy=POLICY_DURATION, duration=timedelta(hours=2)
    )
    assert override.expires_at == NOW + timedelta(hours=2)


def test_duration_senza_intervallo_usa_un_ora(
    manager: override_mod.OverrideManager,
) -> None:
    """Il default esiste perché il servizio può omettere la durata."""
    override = manager.set("z1", 24.0, NOW, policy=POLICY_DURATION)
    assert override.expires_at == NOW + timedelta(hours=1)


def test_until_level_change_sopravvive_al_confine_di_slot(
    data: models.CthaData, manager: override_mod.OverrideManager
) -> None:
    """È la differenza con `next_slot`: la fascia dura più della mezz'ora.

    Alle 07:10 e alle 08:00 il programma tiene lo stesso livello, ma sono due
    slot diversi: `next_slot` sarebbe già decaduto.
    """
    override = manager.set("z1", 24.0, NOW, policy=POLICY_UNTIL_LEVEL_CHANGE)

    assert override.level == HIGH
    assert override.expires_at is None
    assert not override_mod.is_expired(override, SAME_BAND, "default", HIGH)


def test_until_level_change_decade_al_cambio_di_fascia(
    manager: override_mod.OverrideManager,
) -> None:
    """Quando il programma cambia livello, la mano dell'utente ha esaurito il suo."""
    override = manager.set("z1", 24.0, NOW, policy=POLICY_UNTIL_LEVEL_CHANGE)
    assert override_mod.is_expired(override, NEXT_BAND, "default", LOW)


def test_until_level_change_nel_purge(
    data: models.CthaData, manager: override_mod.OverrideManager
) -> None:
    """Il purge risolve da sé la fascia di ogni zona: il timer non la conosce."""
    manager.set("z1", 24.0, NOW, policy=POLICY_UNTIL_LEVEL_CHANGE)

    assert manager.purge_expired(SAME_BAND) == []
    assert "z1" in data.overrides

    assert manager.purge_expired(NEXT_BAND) == ["z1"]
    assert "z1" not in data.overrides


def test_until_level_change_decade_se_il_programma_cambia(
    data: models.CthaData, manager: override_mod.OverrideManager
) -> None:
    """Non serve che passi il tempo: basta che cambi il programma sotto i piedi."""
    manager.set("z1", 24.0, NOW, policy=POLICY_UNTIL_LEVEL_CHANGE)
    program.paint_day_template(data, "default", LOW, 0, SLOTS_PER_DAY - 1)

    assert manager.purge_expired(NOW) == ["z1"]


def test_until_level_change_con_slot_che_eredita(
    data: models.CthaData, manager: override_mod.OverrideManager
) -> None:
    """Uscire dall'ereditarietà è un cambio di fascia come gli altri."""
    data.day_templates["default"].slots = INHERIT_CHAR * SLOTS_PER_DAY
    override = manager.set("z1", 24.0, NOW, policy=POLICY_UNTIL_LEVEL_CHANGE)

    assert override.level is None
    assert not override_mod.is_expired(override, NEXT_BAND, "default", None)
    assert override_mod.is_expired(override, NEXT_BAND, "default", HIGH)


def test_active_tace_su_un_override_gia_decaduto(
    data: models.CthaData, manager: override_mod.OverrideManager
) -> None:
    """`get` dice cos'è registrato, `active` cos'è ancora valido.

    La differenza è tutta nella finestra fra un purge e l'altro: il purge passa
    ai confini di slot, quindi fino a mezz'ora un override decaduto resta scritto
    nel modello. Chi legge il setpoint in quel mentre — watchdog, entità,
    pannello — non deve vederlo.
    """
    manager.set("z1", 24.0, NOW, policy=POLICY_UNTIL_LEVEL_CHANGE)

    assert manager.active("z1", SAME_BAND) is not None
    assert manager.active("z1", NEXT_BAND) is None
    assert manager.get("z1") is not None


def test_active_senza_override_non_inventa_nulla(
    manager: override_mod.OverrideManager,
) -> None:
    """Una zona senza override risponde `None` a qualunque istante."""
    assert manager.active("z1", NOW) is None


def test_active_rispetta_gli_override_hardware(
    manager: override_mod.OverrideManager,
) -> None:
    """La manopola non decade mai: nessun comando software può annullarla."""
    manager.set(
        "z1", 24.0, NOW, source=OVERRIDE_SOURCE_HARDWARE, policy=POLICY_NEXT_SLOT
    )

    assert manager.active("z1", NOW + timedelta(days=30)) is not None


def test_until_scenario_change(manager: override_mod.OverrideManager) -> None:
    """Resiste al tempo, decade al cambio di scenario."""
    override = manager.set("z1", 24.0, NOW, policy=POLICY_UNTIL_SCENARIO_CHANGE)

    assert not override_mod.is_expired(override, NOW + timedelta(days=3), "default")
    assert override_mod.is_expired(override, NOW, "vacanza")


def test_sticky_non_scade_mai(manager: override_mod.OverrideManager) -> None:
    """Solo una rimozione esplicita lo toglie di mezzo."""
    override = manager.set("z1", 24.0, NOW, policy=POLICY_STICKY)
    assert not override_mod.is_expired(override, NOW + timedelta(days=30), "default")


def test_hardware_ignora_la_policy_temporale(
    manager: override_mod.OverrideManager,
) -> None:
    """La manopola fisica non si annulla via software: solo si compensa."""
    override = manager.set(
        "z1",
        24.0,
        NOW,
        source=OVERRIDE_SOURCE_HARDWARE,
        policy=POLICY_NEXT_SLOT,
    )
    assert not override_mod.is_expired(override, NOW + timedelta(days=1), "default")


def test_hardware_sopravvive_al_purge(
    data: models.CthaData, manager: override_mod.OverrideManager
) -> None:
    """Il watchdog non deve ripulire ciò che non può controllare."""
    manager.set(
        "z1", 24.0, NOW, source=OVERRIDE_SOURCE_HARDWARE, policy=POLICY_NEXT_SLOT
    )
    assert manager.purge_expired(NOW + timedelta(days=1)) == []
    assert "z1" in data.overrides


# --- soppressione echo ------------------------------------------------------


def test_eco_riconosciuta_entro_deadband(
    manager: override_mod.OverrideManager,
) -> None:
    """Il ritorno della nostra scrittura arriva arrotondato: 0.15 °C di margine."""
    manager.note_write("z1", 21.0, NOW)
    assert manager.is_echo("z1", 21.1, NOW + timedelta(seconds=5))


def test_scostamento_oltre_deadband_non_e_eco(
    manager: override_mod.OverrideManager,
) -> None:
    """Mezzo grado di differenza è qualcun altro che ha scritto."""
    manager.note_write("z1", 21.0, NOW)
    assert not manager.is_echo("z1", 21.5, NOW + timedelta(seconds=5))


def test_oltre_la_finestra_non_e_piu_eco(
    manager: override_mod.OverrideManager,
) -> None:
    """Passati 60 secondi la nostra scrittura non giustifica più nulla."""
    manager.note_write("z1", 21.0, NOW)
    assert not manager.is_echo("z1", 21.0, NOW + timedelta(seconds=90))


def test_classificazione_delle_variazioni(
    manager: override_mod.OverrideManager,
) -> None:
    """Ciò che non è eco è, in mancanza di dati dal bus, un override esterno."""
    manager.note_write("z1", 21.0, NOW)
    assert manager.classify("z1", 21.0, NOW) == OVERRIDE_SOURCE_HA
    assert manager.classify("z1", 25.0, NOW) == OVERRIDE_SOURCE_EXTERNAL


def test_le_zone_non_si_contaminano(manager: override_mod.OverrideManager) -> None:
    """L'eco di una zona non deve coprire la variazione di un'altra."""
    manager.note_write("z1", 21.0, NOW)
    assert not manager.is_echo("z2", 21.0, NOW)


# --- registro ---------------------------------------------------------------


def test_purge_rimuove_gli_scaduti(
    data: models.CthaData, manager: override_mod.OverrideManager
) -> None:
    """Il purge riporta le zone interessate, perché vanno riscritte."""
    manager.set("z1", 24.0, NOW, policy=POLICY_NEXT_SLOT)
    assert manager.purge_expired(datetime(2026, 8, 11, 8, 0)) == ["z1"]
    assert "z1" not in data.overrides


def test_set_sostituisce_l_override_precedente(
    data: models.CthaData, manager: override_mod.OverrideManager
) -> None:
    """Una zona ha al più un override: il nuovo rimpiazza il vecchio."""
    manager.set("z1", 24.0, NOW)
    manager.set("z1", 19.0, NOW)
    assert len(data.overrides) == 1
    assert data.overrides["z1"].temperature == 19.0


def test_clear_restituisce_l_override_rimosso(
    manager: override_mod.OverrideManager,
) -> None:
    """Il coordinator distingue "rimosso" da "non c'era" per evitare scritture inutili."""
    manager.set("z1", 24.0, NOW)
    assert manager.clear("z1") is not None
    assert manager.clear("z1") is None


def test_override_ricorda_lo_scenario_di_creazione(
    data: models.CthaData, manager: override_mod.OverrideManager
) -> None:
    """`until_scenario_change` si regge su questo campo."""
    data.active_scenario = "vacanza"
    assert manager.set("z1", 24.0, NOW).scenario_id == "vacanza"


def test_override_ricorda_la_fascia_di_creazione(
    manager: override_mod.OverrideManager,
) -> None:
    """`until_level_change` si regge su questo, e vale per ogni override."""
    assert manager.set("z1", 24.0, NOW, policy=POLICY_NEXT_SLOT).level == HIGH


def test_round_trip_della_fascia(
    data: models.CthaData, manager: override_mod.OverrideManager
) -> None:
    """Un riavvio non deve far scadere un override per amnesia."""
    manager.set("z1", 24.0, NOW, policy=POLICY_UNTIL_LEVEL_CHANGE)
    restored = models.CthaData.from_dict(data.to_dict()).overrides["z1"]

    assert restored.level == HIGH
    assert restored.policy == POLICY_UNTIL_LEVEL_CHANGE
