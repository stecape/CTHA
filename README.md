# CTHA — Cronotermostato per Home Assistant

Integrazione custom che aggiunge a Home Assistant un cronotermostato multi-zona:
un programma settimanale a scenari decide quale temperatura tenere in ogni zona,
con override temporanei e riconciliazione periodica dei setpoint.

**CTHA non regola la temperatura: programma il setpoint.** Una zona è un
termostato che già esiste in Home Assistant — per un impianto BTicino, l'F430/4
esposto dall'integrazione MyHOME. Quel termostato misura già la temperatura e
comanda già la valvola; quello che gli manca è *quale setpoint tenere e quando*,
ed è l'unica cosa che CTHA gli fornisce.

## Stato

In sviluppo, ma completo nelle sue parti: modello dati, risoluzione del
setpoint, override, persistenza, servizi, pannello React in sidebar e scrittura
del setpoint sul termostato di zona. Manca il riconoscimento specifico degli
offset dalla manopola fisica, che richiede l'adattatore MyHOME (vedi
[Roadmap](#roadmap)).

## Come funziona

Si parte dalle **giornate tipo**, con granularità di 30 minuti, e se ne fanno
quante servono. Da quelle si costruiscono le **settimane tipo**. Uno **scenario**
è la configurazione delle zone: a ciascuna zona assegna una settimana tipo. Da lì
in poi l'unico gesto è scegliere lo scenario attivo, e il componente esegue
quello.

Il setpoint di una zona nasce dall'incrocio di due assi tenuti separati:

- **asse temporale** — scenario attivo → settimana tipo della zona → giornata
  tipo del giorno → slot → livello. Una giornata tipo è una stringa di 48
  caratteri, uno ogni 30 minuti.
- **asse termico** — le temperature si creano liberamente (di default *alta*,
  *media*, *bassa*, *antigelo*) e si sovrascrivono lungo questa gerarchia:

  ```
  Global
  └─ Scenario
     └─ Zona
        └─ Week template
           └─ Day template
  ```

  Chi sta più in basso vince; chi non dichiara nulla eredita da chi sta sopra.
  Il globale è la radice e non può ereditare da nessuno.

`resolve_setpoint` è una funzione pura che li combina: dato il modello, la zona
e un istante, restituisce la temperatura e **quale livello della gerarchia l'ha
decisa**.

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
scritture di 1.5 s fra una zona e l'altra per non saturare il bus. Scrive solo
dove serve: se il termostato ha già il valore voluto non tocca nulla, quindi in
condizioni normali sul bus non passa traffico.

Ogni cambio di setpoint che non sia l'eco di una scrittura di CTHA è qualcun
altro che ha messo mano alla zona — la manopola, l'app del costruttore, la
centrale. Diventa un override fino alla fine della mezz'ora corrente, non un
errore da correggere all'istante.

## Funzionalità

- Pannello in sidebar con griglia settimanale a 48 mezz'ore e pennellata a
  trascinamento
- Una entità `climate` per zona, sopra al termostato reale, configurabile dalla
  UI senza YAML
- Scenari come configurazione delle zone: uno scenario dice, per ogni zona,
  quale settimana tipo seguire — cambiarlo riprogramma l'impianto in un gesto
- Livelli di temperatura definibili dall'utente (di default alta, media, bassa,
  antigelo), con ereditarietà su cinque livelli
- Override con quattro politiche di scadenza e soppressione delle eco
- Persistenza su Store dedicato, separata dalla config entry
- Servizi per override, template, scenari e setpoint, usabili dalle automazioni
- Integrità referenziale: non si elimina un template ancora in uso, e l'errore
  dice chi lo sta usando
- Provenienza del setpoint esposta negli attributi dell'entità

## Requisiti

- Home Assistant 2024.12 o successivo
- Una entità `climate` per ogni zona da programmare, che accetti
  `climate.set_temperature`

Su impianto BTicino le entità arrivano dall'integrazione
[MyHOME](https://github.com/anotherjulien/MyHOME): il gateway F454 espone una
entità `climate` per ogni termostato di zona F430/4. CTHA non richiede sensori
di temperatura separati — la misura sta già negli attributi di quelle entità.

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
volta per zona: un nome e il termostato che governa quella zona. Una zona per
termostato.

Al primo avvio vengono creati quattro livelli di temperatura (alta 21 °C,
media 19 °C, bassa 17 °C, antigelo 7 °C) e un programma di default: notte
bassa, mattina e sera alte, giornata media, uguale per tutti i giorni. Ogni
zona aggiunta in seguito viene assegnata a quella settimana tipo in tutti gli
scenari esistenti, così comincia a funzionare senza aprire il pannello.

Per ogni zona nasce una entità `climate` di CTHA, che affianca quella del
termostato reale: mostra la stessa temperatura misurata, ma il suo target è
*quello che il programma vuole*, e i suoi attributi dicono da dove viene
(`level`, `setpoint_source`, `scenario`, e l'eventuale override). Cambiarne la
temperatura crea un override; il preset corrisponde al livello. Conviene
nascondere dalle dashboard le entità del termostato sottostante e usare queste.

Spegnere la zona (`hvac_mode: off`) spegne il termostato sottostante, e finché
resta spenta CTHA non le scrive più setpoint.

## Il pannello

Con la prima zona compare **Cronotermostato** nella sidebar (solo per gli
amministratori). Quattro viste, che ricalcano l'architettura:

- **Programma** — l'asse temporale. Sette righe da 48 mezz'ore: si sceglie un
  pennello (un livello di temperatura, o «eredita») e si trascina. Sotto,
  l'elenco delle giornate e settimane tipo con *chi le usa*.
- **Scenari** — la configurazione delle zone. Per ogni scenario la tabella zona
  → settimana tipo, per intero: prima di attivare uno scenario si vede cosa
  farà a ciascuna zona.
- **Temperature** — i livelli (nome, colore, setpoint globale, creazione ed
  eliminazione) e l'elenco di *dove* sono state scritte le sovrascritture.
- **Zone** — lo stato adesso: temperatura misurata, setpoint applicato, da quale
  livello della gerarchia viene, che programma sta seguendo, e l'eventuale
  override con la sua scadenza.

**Le temperature si modificano sull'istanza.** Ogni elemento che può
sovrascrivere una temperatura ha accanto a sé un pulsante **Temperature**, col
numero di quelle proprie: lo scenario nella sua intestazione, la zona nella
tabella dello scenario e nella propria scheda, la settimana tipo accanto al
selettore in *Programma* e nel suo elenco, la giornata tipo nel suo elenco. Il
pulsante apre sempre la stessa finestra, che per ogni livello mostra il valore
proprio, quello che erediterebbe e da chi, e quello in vigore. Un campo vuoto
eredita; svuotarlo è il modo di tornare a ereditare.

Non c'è un editor centrale con un menù «scegli il punto della gerarchia»:
sarebbe più compatto ma direbbe la cosa sbagliata. Le sovrascritture
appartengono all'elemento — due settimane tipo hanno temperature diverse perché
sono due settimane tipo.

**Le giornate tipo sono condivise.** Una riga marcata *condivisa* usa lo stesso
template di altri giorni: dipingerla li cambia tutti. Il pannello se ne accorge
e chiede cosa fare — modificare per tutti, oppure scollegare quel giorno su una
copia indipendente.

## Servizi

| Servizio | A cosa serve |
|---|---|
| `ctha.set_override` | forza una temperatura su una zona |
| `ctha.clear_override` | riporta la zona al programma |
| `ctha.set_level` | crea o aggiorna un livello di temperatura |
| `ctha.delete_level` | elimina un livello non più dipinto |
| `ctha.set_setpoint` | scrive una temperatura in un punto della gerarchia |
| `ctha.set_day_template` | crea o aggiorna una giornata tipo |
| `ctha.paint_slots` | dipinge un livello su un intervallo di slot |
| `ctha.duplicate_day_template` | duplica una giornata tipo e la riaggancia |
| `ctha.delete_day_template` | elimina una giornata tipo non più usata |
| `ctha.set_week_template` | crea o aggiorna una settimana tipo |
| `ctha.delete_week_template` | elimina una settimana tipo non più usata |
| `ctha.set_scenario` | crea o aggiorna uno scenario e la sua mappa delle zone |
| `ctha.delete_scenario` | elimina uno scenario non attivo |
| `ctha.activate_scenario` | cambia lo scenario attivo |
| `ctha.set_zone_week_template` | assegna la settimana tipo di una zona in uno scenario |

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
# Una giornata tipo per il fine settimana, alta dalle 08:00 alle 23:00
action: ctha.set_day_template
data:
  template_id: weekend
  name: Weekend
  slots: "bbbbbbbbbbbbbbbb--------------------------------"

action: ctha.paint_slots
data:
  template_id: weekend
  start_slot: 16      # 08:00
  end_slot: 45        # 22:30 compreso
  level: alta

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

### Scenari

Uno scenario nuovo parte dalla configurazione di quello attivo, poi si cambia
solo ciò che deve cambiare:

```yaml
action: ctha.set_scenario
data:
  scenario_id: vacanza
  name: Vacanza
  zones:
    01J8ZQ4P7K3W2X9Y: ridotta     # questa zona segue la settimana "ridotta"
    01J8ZQ4P7K3W2X9Z: null        # questa non è programmata affatto

action: ctha.activate_scenario
data:
  scenario_id: vacanza

# Assegnazione singola, sullo scenario attivo se non se ne indica un altro
action: ctha.set_zone_week_template
data:
  zone_id: 01J8ZQ4P7K3W2X9Y
  template_id: ridotta
```

### Temperature

I livelli si creano come tutto il resto, e ognuno prende un carattere libero
per le giornate tipo:

```yaml
action: ctha.set_level
data:
  level: notte
  name: Notte
  color: "#5566aa"
  temperature: 16       # setpoint globale del livello
```

Un setpoint si scrive in **un** punto della gerarchia: senza ambito è il
globale, altrimenti si indica lo scenario, la zona, la settimana tipo o la
giornata tipo. Senza temperatura quel punto torna a ereditare.

```yaml
# Radice: vale per chiunque non dica diversamente
action: ctha.set_setpoint
data:
  level: alta
  temperature: 21.5

# In vacanza «alta» vale 17, ovunque
action: ctha.set_setpoint
data:
  level: alta
  temperature: 17
  scenario_id: vacanza

# Il bagno però la vuole a 23 comunque: la zona sta più in basso e vince
action: ctha.set_setpoint
data:
  level: alta
  temperature: 23
  zone_id: 01J8ZQ4P7K3W2X9Y

# ...e ci ripensa: torna a ereditare
action: ctha.set_setpoint
data:
  level: alta
  zone_id: 01J8ZQ4P7K3W2X9Y
```

Le cancellazioni rifiutano di spezzare il programma: `delete_day_template` e
`delete_week_template` falliscono se qualcuno usa ancora l'elemento, dicendo
chi; `delete_level` fallisce se il livello è ancora dipinto da qualche parte;
`delete_scenario` non tocca né lo scenario attivo né l'ultimo rimasto.

## Struttura del repository

```
custom_components/ctha/
├── __init__.py       # setup/unload delle entry, runtime condiviso
├── climate.py        # entità climate di zona, scrittura del setpoint
├── config_flow.py    # config flow: nome della zona e termostato
├── const.py          # domain, chiavi, gerarchia, timing, default
├── coordinator.py    # runtime: programma, override, watchdog
├── migrate.py        # migrazione dei dati fra versioni dello Store
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

`const.py`, `models.py`, `resolve.py`, `override.py`, `program.py` e
`migrate.py` non importano `homeassistant`: sono verificabili senza far
girare HA.

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
- [x] Scrittura del setpoint sul termostato di zona
- [x] Livelli di temperatura definibili dall'utente
- [x] Scenari come configurazione delle zone ed ereditarietà a cinque livelli
- [ ] Lettura dei messaggi di offset locale dell'F430/4, per distinguere la
      manopola fisica (override `hardware`) dalle altre sorgenti esterne
- [ ] Appiattimento del programma dell'unità centrale 3550
- [ ] Test della parte che tocca HA con `pytest-homeassistant-custom-component`

## Licenza

[MIT](LICENSE)
