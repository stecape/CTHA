# TODO — da fare al PC con accesso alla LAN

Elenco degli step immediati, pensato per essere ripreso da una sessione con
accesso diretto alla rete di casa (es. Copernico), dove questo ambiente cloud
non arriva.

## 1. Diagnosi del rimbalzo di setpoint (in corso)

Contesto completo: `CLAUDE.md` → «Apprendimenti e principi chiave» (il
comportamento della sonda 4691, §3.1 del manuale) e «Prossimi passi».

Sintomo osservato: una zona corretta da CTHA a 17 °C al cambio di fascia
(22:00) viene riportata a 18 °C con un ciclo di ~4 minuti, finché CTHA non la
ricorregge al successivo confine di slot o al giro del watchdog. Non succede
mentre è attivo un override manuale (in quella finestra CTHA non deve
riscrivere nulla, quindi non c'è competizione visibile).

- [ ] Installare le dipendenze diagnostiche: `pip install -r
      requirements_diagnostics.txt` (dalla root del repo)
- [ ] Compilare `diagnostics/.env` a partire da `diagnostics/.env.example`
      (host, porta, password del gateway — gli stessi valori già usati da
      MyHOME)
- [ ] Lanciare `python diagnostics/own_bus_trace.py` per una finestra che
      copra l'orario del problema (almeno da poco prima delle 22:00 a dopo le
      23:00)
- [ ] Durante la trace, controllare in Home Assistant che le entità MyHOME
      continuino ad aggiornarsi normalmente (rischio noto e non verificabile
      da remoto: una seconda sessione evento concorrente potrebbe non essere
      supportata da tutti i firmware del gateway — vedi
      `diagnostics/README.md`)
- [ ] Analizzare il log: isolare i frame della zona interessata
      (`grep -P '^\S+\t\*4\*' diagnostics/own_bus_trace_*.log`) e verificare
      se il rimbalzo a 18 °C coincide con una scrittura che tocca **una sola
      zona** (manopola/sonda) o **più zone nello stesso istante** (firma della
      centrale 3550 che riafferma il proprio programma)
- [ ] In base all'esito, decidere il passo successivo — vedi CLAUDE.md →
      «Prossimi passi»:
      - se è la 3550: mettere la centrale in **Manuale** su tutte le zone e
        riverificare che il rimbalzo sparisca (soluzione a costo zero, non
        tocca il codice)
      - se è la sonda/manopola: è un offset hardware, si può solo mostrare o
        compensare in UI — nessun rimedio via bus

## 2. Voci più a lungo termine

Vedi `CLAUDE.md` → «Prossimi passi» per l'elenco completo (lettura degli
offset locali della sonda 4691, eventuale riconfigurazione a termostato
hotel, fork personale di MyHOME, test con
`pytest-homeassistant-custom-component`, prova del pannello dentro un'istanza
HA reale).
