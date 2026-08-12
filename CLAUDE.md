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

**Nota sullo stato del codice**: il backend dell'architettura target è
implementato in `custom_components/ctha/` — modello dati a riferimenti,
risoluzione su due assi, override con soppressione echo, persistenza su Store,
watchdog di riconciliazione, modifica del programma e servizi. Restano fuori
dal codice il frontend React e l'adattatore specifico BTicino/MyHOME:
l'attuazione avviene ancora tramite isteresi su un attuatore generico
(`switch`, `input_boolean` o `climate`), che è il punto in cui si innesterà la
scrittura dei setpoint sul bus OpenWebNet.

Dominio dell'integrazione: `ctha`. Tipo: `helper`, `iot_class: local_push`.

## Struttura del repository

```
custom_components/ctha/
├── __init__.py        # setup/unload delle entry, avvio del runtime condiviso
├── climate.py         # CthaThermostat: entità di zona, attuazione a isteresi
├── config_flow.py     # CthaConfigFlow (setup iniziale) e CthaOptionsFlow (tolleranze)
├── const.py           # DOMAIN, chiavi di config, livelli, timing, default
├── coordinator.py     # CthaCoordinator: programma, override, watchdog
├── models.py          # dataclass del modello dati, serializzabili nello Store
├── override.py        # OverrideManager: policy di scadenza e soppressione echo
├── program.py         # funzioni pure di modifica: template, scenari, setpoint
├── resolve.py         # funzioni pure: slot, livelli, resolve_setpoint
├── services.py        # registrazione dei 13 servizi del dominio
├── store.py           # CthaStore: persistenza via Store helper
├── manifest.json      # metadati dell'integrazione (versione, requisiti, HA minimo)
├── services.yaml      # schema dei servizi per la UI
├── strings.json       # stringhe UI sorgente per config/options flow e servizi
└── translations/      # it.json, en.json — tenute sincronizzate con strings.json
tests/                   # suite pytest sul nucleo puro (conftest.py + un file per modulo)
pytest.ini               # testpaths = tests
requirements_test.txt    # solo pytest: la suite non ha bisogno di HA
hacs.json                # metadati per la distribuzione via HACS
README.md                # documentazione utente (installazione, config, roadmap)
```

`const.py`, `models.py`, `resolve.py`, `override.py` e `program.py` non
importano `homeassistant`: sono logica pura, testabile senza far girare HA.
Tenerli così è deliberato — è la parte del componente verificabile a costo
zero, e infatti è l'unica coperta da test.

Non esiste ancora una config di sviluppo Home Assistant nel repo, né test sulla
parte che tocca HA (vedi Roadmap: `pytest-homeassistant-custom-component` è
previsto ma non presente).

## Architettura

**Una config entry = una zona; il programma è condiviso.** Store, coordinator
e servizi sono istanze uniche in `hass.data[DOMAIN]`, create con la prima
entry e smontate con l'ultima. È la ragione per cui il coordinator non è per
zona: la riconciliazione deve scaglionare le scritture di tutte le zone su un
unico bus.

- **Config entry**: creata da `CthaConfigFlow.async_step_user`, richiede
  `name`, `sensor_entity_id` (sensore con `device_class: temperature`) e
  `heater_entity_id` (dominio `switch`, `input_boolean` o `climate`). Una sola
  zona per attuatore (`_async_abort_entries_match`). L'id della zona è
  l'`entry_id`.
- **Options flow**: `CthaOptionsFlow` permette di rivedere a caldo
  `cold_tolerance` e `hot_tolerance` (isteresi, default 0.3 °C ciascuna).
- **`models.py`**: `CthaData` è la radice persistita — setpoint globali,
  `DayTemplate`, `WeekTemplate`, `Scenario`, `Zone`, `Override`, scenario
  attivo. Ogni dataclass ha `to_dict`/`from_dict`; `DayTemplate` valida in
  `__post_init__` che gli slot siano 48 caratteri noti, così un template
  malformato non arriva mai allo Store.
- **`resolve.py`**: `resolve_level` percorre l'asse temporale,
  `resolve_temperature` quello termico, `resolve_setpoint` li combina.
  Restituiscono una `Resolution` che porta con sé la provenienza (`zone` o
  `global`), perché la UI deve poter mostrare *da dove* viene un valore.
- **`override.py`**: `OverrideManager` tiene il registro degli override,
  riconosce le eco delle nostre scritture (`note_write` / `is_echo`) e applica
  le scadenze (`is_expired`, `purge_expired`). Gli override `hardware` non
  scadono mai: nessun comando software può annullarli.
- **`program.py`**: le modifiche al programma, sempre come funzioni pure sul
  modello. Fa rispettare due regole: non si cita ciò che non esiste, e non si
  elimina ciò che è ancora citato — con `Usage` che dice *chi* sta usando
  l'elemento (la stessa informazione della futura vista delle dipendenze). Le
  operazioni che toccano più elementi validano tutto prima di mutare qualcosa,
  perché una modifica rifiutata a metà finirebbe comunque nello Store al
  salvataggio successivo. La scappatoia "duplica e scollega" è
  `duplicate_day_template`.
- **`coordinator.py`**: `CthaCoordinator` espone `target_for` (override se
  presente, altrimenti programma) e applica i setpoint tramite writer
  registrati dalle entità. Due timer: uno a ogni confine di slot (00 e 30),
  uno ogni `RECONCILE_INTERVAL` per il watchdog. `async_edit` è l'unico
  ingresso per le modifiche al programma: esegue l'operazione di `program.py`,
  persiste e programma la riscrittura delle zone. La riscrittura è debounced
  (`APPLY_DEBOUNCE_SECONDS`) perché una griglia dipinta col mouse produce
  decine di modifiche e ogni riscrittura completa occupa il bus per 1.5 s per
  zona.
- **`CthaThermostat` (climate.py)**: entità di zona.
  - Estende `CoordinatorEntity` + `ClimateEntity` + `RestoreEntity`.
  - Non decide più il setpoint: lo riceve dal coordinator tramite il writer
    `_async_apply_setpoint`. Qui resta solo l'attuazione.
  - `async_set_temperature` e `async_set_preset_mode` creano un **override**
    (policy `next_slot`), non modificano il programma.
  - Logica a isteresi in `_async_control_heating`: accende l'attuatore se
    `current <= target - cold_tolerance`, lo spegne se
    `current >= target + hot_tolerance`; se `hvac_mode == OFF` lo spegne e
    basta.
  - `_async_set_heater` chiama `turn_on`/`turn_off` sul dominio
    dell'attuatore solo se lo stato deve effettivamente cambiare (evita
    chiamate ridondanti al servizio).
  - I preset corrispondono ai livelli: `comfort`, `eco`, `antifreeze`.

Tutte le costanti condivise (chiavi di config, livelli, timing, default,
limiti setpoint) vivono in `const.py`: aggiungere nuove chiavi lì, non come
stringhe sparse nel codice.

## Convenzioni di codice

- Python moderno per Home Assistant: `from __future__ import annotations`,
  type hints ovunque, entità asincrone (`async def async_...`).
- Docstring brevi in italiano su ogni funzione/metodo/classe pubblica, che
  spiegano il "perché"/comportamento, non la mera ripetizione del nome.
- Nessun commento superfluo: seguire lo stile esistente (docstring sì,
  commenti inline solo se il codice non è auto-esplicativo).
- Le stringhe UI vanno aggiunte sia in `strings.json` sia in
  `translations/it.json` e `translations/en.json`, mantenendo le chiavi
  allineate. Un servizio nuovo tocca cinque punti: `const.py` (nome e attributi),
  `services.py` (schema e handler), `services.yaml` (selettori), `strings.json`
  e le due traduzioni.
- Bump di `version` in `manifest.json` quando si rilascia una modifica
  utente-visibile (HACS legge questo campo).

## Sviluppo e test

La suite copre il nucleo puro e gira senza Home Assistant:

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements_test.txt
.venv/Scripts/python -m pytest
```

`tests/conftest.py` registra `ctha` in `sys.modules` come package fittizio con
il solo `__path__`: è ciò che permette di importare `ctha.models` senza
eseguire l'`__init__.py` vero, che importerebbe `homeassistant`. Un modulo
nuovo è testabile qui **solo se non importa HA**; se lo importa, il suo test
va rimandato a `pytest-homeassistant-custom-component`.

Non c'è ancora un ambiente HA di sviluppo nel repo. Per validare a mano le
parti che toccano HA:

1. Copiare/linkare `custom_components/ctha` in
   `<config_home_assistant>/custom_components/`.
2. Riavviare Home Assistant e aggiungere l'integrazione da
   *Impostazioni → Dispositivi e servizi*.

## Architettura target — cosa è già in codice

L'architettura completa è stata progettata nel corso di tre sessioni
progressive. Stato attuale di ciascun pezzo:

- **Struttura del componente**: backend Python come componente custom in
  `config/custom_components/<domain>/` — *fatto*. Frontend React incapsulato
  in un Web Component, distribuito come pannello nella sidebar (non come
  card) — *da fare*. React è stato scelto deliberatamente al posto di Lit
  data la complessità dell'interfaccia di programmazione.
- **Modello dei dati** — *fatto* (`models.py`): basato su riferimenti, con
  stringhe di 48 caratteri (granularità di 30 minuti) per ogni day template.
  I valori `null` rappresentano esplicitamente l'ereditarietà dai setpoint
  globali. Lo storage usa lo Store helper di HA (`store.py`) anziché le
  opzioni della config entry.
- **Risoluzione termica/temporale** — *fatto* (`resolve.py`): l'asse temporale
  (scenario → week_template → day_template → slot → level) è indipendente
  dall'asse termico (setpoint di zona → offset di scenario → setpoint
  globale), risolti tramite la funzione pura `resolve_setpoint`.
- **Architettura degli override** — *fatta* (`override.py`), con i tre tipi
  distinti:
  - scritture avviate da HA: soppresse tramite rilevamento echo (finestra di
    60 secondi, tolleranza deadband di 0.15 °C);
  - scritture da app esterne/unità centrale: rilevabili e con scadenza;
  - regolazioni manuali sulla manopola fisica F430/4: un offset hardware
    persistente che non può essere annullato via software — può solo essere
    compensato o mostrato nell'interfaccia. Nel codice: `source = hardware`,
    mai soggetto a scadenza.
  - Politiche di scadenza implementate: `next_slot`, `duration`,
    `until_scenario_change` e `sticky`.
- **Mitigazione dei conflitti con l'unità centrale 3550**: il loop di
  riconciliazione watchdog è *fatto* (`coordinator.py`, `RECONCILE_INTERVAL`
  = 12 min, scritture scaglionate di `WRITE_STAGGER_SECONDS` = 1.5 s).
  L'appiattimento del programma settimanale della 3550 stessa è *da fare* e
  richiede l'adattatore MyHOME.
- **Servizi HA** — *fatti*: 13 servizi, elencati nel README. Oltre agli
  override coprono giornate tipo (`set_day_template`, `paint_slots`,
  `duplicate_day_template`, `delete_day_template`), settimane tipo, scenari e
  setpoint. Attenzione: il nome storico in progettazione era `termo_zone.*`, ma
  il dominio dell'integrazione è `ctha` e i servizi devono starci dentro.
  `paint_slots` prende un intervallo e non uno slot proprio perché è la
  primitiva su cui poggerà il paint-drag della griglia.

## Prossimi passi

- Costruire la griglia UI di programmazione con interazione paint-drag, sopra i
  servizi già esistenti
- Funzionalità UI da implementare: visualizzazione dei valori ereditati con
  la relativa fonte (già esposta negli attributi dell'entità come
  `setpoint_source`) e vista delle dipendenze "chi usa questo template"
  (i dati arrivano da `program.day_template_usages` e
  `program.week_template_usages`)
- Adattatore MyHOME/BTicino: scrittura dei setpoint sul bus al posto
  dell'isteresi generica, e lettura dei messaggi di offset locale per
  registrare gli override `hardware`
- Probabile necessità di fare un fork personale dell'integrazione MyHOME,
  poiché il progetto upstream è di fatto non mantenuto dall'inizio del 2024
- Durata minima di ciclo per proteggere la caldaia (`CONF_MIN_CYCLE_DURATION`
  è definita in `const.py` ma non ancora usata in `climate.py`)
- Test con `pytest-homeassistant-custom-component` per la parte che tocca HA:
  coordinator, entità climate, registrazione dei servizi. Il nucleo puro è già
  coperto da `tests/`

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
