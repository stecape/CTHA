# CLAUDE.md

Guida di riferimento per Claude Code quando lavora su questo repository.

## Scopo e contesto

Stefano sta sviluppando un componente custom per Home Assistant per gestire
un impianto di riscaldamento a pavimento radiante multi-zona. L'impianto
prevede 10 zone BTicino integrate tramite l'integrazione MyHOME (di
anotherjulien), con 9 zone attive più un'unità centrale (#0), tutte
configurate come `standalone: False`, con sensori dei termostati fisici
BTicino F430/4 e centrale modello 3550.

L'obiettivo del progetto è un sistema di programmazione e override completo
che gli strumenti nativi di HA non coprono: programmazione settimanale
multi-scenario, livelli di temperatura ereditati, template riutilizzabili e
gestione elegante degli override a livello hardware provenienti dai
termostati fisici e dall'unità centrale.

**Nota sullo stato del codice**: l'implementazione attuale in
`custom_components/ctha/` (vedi sotto) è un MVP generico a singola zona —
un'entità `climate` a isteresi che pilota un attuatore qualsiasi (`switch`,
`input_boolean` o `climate`), senza alcun riferimento specifico a BTicino o
MyHOME. Rappresenta il punto di partenza su cui costruire l'architettura
target multi-zona descritta di seguito, non ancora realizzata nel codice.

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

## Architettura target (progettazione, non ancora implementata)

L'architettura completa è stata progettata nel corso di tre sessioni
progressive ed è ora ben definita, anche se non ancora tradotta in codice:

- **Struttura del componente**: backend Python come componente custom in
  `config/custom_components/<domain>/`, con un frontend React incapsulato in
  un Web Component, distribuito come pannello nella sidebar (non come card).
  React è stato scelto deliberatamente al posto di Lit data la complessità
  dell'interfaccia di programmazione.
- **Modello dei dati**: basato su riferimenti, con stringhe di 48 caratteri
  (granularità di 30 minuti) per ogni day template. I valori `null`
  rappresentano esplicitamente l'ereditarietà dai setpoint globali. Lo
  storage usa lo Store helper di HA anziché le opzioni della config entry.
- **Risoluzione termica/temporale**: nettamente separata — l'asse temporale
  (scenario → week_template → day_template → slot → level) è indipendente
  dall'asse termico (setpoint di zona → offset di scenario → setpoint
  globale), risolti tramite una funzione pura `resolve_setpoint`.
- **Architettura degli override**: identificati e gestiti in modo
  differenziato tre tipi di override fondamentalmente distinti:
  - scritture avviate da HA: sopprimibili tramite rilevamento echo (finestra
    di 60 secondi, tolleranza deadband di 0.15 °C);
  - scritture da app esterne/unità centrale: rilevabili e con scadenza;
  - regolazioni manuali sulla manopola fisica F430/4: un offset hardware
    persistente che non può essere annullato via software — può solo essere
    compensato o mostrato nell'interfaccia.
  - Politiche di scadenza degli override definite: `next_slot`, `duration`,
    `until_scenario_change` e `sticky`.
- **Mitigazione dei conflitti con l'unità centrale 3550**: due strategie —
  appiattire il programma settimanale della 3550 stessa per eliminare i suoi
  punti di cambio, più un loop di riconciliazione watchdog che riscrive i
  setpoint desiderati ogni 10–15 minuti con scritture scaglionate (1.5 s tra
  una zona e l'altra) per non sovraccaricare il bus OpenWebNet.
- **Servizi HA**: `termo_zone.set_override` e `termo_zone.clear_override` da
  esporre presto, per consentire override guidati da automazioni prima che
  il frontend sia completo.

## Prossimi passi

- Implementare la logica di soppressione echo e la gestione della scadenza
  degli override
- Costruire la griglia UI di programmazione con interazione paint-drag
- Funzionalità UI da implementare: visualizzazione dei valori ereditati con
  la relativa fonte, vista delle dipendenze "chi usa questo template" e una
  scappatoia "duplica e scollega" per i template
- Probabile necessità di fare un fork personale dell'integrazione MyHOME,
  poiché il progetto upstream è di fatto non mantenuto dall'inizio del 2024

Roadmap dell'MVP attuale (README), propedeutica o parallela a quanto sopra:

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

## Apprendimenti e principi chiave

- L'integrazione MyHOME gestisce effettivamente i messaggi di offset locale
  dalla manopola fisica F430/4 — confermato ispezionando direttamente il
  repository GitHub.
- La riasserzione del proprio programma settimanale da parte dell'unità
  centrale 3550 è una fonte primaria di conflitti e va neutralizzata
  attivamente.
- Gli offset della manopola del termostato fisico sono una questione a
  livello hardware: nessun comando software può annullarli, solo
  compensarli o visualizzarli.
- Il rilevamento echo e la tolleranza deadband (0.15 °C) sono necessari per
  prevenire loop di feedback tra override e scritture.
- Il fatto che l'integrazione MyHOME upstream non sia mantenuta rende un
  fork personale una necessità pratica per la stabilità a lungo termine.

## Strumenti e risorse

- Framework dei componenti custom di Home Assistant (Store helper, registro
  dei servizi)
- Integrazione MyHOME di anotherjulien (GitHub) — è previsto un fork
  personale
- Protocollo OpenWebNet di BTicino (i vincoli di comunicazione sul bus
  determinano la temporizzazione delle scritture scaglionate)
- React (frontend, incapsulato come Web Component)
