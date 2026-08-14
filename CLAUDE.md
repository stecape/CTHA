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

**L'architettura in una frase.** Si parte dalle giornate tipo (30 minuti di
granularità), da quelle si costruiscono le settimane tipo, e uno scenario è la
configurazione delle zone: a ogni zona la sua settimana tipo. L'esercizio si
riduce a scegliere lo scenario attivo. Le temperature sono un insieme aperto e
si sovrascrivono lungo la gerarchia
`Global → Scenario → Zona → Week template → Day template`, ereditando dal
superiore quando non dicono nulla.

**Nota sullo stato del codice**: l'architettura target è implementata in
`custom_components/ctha/` (modello dati a riferimenti, risoluzione su due assi,
override con soppressione echo, persistenza su Store, watchdog di
riconciliazione, modifica del programma, servizi, scrittura del setpoint sul
termostato di zona) e in `frontend/` (pannello React in sidebar con la griglia
di programmazione). Resta fuori la lettura dei messaggi di offset locale
dell'F430/4, che richiede di entrare dentro MyHOME.

**CTHA non regola: programma.** Una zona *è* una entità `climate` che già
esiste — l'F430/4 esposto da MyHOME. Quel termostato misura la temperatura e
comanda la valvola; CTHA gli dice solo quale setpoint tenere, scrivendo
`climate.set_temperature`. Non esiste isteresi nel componente, e non deve
tornarci: quel livello lo copre già `generic_thermostat` di HA core, e per
questo impianto è il livello sbagliato.

Dominio dell'integrazione: `ctha`. Tipo: `helper`, `iot_class: local_push`.

## Struttura del repository

```
custom_components/ctha/
├── __init__.py        # setup/unload delle entry, avvio del runtime condiviso
├── climate.py         # CthaThermostat: entità di zona, scrittura del setpoint
├── config_flow.py     # CthaConfigFlow: nome della zona e termostato da pilotare
├── const.py           # DOMAIN, chiavi di config, gerarchia, timing, default
├── coordinator.py     # CthaCoordinator: programma, override, watchdog
├── migrate.py         # migrazione dei dati fra versioni dello Store
├── models.py          # dataclass del modello dati, serializzabili nello Store
├── override.py        # OverrideManager: policy di scadenza e soppressione echo
├── panel.py           # percorso statico del bundle + voce in sidebar
├── program.py         # funzioni pure di modifica: livelli, template, scenari
├── resolve.py         # funzioni pure: catena, livelli, resolve_setpoint
├── services.py        # registrazione dei 15 servizi del dominio
├── store.py           # CthaStore: persistenza via Store helper
├── websocket.py       # ctha/get e ctha/subscribe: lettura con push
├── frontend/          # bundle compilato del pannello — versionato, non a mano
├── manifest.json      # metadati dell'integrazione (versione, requisiti, HA minimo)
├── services.yaml      # schema dei servizi per la UI
├── strings.json       # stringhe UI sorgente per config/options flow e servizi
└── translations/      # it.json, en.json — tenute sincronizzate con strings.json
frontend/                # sorgenti del pannello: Vite + React + TypeScript
tests/                   # suite pytest sul nucleo puro (conftest.py + un file per modulo)
pytest.ini               # testpaths = tests
requirements_test.txt    # solo pytest: la suite non ha bisogno di HA
hacs.json                # metadati per la distribuzione via HACS
README.md                # documentazione utente (installazione, config, roadmap)
```

`const.py`, `models.py`, `resolve.py`, `override.py`, `program.py` e
`migrate.py` non importano `homeassistant`: sono logica pura, testabile senza
far girare HA. Tenerli così è deliberato — è la parte del componente
verificabile a costo zero, e infatti è l'unica coperta da test.

Non esiste ancora una config di sviluppo Home Assistant nel repo, né test sulla
parte che tocca HA (vedi Roadmap: `pytest-homeassistant-custom-component` è
previsto ma non presente).

## Architettura

**Una config entry = una zona; il programma è condiviso.** Store, coordinator
e servizi sono istanze uniche in `hass.data[DOMAIN]`, create con la prima
entry e smontate con l'ultima. È la ragione per cui il coordinator non è per
zona: la riconciliazione deve scaglionare le scritture di tutte le zone su un
unico bus.

- **Config entry**: creata da `CthaConfigFlow.async_step_user`, richiede `name`
  e `target_entity_id` (una entità del dominio `climate`). Una sola zona per
  termostato (`_async_abort_entries_match`). L'id della zona è l'`entry_id`.
  Non c'è options flow: non è rimasto nulla da regolare a caldo.
- **`models.py`**: `CthaData` è la radice persistita — `TemperatureLevel`,
  setpoint globali, `DayTemplate`, `WeekTemplate`, `Scenario`, `Zone`,
  `Override`, scenario attivo. Ogni dataclass ha `to_dict`/`from_dict`;
  `DayTemplate` valida in `__post_init__` **solo la forma** degli slot (48
  caratteri dell'alfabeto ammesso). Che quei caratteri corrispondano a livelli
  esistenti è una domanda sul modello intero e la fa `program.py`: validarla nel
  dataclass renderebbe illeggibile uno Store in cui un livello è stato
  eliminato.
  - **I livelli di temperatura sono dati, non costanti.** Ognuno porta un
    `char` — il carattere con cui compare nei day template, immutabile dopo la
    creazione perché è già scritto nei template — e un `color`, che serve al
    pannello: senza un colore per livello non esisterebbe una classe CSS da
    scrivere per livelli che nascono a runtime.
  - **Uno `Scenario` è la mappa `zones: zona → settimana tipo`**, non una
    settimana sola. È ciò che rende «scegliere lo scenario» l'unico gesto di
    esercizio: una zona assente dalla mappa semplicemente non è programmata lì.
- **`resolve.py`**: `resolve_chain` percorre l'asse temporale e restituisce la
  `Chain` (scenario, zona, settimana, giornata, slot); `resolve_temperature`
  percorre la gerarchia termica **su quella stessa catena**, dal più specifico
  al più generale — day template → week template → zona → scenario → globale —
  e si ferma al primo che dichiara il livello. `resolve_setpoint` li combina.
  La `Resolution` porta con sé `source`, cioè *quale livello della gerarchia ha
  deciso*: con cinque livelli di ereditarietà, un valore senza provenienza
  sarebbe inspiegabile.
  - Conseguenza da tenere presente: i template sono condivisi, quindi un
    setpoint scritto su un day template vale per **tutte** le zone che lo usano.
    È esattamente ciò che la gerarchia richiede, ma è il punto in cui è più
    facile sorprendersi.
- **`override.py`**: `OverrideManager` tiene il registro degli override,
  riconosce le eco delle nostre scritture (`note_write` / `is_echo`) e applica
  le scadenze (`is_expired`, `purge_expired`). Gli override `hardware` non
  scadono mai: nessun comando software può annullarli.
- **`program.py`**: le modifiche al programma, sempre come funzioni pure sul
  modello. Fa rispettare due regole: non si cita ciò che non esiste, e non si
  elimina ciò che è ancora citato — con `Usage` che dice *chi* sta usando
  l'elemento (la stessa informazione della vista delle dipendenze). Le
  operazioni che toccano più elementi validano tutto prima di mutare qualcosa,
  perché una modifica rifiutata a metà finirebbe comunque nello Store al
  salvataggio successivo. La scappatoia "duplica e scollega" è
  `duplicate_day_template`.
  - `set_setpoint` prende gli ambiti come argomenti alternativi e ne ammette
    **uno solo**: una temperatura sta in un punto solo della gerarchia, e
    accettarne due vorrebbe dire scriverne una e ignorare l'altra in silenzio.
  - `delete_level` si oppone solo se il livello è **dipinto** da qualche parte:
    uno slot orfano è un pezzo di programma che smette di imporre qualcosa,
    mentre una riga di setpoint che lo cita sparisce insieme a lui.
  - `ensure_zone` è chiamata dal coordinator a ogni avvio: registra la zona e le
    assegna una settimana tipo **in ogni scenario**, altrimenti una zona appena
    aggiunta resterebbe muta finché qualcuno non apre il pannello.
- **`migrate.py`**: da dizionario a dizionario, per lo Store. La v1 aveva tre
  livelli fissi e uno scenario con una sola settimana tipo; la migrazione
  ricrea quei tre livelli come dati (stessi caratteri, così i template già
  dipinti restano validi) e riscrive lo scenario come mappa delle zone. Gli
  offset non hanno più un posto: quello generale diventa una tabella di
  temperature esplicite dello scenario, le eccezioni per zona si perdono.
- **`coordinator.py`**: `CthaCoordinator` espone `target_for` (override se
  presente, altrimenti programma) e applica i setpoint tramite writer
  registrati dalle entità. Due timer: uno a ogni confine di slot (00 e 30),
  uno ogni `RECONCILE_INTERVAL` per il watchdog. `async_edit` è l'unico
  ingresso per le modifiche al programma: esegue l'operazione di `program.py`,
  persiste e programma la riscrittura delle zone. La riscrittura è debounced
  (`APPLY_DEBOUNCE_SECONDS`) perché una griglia dipinta col mouse produce
  decine di modifiche e ogni riscrittura completa occupa il bus per 1.5 s per
  zona.
- **`CthaThermostat` (climate.py)**: entità di zona, sovrapposta al termostato
  reale. È l'adattatore fra il programma e il bus.
  - Rispecchia dal termostato pilotato ciò che è suo: temperatura misurata,
    acceso/spento, `hvac_action`. Non li tiene in stato proprio, li legge —
    per questo non serve più `RestoreEntity`.
  - Il `target_temperature` invece è **quello che il programma vuole**: la
    differenza fra questo e il valore sul bus è il segnale che qualcuno ha
    messo mano alla zona.
  - `_async_apply_setpoint` è il writer registrato nel coordinator: chiama
    `climate.set_temperature` sul termostato, ma **solo se il valore è diverso
    da quello già presente** oltre `WRITE_DEADBAND`. Senza quel confronto il
    watchdog riscriverebbe ogni 12 minuti valori già corretti, per sempre. Se
    la zona è spenta non scrive: riaccenderla non l'ha chiesto nessuno.
  - `_async_note_external`: ogni cambio del setpoint sul termostato che non sia
    un'eco nostra diventa un override `external` con policy `next_slot`. Dal
    bus la manopola, l'app e la centrale arrivano identiche — l'unica cosa
    dicibile è "non l'ho scritto io", e tenerlo fino al prossimo slot è meno
    peggio sia dell'ignorarlo sia del litigarci ogni minuto. Se a riasserire è
    la 3550, il rimedio vero resta appiattirne il programma.
  - `async_set_temperature` e `async_set_preset_mode` creano un **override**
    (policy `next_slot`), non modificano il programma.
  - `async_set_hvac_mode` inoltra al termostato; riaccendendo si preferisce
    `heat` ad `auto`, perché su BTicino `auto` significa "segui il programma
    della centrale", cioè proprio ciò che CTHA sta sostituendo.
  - I preset **sono** i livelli di temperatura, quindi `preset_modes` è una
    property e non una costante di classe: l'elenco cambia quando l'utente crea
    o elimina un livello. Forzare un preset risolve i gradi lungo la catena
    corrente della zona (`resolve_level_temperature`), non sul globale.

Tutte le costanti condivise (chiavi di config, livelli, timing, default,
limiti setpoint) vivono in `const.py`: aggiungere nuove chiavi lì, non come
stringhe sparse nel codice.

## Il pannello

`websocket.py` **legge**, i servizi **scrivono**. Il pannello non ha comandi
websocket di scrittura apposta: validazione e integrità referenziale stanno già
nei servizi, e duplicarle vorrebbe dire mantenerne due copie che prima o poi
divergono. Lo snapshot di `ctha/subscribe` unisce il modello persistito e il
`runtime` per zona (livello risolto, provenienza, override), perché il secondo
è il risultato di `resolve_setpoint` e il frontend non può ricavarlo senza
reimplementare la risoluzione in TypeScript.

`panel.py` serve il bundle da un percorso statico e registra la voce in
sidebar. Due dettagli non ovvi: la rotta statica si registra una volta sola per
processo (le rotte di aiohttp non si rimuovono, quindi il flag è a livello di
modulo), e l'url del modulo porta `?v=<versione del manifest>` perché senza il
browser continuerebbe a servire il bundle vecchio dopo un aggiornamento.

Il frontend è React dentro un Web Component su shadow root (`frontend/src/`):

- `main.tsx` definisce `<ctha-panel>`; HA assegna la proprietà `hass` a ogni
  cambio di stato della casa, quindi la sottoscrizione websocket passa da una
  ref e si apre una volta sola (`App.tsx`).
- `model.ts` sono funzioni pure che rifanno in TypeScript pezzi di
  `program.py` — usanze di un template, esito di una pennellata, catena di
  ereditarietà. La duplicazione è voluta: serve a mostrare l'effetto *prima*
  del giro sul backend. La verità resta il backend, che rifiuta ciò che non è
  ammissibile.
  - `ancestors()` mostra la catena **tipica**, non quella vera: un week template
    non ha un solo genitore, dipende da quale zona lo segue e in quale scenario.
    Si prende lo scenario attivo e la prima zona che ci passa, perché è la
    situazione che l'utente sta guardando mentre programma. La risoluzione vera
    resta quella del backend, che il pannello rilegge dal `runtime`.
- I colori dei livelli arrivano **inline dal modello**, non dal CSS: livelli che
  nascono a runtime non possono avere una classe scritta a mano nel foglio di
  stile.
- `WeekGrid.tsx` ascolta il puntatore sulla riga, non sulle celle: la posizione
  diventa un indice di slot con un calcolo sulla larghezza, così un
  trascinamento resta *un* intervallo — la forma che `paint_slots` si aspetta.
  Lo stato del trascinamento vive anche in una ref, perché il rilascio può
  arrivare prima che React abbia applicato lo stato della pressione.
- Il momento in cui si chiede "modifica per tutti o scollega?" è la pennellata
  su una giornata tipo condivisa (`ProgramTab.tsx`): è lì che l'utente scopre
  la condivisione, ed è lì che ha senso offrire la scappatoia.

**Il bundle compilato è versionato.** HACS distribuisce il repository così
com'è: dopo aver toccato `frontend/src/` bisogna rifare `npm run check` e
committare anche `custom_components/ctha/frontend/ctha-panel.js`.

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

Il frontend si compila e si prova con:

```bash
cd frontend && npm install && npm run check
```

`npm run check` fa tre cose: `tsc`, il build Vite, e `test/smoke.mjs`, che
monta il bundle in jsdom con un `hass` finto e verifica che la griglia si
disegni e che una pennellata su un template condiviso apra il dialogo invece di
scrivere. Non sostituisce la prova dentro HA — geometria, temi e bus non
esistono in jsdom — ma intercetta le rotture grosse.

`tests/conftest.py` registra `ctha` in `sys.modules` come package fittizio con
il solo `__path__`: è ciò che permette di importare `ctha.models` senza
eseguire l'`__init__.py` vero, che importerebbe `homeassistant`. Un modulo
nuovo è testabile qui **solo se non importa HA**; se lo importa, il suo test
va rimandato a `pytest-homeassistant-custom-component`.

Per i moduli che HA lo importano davvero resta pyflakes, che lavora sull'AST e
non esegue nulla:

```bash
.venv/Scripts/python -m pyflakes custom_components/ctha tests
```

Non verifica la logica, ma prende import inutilizzati e nomi inesistenti anche
lì dove non si può importare niente. Vale la pena lanciarlo dopo ogni modifica
a `climate.py`, `coordinator.py`, `services.py`, `websocket.py`, `panel.py`.

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
  card) — *fatto* (vedi «Il pannello»). React è stato scelto deliberatamente al
  posto di Lit data la complessità dell'interfaccia di programmazione.
- **Modello dei dati** — *fatto* (`models.py`): basato su riferimenti, con
  stringhe di 48 caratteri (granularità di 30 minuti) per ogni day template.
  L'assenza di un livello da una tabella di setpoint rappresenta esplicitamente
  l'ereditarietà da chi sta sopra. Lo storage usa lo Store helper di HA
  (`store.py`) anziché le opzioni della config entry; è alla versione 2, con
  migrazione dalla 1 in `migrate.py`.
- **Risoluzione termica/temporale** — *fatto* (`resolve.py`): l'asse temporale
  (scenario attivo → settimana tipo della zona → giornata tipo → slot → livello)
  è indipendente dall'asse termico, che è la gerarchia
  `global → scenario → zona → week template → day template` percorsa dal basso.
  Entrambi passano dalla stessa `Chain`, risolta da `resolve_setpoint`.
- **Livelli di temperatura definibili dall'utente** — *fatto*: si creano,
  rinominano, ricolorano ed eliminano come i template. Alta, media, bassa e
  antigelo esistono solo come contenuto di `CthaData.default()`.
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
- **Servizi HA** — *fatti*: 15 servizi, elencati nel README. Oltre agli
  override coprono livelli di temperatura (`set_level`, `delete_level`),
  setpoint per ambito (`set_setpoint`), giornate tipo (`set_day_template`,
  `paint_slots`, `duplicate_day_template`, `delete_day_template`), settimane
  tipo e scenari. Attenzione: il nome storico in progettazione era
  `termo_zone.*`, ma il dominio dell'integrazione è `ctha` e i servizi devono
  starci dentro. `paint_slots` prende un intervallo e non uno slot proprio
  perché è la primitiva su cui poggia il paint-drag della griglia.
- **Interfaccia di programmazione** — *fatta*: quattro viste (Programma,
  Scenari, Temperature, Zone), griglia paint-drag, editor della gerarchia con
  valore proprio / ereditato / in vigore, vista delle dipendenze e scappatoia
  "duplica e scollega" al momento in cui serve.
- **Adattatore verso il bus** — *fatto a metà*: la scrittura dei setpoint passa
  per `climate.set_temperature` sull'entità MyHOME della zona, che è tutto ciò
  che serve per programmare. Manca solo la lettura dei messaggi di offset
  locale, l'unica via per marcare un override come `hardware` anziché
  `external`.

## Prossimi passi

- Lettura dei messaggi di offset locale dell'F430/4, per distinguere la manopola
  fisica dalle altre sorgenti esterne. È l'ultimo pezzo che richiede di entrare
  dentro MyHOME
- Probabile necessità di fare un fork personale dell'integrazione MyHOME,
  poiché il progetto upstream è di fatto non mantenuto dall'inizio del 2024
- Test con `pytest-homeassistant-custom-component` per la parte che tocca HA:
  coordinator, entità climate, registrazione di servizi, websocket e pannello.
  Il nucleo puro è già coperto da `tests/`, il bundle da `npm run smoke`
- Prova del pannello dentro Home Assistant vero: finora è verificato solo in
  jsdom, quindi geometria del trascinamento, temi e permessi non sono stati
  visti funzionare

## Apprendimenti e principi chiave

- **MyHOME espone ogni zona come entità `climate`, non come sensore più
  attuatore.** Il gateway F454 è l'integrazione; sotto ci sono i dispositivi
  F430/4, e ciascuno diventa una entità `climate` con `current_temperature`,
  `temperature`, `hvac_action` e le modalità spento/automatico/caldo. Non
  esistono `sensor` separati con `device_class: temperature`. La prima versione
  del config flow li chiedeva ed era inconfigurabile su un impianto reale: il
  menù delle entità restava vuoto. Verificato sull'impianto di Stefano il
  13 agosto 2026.
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
