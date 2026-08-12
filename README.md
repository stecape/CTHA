# CTHA — Cronotermostato per Home Assistant

Integrazione custom che aggiunge a Home Assistant un cronotermostato multi-zona:
un programma settimanale a scenari decide quale temperatura tenere in ogni zona,
con override temporanei e riconciliazione periodica dei setpoint.

## Stato

In sviluppo. Backend e interfaccia di programmazione ci sono: modello dati,
risoluzione del setpoint, override, persistenza, servizi e un pannello React in
sidebar con la griglia settimanale. Manca l'adattatore BTicino/MyHOME, quindi
l'attuazione avviene ancora a isteresi su un attuatore generico (vedi
[Roadmap](#roadmap)).

## Come funziona

Il setpoint di una zona nasce dall'incrocio di due assi tenuti separati:

- **asse temporale** — scenario → week template → day template → slot → livello.
  Un day template è una stringa di 48 caratteri, uno ogni 30 minuti.
- **asse termico** — setpoint di zona → offset di scenario → setpoint globale.
  Un valore assente o `null` significa *eredita*, esplicitamente.

`resolve_setpoint` è una funzione pura che li combina: dato il modello, la zona
e un istante, restituisce la temperatura e la sua provenienza.

Sopra al programma stanno gli **override**, distinti per sorgente perché vanno
trattati diversamente:

| Sorgente | Origine | Trattamento |
|---|---|---|
| `ha` | scritture nostre | soppresse per eco (finestra 60 s, deadband 0.15 °C) |
| `external` | app esterne, unità centrale | registrate, scadono secondo la policy |
| `hardware` | manopola del termostato fisico | non annullabile via software: si mostra e si compensa |

Politiche di scadenza disponibili: `next_slot`, `duration`,
`until_scenario_change`, `sticky`.

Un watchdog riscrive i setpoint desiderati ogni 12 minuti, scaglionando le
scritture di 1.5 s fra una zona e l'altra per non saturare il bus.

## Funzionalità

- Pannello in sidebar con griglia settimanale a 48 mezz'ore e pennellata a
  trascinamento
- Entità `climate` per zona, configurabile dalla UI senza YAML
- Programma settimanale a scenari con template riutilizzabili
- Livelli `comfort`, `eco`, `antifreeze` con ereditarietà zona → globale
- Override con quattro politiche di scadenza e soppressione delle eco
- Persistenza su Store dedicato, separata dalla config entry
- Controllo a isteresi con tolleranze separate sopra/sotto il setpoint
- Servizi per override, template, scenari e setpoint, usabili dalle automazioni
- Integrità referenziale: non si elimina un template ancora in uso, e l'errore
  dice chi lo sta usando
- Provenienza del setpoint esposta negli attributi dell'entità

## Requisiti

- Home Assistant 2024.12 o successivo
- Un sensore con `device_class: temperature`
- Un attuatore comandabile: `switch`, `input_boolean` o `climate`

## Installazione

### HACS (custom repository)

1. HACS → Integrazioni → menu ⋮ → *Custom repositories*
2. Aggiungi `https://github.com/stecape/CTHA` come categoria *Integration*
3. Installa **CTHA** e riavvia Home Assistant

### Manuale

Copia `custom_components/ctha` in `<config>/custom_components/` e riavvia
Home Assistant.

## Configurazione

*Impostazioni → Dispositivi e servizi → Aggiungi integrazione → CTHA*, una
volta per zona: nome, sensore di temperatura e attuatore. Le tolleranze di
isteresi (default 0.3 °C) si regolano poi da *Configura*.

Al primo avvio viene creato un programma di default: notte in eco, risveglio e
sera in comfort, uguale per tutti i giorni.

## Il pannello

Con la prima zona compare **Cronotermostato** nella sidebar (solo per gli
amministratori). Tre viste, che ricalcano l'architettura:

- **Programma** — l'asse temporale. Sette righe da 48 mezz'ore: si sceglie un
  pennello (comfort, eco, antigelo, eredita) e si trascina. Sotto, l'elenco
  delle giornate e settimane tipo con *chi le usa*.
- **Temperature** — l'asse termico. Setpoint globali, eccezioni per zona (un
  campo vuoto eredita e mostra in grigio il valore ereditato) e scenari con i
  loro offset.
- **Zone** — lo stato adesso: temperatura misurata, setpoint applicato, da dove
  viene, e l'eventuale override con la sua scadenza.

**Le giornate tipo sono condivise.** Una riga marcata *condivisa* usa lo stesso
template di altri giorni: dipingerla li cambia tutti. Il pannello se ne accorge
e chiede cosa fare — modificare per tutti, oppure scollegare quel giorno su una
copia indipendente.

## Servizi

| Servizio | A cosa serve |
|---|---|
| `ctha.set_override` | forza una temperatura su una zona |
| `ctha.clear_override` | riporta la zona al programma |
| `ctha.set_day_template` | crea o aggiorna una giornata tipo |
| `ctha.paint_slots` | dipinge un livello su un intervallo di slot |
| `ctha.duplicate_day_template` | duplica una giornata tipo e la riaggancia |
| `ctha.delete_day_template` | elimina una giornata tipo non più usata |
| `ctha.set_week_template` | crea o aggiorna una settimana tipo |
| `ctha.delete_week_template` | elimina una settimana tipo non più usata |
| `ctha.set_scenario` | crea o aggiorna uno scenario e i suoi offset |
| `ctha.delete_scenario` | elimina uno scenario non attivo |
| `ctha.activate_scenario` | cambia lo scenario attivo |
| `ctha.set_setpoint` | imposta un setpoint globale o di zona |
| `ctha.set_zone_week_template` | dà a una zona un programma proprio |

I servizi `set_*` creano l'elemento se l'id non esiste e aggiornano solo i campi
indicati: la stessa chiamata, ripetuta, converge sempre sullo stesso risultato.

### Override

```yaml
action: ctha.set_override
data:
  zone_id: 01J8ZQ4P7K3W2X9Y   # id della config entry della zona
  temperature: 22.5
  policy: duration
  duration: "01:30:00"
```

### Costruire un programma

```yaml
# Una giornata tipo per il fine settimana, comfort dalle 08:00 alle 23:00
action: ctha.set_day_template
data:
  template_id: weekend
  name: Weekend
  slots: "eeeeeeeeeeeeeeee--------------------------------"

action: ctha.paint_slots
data:
  template_id: weekend
  start_slot: 16      # 08:00
  end_slot: 45        # 22:30 compreso
  level: comfort

# ...e assegnarla a sabato e domenica (0 = lunedì)
action: ctha.set_week_template
data:
  template_id: default
  days:
    5: weekend
    6: weekend
```

Modificare una giornata tipo la modifica per tutti i giorni che la usano. Per
differenziarne uno solo:

```yaml
action: ctha.duplicate_day_template
data:
  template_id: weekend
  week_template: default
  days: [6]           # solo la domenica passa alla copia
```

### Scenari e setpoint

```yaml
action: ctha.set_scenario
data:
  scenario_id: vacanza
  name: Vacanza
  offset: -4          # tutta la casa 4 °C più fredda
  zone_offsets:
    01J8ZQ4P7K3W2X9Y: 0    # tranne questa zona

action: ctha.activate_scenario
data:
  scenario_id: vacanza

# Setpoint globale del livello comfort
action: ctha.set_setpoint
data:
  level: comfort
  temperature: 21.5

# ...e l'eccezione di una zona; senza temperatura torna a ereditare
action: ctha.set_setpoint
data:
  level: comfort
  temperature: 20.0
  zone_id: 01J8ZQ4P7K3W2X9Y
```

Le cancellazioni rifiutano di spezzare il programma: `delete_day_template` e
`delete_week_template` falliscono se qualcuno usa ancora l'elemento, dicendo
chi; `delete_scenario` non tocca né lo scenario attivo né l'ultimo rimasto.

## Struttura del repository

```
custom_components/ctha/
├── __init__.py       # setup/unload delle entry, runtime condiviso
├── climate.py        # entità climate di zona, attuazione a isteresi
├── config_flow.py    # config flow e options flow
├── const.py          # domain, chiavi, livelli, timing, default
├── coordinator.py    # runtime: programma, override, watchdog
├── models.py         # modello dati serializzabile
├── override.py       # policy di scadenza e soppressione echo
├── panel.py          # registrazione del pannello e del percorso statico
├── program.py        # funzioni pure di modifica del programma
├── resolve.py        # funzioni pure di risoluzione del setpoint
├── services.py       # registrazione dei servizi
├── store.py          # persistenza via Store helper
├── websocket.py      # API di lettura con push per il pannello
├── frontend/         # bundle compilato del pannello (versionato)
├── manifest.json     # metadati dell'integrazione
├── services.yaml     # schema dei servizi
├── strings.json      # stringhe UI sorgente
└── translations/     # it, en
frontend/             # sorgenti React + Vite del pannello
tests/                # suite sul nucleo puro, non serve Home Assistant
```

## Sviluppo

### Backend

`const.py`, `models.py`, `resolve.py`, `override.py` e `program.py` non
importano `homeassistant`: sono verificabili senza far girare HA.

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements_test.txt
.venv/Scripts/python -m pytest
```

### Frontend

Il pannello è React impacchettato come Web Component. Il bundle compilato è
versionato in `custom_components/ctha/frontend/`: HACS distribuisce il
repository così com'è, quindi va ricompilato e committato a ogni modifica dei
sorgenti.

```bash
cd frontend
npm install
npm run check     # tsc + vite build + prova di accensione in jsdom
npm run watch     # ricompila a ogni salvataggio
```

## Roadmap

- [x] Pannello React in sidebar per la griglia di programmazione (paint-drag)
- [x] Vista delle dipendenze "chi usa questo template" nell'interfaccia
- [ ] Adattatore MyHOME/BTicino: scrittura setpoint e lettura offset manopola
- [ ] Appiattimento del programma dell'unità centrale 3550
- [ ] Durata minima di ciclo per proteggere la caldaia
- [ ] Test della parte che tocca HA con `pytest-homeassistant-custom-component`

## Licenza

[MIT](LICENSE)
