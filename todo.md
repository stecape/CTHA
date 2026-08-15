# TODO

## 1. Diagnosi del rimbalzo di setpoint — chiusa il 15 agosto 2026

La checklist di questa sezione è stata eseguita per intero su Copernico, con
accesso diretto alla LAN del gateway. **L'esito ha smentito l'ipotesi di
partenza**, quindi vale la pena tenerne il verbale invece di cancellarlo.

Sintomo: una zona portata a 17 °C al cambio di fascia veniva riportata a 18 °C
pochi minuti dopo, fino al confine di slot successivo. L'ipotesi era che a
riasserire fosse il programma settimanale della centrale 3550.

- [x] Dipendenze diagnostiche installate (`requirements_diagnostics.txt`)
- [x] `diagnostics/.env` compilato — il gateway è `192.168.2.35:20000`
- [x] Trace eseguita dalle 22:02 alle 23:33 del 15 agosto 2026
- [x] Entità MyHOME controllate durante la trace: nessuna interruzione, la
      seconda sessione EVENTO convive con quella di Home Assistant
- [x] Log analizzato

**Risultato: non era la 3550. Era CTHA.** In un'ora e mezza di bus la centrale
non ha scritto un solo setpoint; tutti i venti frame registrati erano di CTHA o
dell'utente. La firma che lo prova è la periodicità di **12 minuti esatti**
(`RECONCILE_INTERVAL`) con fase costante al centesimo di secondo, e la
spaziatura di **3,0 s** fra zone (`WRITE_STAGGER_SECONDS` +
`WRITE_VERIFY_SECONDS`).

Causa: `_async_reconcile` gira su `async_track_time_interval`, che consegna
**UTC**, mentre `_async_slot_tick` gira su `async_track_time_change`, che
consegna l'**ora locale**. `resolve.py` legge l'orologio a muro, quindi il
watchdog applicava il programma di due ore prima e sovrascriveva ogni dodici
minuti quello che il tick di slot aveva appena messo a posto.

Corretto in 0.9.0 (`_as_local` in `coordinator.py`), insieme a due difetti
emersi dalla stessa analisi: `target_for` che non verificava la scadenza degli
override, e `note_write` che registrava l'eco anche per scritture mai partite.

Il metodo è annotato in `CLAUDE.md` → «Apprendimenti»; lo strumento resta in
`diagnostics/` per la prossima volta.

## 2. Da verificare in stagione di riscaldamento

La trace è stata fatta in agosto, con l'impianto fermo (sonde a 27–30 °C,
attuatori chiusi). Due cose non sono quindi state messe alla prova:

- [ ] **La 3550 riasserisce davvero il proprio programma?** In agosto no. Se in
      inverno si vedessero scritture non attribuibili a CTHA, rilanciare
      `diagnostics/own_bus_trace.py` e confrontare periodicità e spaziatura
      prima di concludere
- [ ] **Il §3.1 della sonda 4691** (setpoint esterno «temporaneo fino al
      prossimo cambio dalla centrale») non si è manifestato: quattro zone hanno
      tenuto per venti minuti un valore scritto da fuori senza tornare indietro

## 3. Voci più a lungo termine

Vedi `CLAUDE.md` → «Prossimi passi» (lettura degli offset locali della sonda
4691, eventuale riconfigurazione a termostato hotel, fork personale di MyHOME,
test con `pytest-homeassistant-custom-component`, prova del pannello dentro
un'istanza HA reale).
