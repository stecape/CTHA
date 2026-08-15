# Trace log del bus OpenWebNet

Script diagnostico standalone: apre una sessione EVENTO OpenWebNet
indipendente (stessa libreria usata in produzione da MyHOME, `OWNd`) e logga
per intero ogni frame che il gateway inoltra, non solo quelli di
riscaldamento. Serve a capire con certezza chi scrive un setpoint di zona e
quando — in particolare a distinguere una riasserzione della centrale 3550 da
un'altra sorgente — prima di decidere come intervenire nella logica di CTHA.

**Non richiede e non tocca `custom_components/ctha/`**: è uno strumento
indipendente, non fa parte dell'integrazione.

## Va eseguito sulla LAN del gateway, non nel repository/ambiente cloud

Questo script deve girare su una macchina con accesso diretto alla rete dove
si trova il gateway BTicino (es. il server di casa, "Copernico"). Un
ambiente di sviluppo cloud non ha rete verso il bus OpenWebNet.

## Setup

Dalla root del repository:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements_diagnostics.txt
```

Copia il template delle credenziali e compilalo:

```bash
cp diagnostics/.env.example diagnostics/.env
```

Modifica `diagnostics/.env` con `HOST`, `PORT` (default `20000`), `PASSWORD`
e opzionalmente `SERIAL_NUMBER` — gli stessi valori già usati dalla
configurazione di MyHOME in Home Assistant.

## Esecuzione

```bash
.venv/bin/python diagnostics/own_bus_trace.py
```

Ferma con `Ctrl+C`. Il log va sia su stdout sia su un file
`diagnostics/own_bus_trace_<timestamp>.log` (non versionato, coperto dalla
regola `*.log` di `.gitignore`).

## Come leggere l'output

Ogni riga di traffico ha tre colonne separate da tabulazione:

```
<timestamp ISO8601 con microsecondi>	<frame OpenWebNet grezzo>	<descrizione human-readable>
```

più righe di servizio `[AVVIO]`, `[CONNESSO]`, `[ERRORE]` (con backoff prima
di riprovare) e `[STOP]`.

Per isolare solo i frame di termoregolazione (`WHO=4`):

```bash
grep -P '^\S+\t\*4\*' diagnostics/own_bus_trace_*.log
```

Per la diagnosi del rimbalzo: lanciare la trace per una finestra che copra
l'orario del problema (es. attorno alle 22:00) e cercare, sul frame della
zona interessata, un pattern ripetuto a intervalli regolari (~4 minuti) —
è quello il "chi" da confrontare con la firma della 3550 (vedi
`CLAUDE.md` → *Prossimi passi*: la centrale muove più zone nello stesso
istante, la manopola ne muove una sola).

## Rischio noto, non verificabile da remoto

Aprire una seconda sessione EVENTO mentre MyHOME ne ha già una attiva
potrebbe non essere supportato da tutti i firmware del gateway BTicino.
Durante la trace, controllare in Home Assistant che le entità MyHOME
continuino ad aggiornarsi normalmente (nessun "non disponibile" prolungato).
Se si notano anomalie, interrompere subito la trace.
