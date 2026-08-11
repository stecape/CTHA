# CLAUDE.md

Guida di riferimento per Claude Code quando lavora su questo repository.

## Cos'è CTHA

CTHA (Cronotermostato per Home Assistant) è un'integrazione custom per Home
Assistant, distribuita anche via HACS. Aggiunge un'entità `climate` che pilota
un attuatore (caldaia, valvola, relè) in base a un sensore di temperatura,
con controllo a isteresi. Il programmatore settimanale è pianificato ma non
ancora implementato (vedi Roadmap nel README).

Dominio dell'integrazione: `ctha`. Tipo: `helper`, `iot_class: local_push`.

## Struttura del repository

```
custom_components/ctha/
├── __init__.py       # setup/unload della config entry, forward alla piattaforma climate
├── climate.py         # CthaThermostat: entità climate e logica a isteresi
├── config_flow.py     # CthaConfigFlow (setup iniziale) e CthaOptionsFlow (tolleranze)
├── const.py           # DOMAIN, chiavi di config, default, limiti setpoint
├── manifest.json       # metadati dell'integrazione (versione, requisiti, HA minimo)
├── strings.json        # stringhe UI sorgente per config/options flow
└── translations/       # it.json, en.json — tenute sincronizzate con strings.json
hacs.json                # metadati per la distribuzione via HACS
README.md                # documentazione utente (installazione, config, roadmap)
```

Non esistono ancora test automatici né una config di sviluppo Home Assistant
nel repo (vedi Roadmap: `pytest-homeassistant-custom-component` è previsto ma
non presente).

## Architettura

- **Config entry**: creata da `CthaConfigFlow.async_step_user`, richiede
  `name`, `sensor_entity_id` (sensore con `device_class: temperature`) e
  `heater_entity_id` (dominio `switch`, `input_boolean` o `climate`). Un solo
  cronotermostato per attuatore (`_async_abort_entries_match`).
- **Options flow**: `CthaOptionsFlow` permette di rivedere a caldo
  `cold_tolerance` e `hot_tolerance` (isteresi, default 0.3 °C ciascuna).
- **`__init__.py`**: inoltra il setup alla piattaforma `climate` e registra un
  listener che ricarica la entry quando cambiano le opzioni.
- **`CthaThermostat` (climate.py)**: unica entità della piattaforma.
  - Estende `ClimateEntity` + `RestoreEntity`: ripristina modalità HVAC,
    preset e setpoint dopo un riavvio di Home Assistant.
  - Si iscrive ai cambi di stato del sensore via
    `async_track_state_change_event`.
  - Logica a isteresi in `_async_control_heating`: accende l'attuatore se
    `current <= target - cold_tolerance`, lo spegne se
    `current >= target + hot_tolerance`; se `hvac_mode == OFF` lo spegne e
    basta.
  - `_async_set_heater` chiama `turn_on`/`turn_off` sul dominio
    dell'attuatore solo se lo stato deve effettivamente cambiare (evita
    chiamate ridondanti al servizio).
  - Preset supportati: `comfort` (21 °C), `eco` (18 °C), `antifreeze` (7 °C),
    definiti in `PRESET_TEMPERATURES` (climate.py) a partire dai default in
    `const.py`.

Tutte le costanti condivise (chiavi di config, default, limiti setpoint)
vivono in `const.py`: aggiungere nuove chiavi lì, non come stringhe sparse
nel codice.

## Convenzioni di codice

- Python moderno per Home Assistant: `from __future__ import annotations`,
  type hints ovunque, entità asincrone (`async def async_...`).
- Docstring brevi in italiano su ogni funzione/metodo/classe pubblica, che
  spiegano il "perché"/comportamento, non la mera ripetizione del nome.
- Nessun commento superfluo: seguire lo stile esistente (docstring sì,
  commenti inline solo se il codice non è auto-esplicativo).
- Le stringhe UI vanno aggiunte sia in `strings.json` sia in
  `translations/it.json` e `translations/en.json`, mantenendo le chiavi
  allineate.
- Bump di `version` in `manifest.json` quando si rilascia una modifica
  utente-visibile (HACS legge questo campo).

## Sviluppo e test

Non c'è ancora un ambiente HA di sviluppo né una suite di test nel repo.
Per validare modifiche manualmente:

1. Copiare/linkare `custom_components/ctha` in
   `<config_home_assistant>/custom_components/`.
2. Riavviare Home Assistant e aggiungere l'integrazione da
   *Impostazioni → Dispositivi e servizi*.

Quando si aggiunge una suite di test (roadmap), usare
`pytest-homeassistant-custom-component` come indicato nel README.

## Roadmap (non ancora implementato)

- Programma settimanale (fasce orarie per giorno, editor da UI)
- Applicazione automatica dei preset in base al programma
- Override manuale temporaneo con rientro automatico nel programma
- Modalità vacanza / assenza
- Durata minima di ciclo per proteggere la caldaia (`CONF_MIN_CYCLE_DURATION`
  è già definita in `const.py` ma non ancora usata in `climate.py`)
- Test con `pytest-homeassistant-custom-component`
- Card Lovelace dedicata per il programma settimanale

`CONF_SCHEDULE` in `const.py` è un'altra chiave predisposta per il
programmatore settimanale ma non ancora consumata da nessun modulo: è il
punto di partenza naturale per implementare la roadmap.
