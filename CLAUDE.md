# CLAUDE.md

Guida di riferimento per Claude Code quando lavora su questo repository.

## Scopo e contesto

Stefano sta sviluppando un componente custom per Home Assistant per gestire
un impianto di riscaldamento a pavimento radiante multi-zona. L'impianto
prevede 10 zone BTicino integrate tramite l'integrazione MyHOME (di
anotherjulien), con 9 zone attive più un'unità centrale (#0), tutte
configurate come `standalone: False`.

**Chi fa cosa nell'impianto**, perché ogni scelta di CTHA discende da qui:

- **sonde 4691** — una per zona, misurano la temperatura e portano la manopola
  con l'offset locale. Sono la «zona» che MyHOME espone come entità `climate`;
- **attuatori F430/4** — comandano le testine motorizzate delle valvole;
- **centrale 3550** — è il **regolatore**: confronta la misura delle sonde con
  il setpoint e pilota le testine attraverso gli attuatori. Tutte le zone sono
  in configurazione `CEN`, cioè le sonde sono sue.

La conseguenza da tenere sempre presente: **la 3550 non è solo una fonte di
conflitto, è il regolatore da cui CTHA dipende.** Non si può toglierla dal giro
— senza di lei nessuno comanda le testine. Il conflitto con lei non è su *chi
regola*, è solo su *quale setpoint*, e riguarda unicamente il suo programma
settimanale che riasserisce i propri valori ai propri confini orari.

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
riconciliazione, modifica del programma, servizi, scrittura del setpoint sulla
zona) e in `frontend/` (pannello React in sidebar con la griglia di
programmazione). Resta fuori la lettura dei messaggi di offset locale della
sonda 4691, che richiede di entrare dentro MyHOME.

**CTHA non regola: programma.** Una zona *è* una entità `climate` che già
esiste — quella che MyHOME espone per la zona BTicino. Misura e regolazione
esistono già nell'impianto: la sonda misura, la 3550 confronta e comanda le
testine. Quello che manca è *quale setpoint tenere e quando*, ed è l'unica cosa
che CTHA fornisce, scrivendo `climate.set_temperature`. Non esiste isteresi nel
componente, e non deve tornarci: qui la farebbe due volte, perché la centrale la
sta già facendo.

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
diagnostics/             # strumenti standalone, indipendenti da HA (vedi diagnostics/README.md)
requirements_diagnostics.txt  # dipendenze dei soli strumenti diagnostici
todo.md                  # checklist operativa degli step immediati in corso
.github/workflows/ci.yml # test, lint, build del pannello, bundle allineato
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
  - Le policy che scadono su un *cambiamento* non hanno un istante da
    calcolare: `Override` memorizza com'era il mondo alla creazione
    (`scenario_id`, `level`) e `is_expired` confronta. Per questo `purge_expired`
    risolve da sé il livello di ogni zona — chi lo chiama è un timer, e non sa
    in che fascia si trovi ciascuna.
  - `until_level_change` è la policy di **ogni mano sul termostato**: manopola,
    pannello, `set_temperature` sull'entità. Vale finché il programma tiene lo
    stesso livello, che è ciò che l'utente intende quando alza la temperatura
    alle 07:05. Il costo è che una riasserzione della 3550 — indistinguibile
    dalla manopola, dal bus arrivano uguali — dura anch'essa quanto la fascia.
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
- **`coordinator.py`**: `CthaCoordinator` espone `target_for` (l'override
  ancora valido se c'è, altrimenti programma) e applica i setpoint tramite
  writer registrati dalle entità. Due timer: uno a ogni confine di slot (00 e
  30), uno ogni `RECONCILE_INTERVAL` per il watchdog. `async_edit` è l'unico
  ingresso per le modifiche al programma: esegue l'operazione di `program.py`,
  persiste e programma la riscrittura delle zone. La riscrittura è debounced
  (`APPLY_DEBOUNCE_SECONDS`) perché una griglia dipinta col mouse produce
  decine di modifiche e ogni riscrittura completa occupa il bus per 1.5 s per
  zona.
  - **Ogni istante che entra nel nucleo puro passa da `_as_local`.** I timer di
    HA non consegnano la stessa cosa: `async_track_time_change` chiama con
    l'ora locale, `async_track_time_interval` e `async_call_later` con UTC.
    `resolve.py` legge `hour`, `minute` e `weekday` grezzi — non conosce il
    fuso di HA e non può conoscerlo — quindi un istante UTC gli fa risolvere la
    fascia sbagliata, e dopo mezzanotte anche la giornata tipo di ieri. È il
    difetto che faceva rimbalzare le zone fra due valori: il tick di slot
    scriveva la fascia giusta, il watchdog quella di due ore prima, e i due si
    sovrascrivevano a vicenda ogni dodici minuti.
  - `target_for` **verifica la scadenza**, non si limita a leggere il registro:
    `purge_expired` passa solo ai confini di slot, quindi fino a mezz'ora un
    override decaduto resta scritto nel modello. `OverrideManager.get` dice
    cos'è registrato, `active` cos'è ancora valido — chi decide un setpoint
    vuole il secondo.
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
  - **Scrive, verifica, riprova** (`WRITE_ATTEMPTS`). La chiamata al servizio
    che riesce non dimostra che il setpoint sia arrivato: ha consegnato il
    comando al gateway, e sul bus da lì in poi può perdersi in silenzio.
    L'unica prova è che il termostato riporti il valore chiesto, e per averla
    bisogna aspettare (`WRITE_VERIFY_SECONDS`), perché torna come cambio di
    stato e non come esito della chiamata. Un lock per zona impedisce che tick
    di slot e watchdog intreccino due cicli sullo stesso termostato,
    verificandosi a vicenda il valore dell'altro.
  - **L'eco si annota dove il comando parte davvero**, cioè dentro
    `_async_apply_setpoint`, accanto alla chiamata al servizio e a ogni
    ritentativo. Annotarla nel coordinator, prima di invocare il writer,
    significava aspettare l'eco di scritture mai partite — il writer tace se il
    valore è già sul bus o se la zona è spenta — e per tutta `ECHO_WINDOW`
    scambiare per propria una mano altrui che portasse la zona proprio a quel
    valore: nessun override, nessun log.
  - `_async_note_external`: ogni cambio del setpoint sul termostato che non sia
    un'eco nostra diventa un override `external` con policy
    `until_level_change`. Dal bus la manopola, l'app e la centrale arrivano
    identiche — l'unica cosa dicibile è "non l'ho scritto io", e tenerlo per la
    fascia in corso è meno peggio sia dell'ignorarlo sia del litigarci ogni
    minuto. Se a riasserire è la 3550, il rimedio vero resta appiattirne il
    programma.
  - `async_set_temperature` e `async_set_preset_mode` creano un **override**
    (policy `until_level_change`), non modificano il programma.
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
  - Su un telefono quel gesto ne ha un altro addosso: la griglia è più larga
    dello schermo, e lo stesso dito dovrebbe anche scorrerla. I due
    trascinamenti sono indistinguibili, quindi la scelta è esplicita —
    l'interruttore **«Scorri / Dipingi»**, che compare solo dove esiste un dito
    (`navigator.maxTouchPoints`) e parte da «Scorri». Il mouse non ci passa: col
    mouse il trascinamento non ha mai scrollato niente, quindi dipinge sempre.
  - Il `touch-action` è la metà CSS della stessa decisione, e va tenuta in
    accordo con la guardia in `onPointerDown`: la riga dichiara `pan-x pan-y`
    finché il dito scorre e `none` solo in «Dipingi», perché un trascinamento
    interrotto dallo scorrimento non arriverebbe mai in fondo. Per lo stesso
    motivo `.grid` dichiara **entrambi** gli assi: con il solo `pan-y` il
    browser rifiutava di scorrere la griglia proprio nel verso in cui è
    tagliata.
  - Sotto i 700 px il nome del giorno e il menù della giornata tipo passano
    *sopra* la riga: la colonna dei giorni si mangiava metà della larghezza, ed
    era la metà che serve alle fasce. L'etichetta resta `sticky` a sinistra,
    altrimenti scorrendo verso sera si perde di vista quale riga si sta
    dipingendo.
  - **Su mobile la griglia è larga 960 px, non quanto ci sta.** A 520 px una
    mezz'ora era più stretta di un polpastrello e per prendere la fascia giusta
    bisognava mirare; a 960 px ogni slot è una tacca da 20 px. Si scorre di più,
    ma si dipinge quello che si voleva dipingere — ed è il motivo per cui il
    breakpoint *allarga* invece di comprimere.
  - Il righello delle ore porta una tacca ogni due ore (`HOUR_LABELS` in
    `WeekGrid.tsx`, `repeat(12, 1fr)` in `.hours`): i due numeri vanno tenuti in
    accordo, altrimenti le etichette non cadono più sui confini degli slot che
    dicono di marcare. Il righello però resta in cima e sparisce appena si
    scorre, quindi le celle marcano da sé le quattro parti della giornata
    (`.cell.quarter`, ogni sei ore): senza quelle, a metà settimana non si
    saprebbe più a che ora si sta dipingendo.
- Il momento in cui si chiede "modifica per tutti o scollega?" è la pennellata
  su una giornata tipo condivisa (`ProgramTab.tsx`): è lì che l'utente scopre
  la condivisione, ed è lì che ha senso offrire la scappatoia.
- `Setpoints.tsx` è **un** editor usato da cinque posti. Le sovrascritture si
  modificano sull'istanza — pulsante «Temperature» accanto all'elemento, col
  numero di quelle proprie — e non da un menù «scegli il punto della gerarchia»:
  quel menù sarebbe più compatto ma direbbe che le temperature stanno altrove,
  mentre appartengono all'elemento. La vista Temperature tiene solo ciò che non
  è di nessun elemento (quali livelli esistono, quanto valgono alla radice) più
  l'elenco di *dove* è stato scritto qualcosa, che altrimenti si scoprirebbe
  aprendo gli elementi uno per uno.
  - Attenzione a un'ambiguità che la UI deve dire a voce: il pulsante di una
    zona compare anche dentro la tabella di uno scenario, ma le temperature di
    una zona sono **della zona** e valgono in tutti gli scenari — solo la
    settimana tipo è un'assegnazione di quello scenario.

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

### La CI

`.github/workflows/ci.yml` gira su ogni push a `main`, su ogni pull request e a
mano (`workflow_dispatch`). Sono gli stessi comandi di sopra, in due job
paralleli — nessun passo che non si possa rifare in locale, di proposito:

- **`python`** — `pytest` sul nucleo puro, poi
  `pyflakes custom_components/ctha tests diagnostics`. Il perimetro di pyflakes
  è più largo di quello dei test apposta: né Home Assistant né `OWNd` sono
  installati nel job, e pyflakes è l'unico controllo che arriva dove l'import
  fallirebbe. È anche il motivo per cui `diagnostics/` è nell'elenco pur non
  avendo test.
- **`frontend`** — `npm ci` e `npm run check` (tsc, build Vite, smoke in
  jsdom), e infine **il controllo che il bundle committato sia aggiornato**:
  se il build ha modificato `custom_components/ctha/frontend/ctha-panel.js`,
  il job fallisce.

Quel controllo finale è la ragione principale per cui la CI esiste. Il bundle è
versionato perché HACS distribuisce il repository così com'è, quindi un
sorgente committato senza il bundle rifatto non rompe nulla in locale — rompe
l'installazione di chi aggiorna da HACS, che si ritrova il pannello vecchio
senza un errore da nessuna parte. Se il job segnala il disallineamento, la
correzione è sempre la stessa: `cd frontend && npm run check` e committare
anche il bundle.

Le versioni di Node e Python nel workflow sono fissate (22 e 3.13): il bundle è
confrontato byte a byte, quindi cambiarle a caso è il modo più rapido di far
fallire il controllo per un motivo che non c'entra con la modifica.

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
  - regolazioni manuali sulla manopola della sonda 4691: un offset hardware
    persistente che non può essere annullato via software — può solo essere
    compensato o mostrato nell'interfaccia. Nel codice: `source = hardware`,
    mai soggetto a scadenza.
  - Politiche di scadenza implementate: `until_level_change` (quella dei gesti
    manuali), `next_slot`, `duration`, `until_scenario_change` e `sticky`.
- **Mitigazione dei conflitti con l'unità centrale 3550**: il loop di
  riconciliazione watchdog è *fatto* (`coordinator.py`, `RECONCILE_INTERVAL`
  = 12 min, scritture scaglionate di `WRITE_STAGGER_SECONDS` = 1.5 s). Resta
  *eventualmente* da fare la parte che non è software: mettere la 3550 in una
  modalità che **regoli senza programmare**, cioè Manuale su tutte le zone
  (manuale d'installazione §5.1.2, «temperatura fissa senza fasce orarie»). Il
  suo programma settimanale sarebbe l'unica cosa a riasserire setpoint ai
  propri confini orari; la sua regolazione, invece, serve e va lasciata
  lavorare. Da tenere presente però che la trace del 15 agosto 2026 **non ha
  registrato una sola scrittura della centrale**: il conflitto è plausibile ma
  non ancora osservato, e va misurato prima di intervenire.
- **Servizi HA** — *fatti*: 15 servizi, elencati nel README. Oltre agli
  override coprono livelli di temperatura (`set_level`, `delete_level`),
  setpoint per ambito (`set_setpoint`), giornate tipo (`set_day_template`,
  `paint_slots`, `duplicate_day_template`, `delete_day_template`), settimane
  tipo e scenari. Attenzione: il nome storico in progettazione era
  `termo_zone.*`, ma il dominio dell'integrazione è `ctha` e i servizi devono
  starci dentro. `paint_slots` prende un intervallo e non uno slot proprio
  perché è la primitiva su cui poggia il paint-drag della griglia.
- **Interfaccia di programmazione** — *fatta*: quattro viste (Programma,
  Scenari, Temperature, Zone), griglia paint-drag, temperature modificabili
  sull'istanza che le sovrascrive, vista delle dipendenze e scappatoia
  "duplica e scollega" al momento in cui serve.
- **Adattatore verso il bus** — *fatto a metà*: la scrittura dei setpoint passa
  per `climate.set_temperature` sull'entità MyHOME della zona, che è tutto ciò
  che serve per programmare. Manca solo la lettura dei messaggi di offset
  locale, l'unica via per marcare un override come `hardware` anziché
  `external`.

## Prossimi passi

Il rimbalzo di setpoint che occupava questa sezione **è stato diagnosticato e
corretto** il 15 agosto 2026 — non era la 3550, era CTHA. Vedi «Apprendimenti»
per la trace e il metodo; `todo.md` conserva l'esito della checklist.

- Lettura dei messaggi di offset locale della sonda 4691, per distinguere la
  manopola fisica dalle altre sorgenti esterne. È l'ultimo pezzo che richiede di
  entrare dentro MyHOME
- Riverificare in stagione se la 3550 riasserisca davvero il proprio programma.
  Nella trace di agosto **non ha scritto un solo setpoint in un'ora e mezza**,
  quindi il conflitto con la centrale resta un'ipotesi non dimostrata. Se si
  ripresenta, la mossa a costo zero è metterla in Manuale su tutte le zone; ma
  non va fatto preventivamente, perché nel frattempo si è visto che il rimbalzo
  attribuito a lei aveva un'altra causa
- Valutare la riconfigurazione delle sonde come **termostato hotel** (`TYPE`
  sulla sonda): in quella modalità la sonda regola da sé i propri attuatori, non
  esiste centrale che riasserisca, e il comando da remoto resta — è la forma che
  servirebbe a CTHA. Da chiarire prima: i valori di `TYPE` (non sono nel manuale
  installatore, rimanda alla scheda tecnica), la riconfigurazione degli
  attuatori, e soprattutto se l'integrazione MyHOME continui a esporre la zona
  allo stesso modo. Da provare **su una sola zona**. Attenzione: la modalità
  *residenziale* invece perde il comando da remoto, quindi non va bene
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
  attuatore.** Il gateway F454 è l'integrazione; sotto, l'unità di modello è la
  *zona*, non il singolo apparecchio, e diventa una entità `climate` con
  `current_temperature`, `temperature`, `hvac_action` e le modalità
  spento/automatico/caldo. Non esistono `sensor` separati con
  `device_class: temperature`. La prima versione del config flow li chiedeva ed
  era inconfigurabile su un impianto reale: il menù delle entità restava vuoto.
  Verificato sull'impianto di Stefano il 13 agosto 2026.
- **Nell'impianto la regolazione non è distribuita, è nella centrale.** La sonda
  4691 misura, la 3550 confronta col setpoint e comanda le testine motorizzate
  attraverso gli attuatori F430/4. Da qui due conseguenze che vale la pena non
  riscoprire: la centrale non si può togliere di mezzo (senza di lei le testine
  non ricevono comandi), e su BTicino `auto` significa «segui il programma
  settimanale della centrale» mentre `heat` significa «tieni il setpoint» — che
  è la ragione per cui `_heating_mode()` preferisce `heat`.
- L'integrazione MyHOME gestisce effettivamente i messaggi di offset locale
  dalla manopola della sonda — confermato ispezionando direttamente il
  repository GitHub.
- **Il rimbalzo di setpoint attribuito per settimane alla 3550 era CTHA.**
  Diagnosi del 15 agosto 2026 con `diagnostics/own_bus_trace.py` su un'ora e
  mezza di bus: dei venti frame di setpoint registrati, **tutti** erano
  attribuibili a CTHA o all'utente, e **la centrale non ne ha scritto nessuno**.
  La causa era il fuso orario — vedi il punto seguente. Da qui due lezioni di
  metodo che è costato caro imparare:
  - il criterio diagnostico «una zona = manopola, molte zone = centrale» **non
    discrimina**, perché anche CTHA scrive molte zone insieme con valori
    diversi. Ciò che identifica lo scrivente è la **periodicità** (12 minuti
    esatti, fase costante al centesimo di secondo) e la **spaziatura**
    (`WRITE_STAGGER_SECONDS` + `WRITE_VERIFY_SECONDS` = 3,0 s), più l'ordine
    delle zone: la centrale le percorrerebbe in ordine numerico, CTHA segue
    l'ordine delle config entry;
  - prima di accusare l'impianto, misurare. L'ipotesi «è la centrale» era
    plausibile, documentata dal manuale e sbagliata, e ha orientato per
    settimane il piano di lavoro verso un intervento che non avrebbe risolto
    nulla.
- **Ogni istante che entra in `resolve.py` dev'essere ora locale.** I timer di
  Home Assistant non concordano: `async_track_time_change` chiama con l'ora
  locale, `async_track_time_interval` e `async_call_later` con UTC. Il nucleo
  puro non importa HA, quindi non conosce il fuso configurato e legge `hour`,
  `minute` e `weekday` grezzi. Il watchdog, che gira sul timer a intervallo,
  applicava così il programma di due ore prima (l'offset CEST), riscrivendo ogni
  dodici minuti ciò che il tick di slot aveva appena messo giusto; dopo
  mezzanotte avrebbe usato pure la giornata tipo di ieri. La conversione sta in
  `_as_local`, all'unico confine fra HA e le funzioni pure.
- La riasserzione del proprio *programma settimanale* da parte della 3550
  **resta un rischio plausibile ma non osservato**. Se e quando si manifesterà,
  neutralizzare il programma non vuol dire neutralizzare la centrale: quella
  regola, e serve.
- **Finché la sonda è configurata come «sonda MyHOME», il setpoint scritto da
  CTHA è provvisorio per progetto.** Il manuale installatore della H/LN4691
  (§3.1) dice che un'impostazione diversa da quella della centrale «è temporanea
  e rimarrà valida sino al prossimo cambio di set point da parte della
  centrale». È un comportamento *della sonda*, non della centrale: nessuna
  quantità di riscritture lo cambia. Ne discende che il watchdog non può vincere
  la partita, può solo tenere il campo fra un cambio e l'altro — e che l'unico
  modo di vincerla è che quel «prossimo cambio» non arrivi mai.
- Sempre dal manuale della sonda: in modalità comfort, eco e antigelo «non sarà
  possibile cambiare modalità da centrale o altri dispositivo di controllo».
  Blocca la centrale, ma anche CTHA: non è una strada, è un blocco d'emergenza.
- Le funzioni locali della sonda (cambio modalità, comfort/eco/antigelo,
  ventola) **si possono disabilitare in configurazione** con MyHOME_Suite, e da
  lì «la pressione del pulsante non avrà nessun effetto». È una via alternativa
  al problema della manopola: invece di leggerne l'offset, la si spegne.
- Gli offset della manopola della sonda sono una questione a livello hardware:
  nessun comando software può annullarli, solo compensarli o visualizzarli.
- Il rilevamento echo e la tolleranza deadband (0.15 °C) sono necessari per
  prevenire loop di feedback tra override e scritture. **L'eco va annotata solo
  quando un comando parte davvero**: annotarla in anticipo, dove non si sa
  ancora se il writer scriverà, fa sì che per tutta `ECHO_WINDOW` una mano
  altrui su quel valore venga scambiata per la propria e scartata in silenzio.
- **Una scadenza che si consuma solo a intervalli va verificata anche in
  lettura.** `purge_expired` passa ai confini di slot; nella mezz'ora in mezzo un
  override decaduto resta scritto nel modello, e chi lo legge per decidere un
  setpoint deve chiedersi se è ancora valido. Da qui la coppia
  `OverrideManager.get` (cos'è registrato) / `active` (cos'è ancora valido).
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
