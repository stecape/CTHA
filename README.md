# CTHA — Cronotermostato per Home Assistant

Integrazione custom che aggiunge a Home Assistant un cronotermostato multi-zona:
un programma settimanale a scenari decide quale temperatura tenere in ogni zona,
con override temporanei e riconciliazione periodica dei setpoint.

## Stato

In sviluppo. Il backend — modello dati, risoluzione del setpoint, override,
persistenza, servizi — è implementato; l'interfaccia di programmazione non
esiste ancora (vedi [Roadmap](#roadmap)).

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

- Entità `climate` per zona, configurabile dalla UI senza YAML
- Programma settimanale a scenari con template riutilizzabili
- Livelli `comfort`, `eco`, `antifreeze` con ereditarietà zona → globale
- Override con quattro politiche di scadenza e soppressione delle eco
- Persistenza su Store dedicato, separata dalla config entry
- Controllo a isteresi con tolleranze separate sopra/sotto il setpoint
- Servizi `ctha.set_override` e `ctha.clear_override` per le automazioni
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

## Servizi

```yaml
action: ctha.set_override
data:
  zone_id: 01J8ZQ4P7K3W2X9Y   # id della config entry della zona
  temperature: 22.5
  policy: duration
  duration: "01:30:00"
```

```yaml
action: ctha.clear_override
data:
  zone_id: 01J8ZQ4P7K3W2X9Y
```

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
├── resolve.py        # funzioni pure di risoluzione del setpoint
├── services.py       # servizi set_override / clear_override
├── store.py          # persistenza via Store helper
├── manifest.json     # metadati dell'integrazione
├── services.yaml     # schema dei servizi
├── strings.json      # stringhe UI sorgente
└── translations/     # it, en
```

## Roadmap

- [ ] Pannello React in sidebar per la griglia di programmazione (paint-drag)
- [ ] Vista delle dipendenze "chi usa questo template" e "duplica e scollega"
- [ ] Servizi per gestire scenari e template dalle automazioni
- [ ] Adattatore MyHOME/BTicino: scrittura setpoint e lettura offset manopola
- [ ] Appiattimento del programma dell'unità centrale 3550
- [ ] Durata minima di ciclo per proteggere la caldaia
- [ ] Test con `pytest-homeassistant-custom-component`

## Licenza

[MIT](LICENSE)
