# CTHA — Cronotermostato per Home Assistant

Integrazione custom che aggiunge a Home Assistant un cronotermostato: un'entità
`climate` che comanda un attuatore (caldaia, valvola, relè) sulla base di un
sensore di temperatura, con controllo a isteresi e programmazione settimanale.

## Stato

Fase iniziale. Il nucleo termostato è implementato; il programmatore settimanale
è il prossimo passo (vedi [Roadmap](#roadmap)).

## Funzionalità

- Entità `climate` configurabile dalla UI (config flow), senza YAML
- Controllo a isteresi con tolleranze separate sopra/sotto il setpoint
- Modalità `heat` / `off` e azione corrente (`heating` / `idle` / `off`)
- Preset `comfort`, `eco`, `antifreeze` con setpoint dedicati
- Stato ripristinato al riavvio di Home Assistant
- Tolleranze modificabili a caldo dalle opzioni dell'integrazione

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

*Impostazioni → Dispositivi e servizi → Aggiungi integrazione → CTHA*.

Vengono richiesti nome, sensore di temperatura e attuatore. Le tolleranze di
isteresi (default 0.3 °C) si regolano poi da *Configura*.

## Struttura del repository

```
custom_components/ctha/
├── __init__.py       # setup/unload della config entry
├── climate.py        # entità climate e logica a isteresi
├── config_flow.py    # config flow e options flow
├── const.py          # domain, chiavi di config, default
├── manifest.json     # metadati dell'integrazione
├── strings.json      # stringhe UI sorgente
└── translations/     # it, en
```

## Roadmap

- [ ] Programma settimanale (fasce orarie per giorno, editor da UI)
- [ ] Applicazione automatica dei preset in base al programma
- [ ] Override manuale temporaneo con rientro automatico nel programma
- [ ] Modalità vacanza / assenza
- [ ] Durata minima di ciclo per proteggere la caldaia
- [ ] Test con `pytest-homeassistant-custom-component`
- [ ] Card Lovelace dedicata per il programma settimanale

## Licenza

[MIT](LICENSE)
