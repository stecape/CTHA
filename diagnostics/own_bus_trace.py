"""Trace log del bus OpenWebNet: registra ogni frame ricevuto da una sessione
EVENTO indipendente, per capire chi scrive un setpoint e quando (diagnosi del
rimbalzo di fascia vs riasserzione della centrale 3550). Non richiede Home
Assistant, non tocca custom_components/ctha. Va eseguito su una macchina con
accesso diretto alla LAN del gateway BTicino — non nell'ambiente cloud in cui
è stato scritto. Uso: vedi diagnostics/README.md.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from OWNd.connection import OWNEventSession, OWNGateway

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_PORT = 20000
INITIAL_BACKOFF = 2.0
MAX_BACKOFF = 60.0


def _load_dotenv(path: Path) -> None:
    """Carica KEY=VALUE da .env senza dipendenze esterne.

    Le variabili già presenti in `os.environ` (systemd, cron, shell) hanno
    sempre la priorità sul file: permette sia l'uso interattivo con `.env`
    sia un'esecuzione schedulata senza credenziali su disco.
    """
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True, slots=True)
class Config:
    """Parametri di connessione al gateway, letti dall'ambiente."""

    host: str
    port: int
    password: str
    serial_number: str | None

    @classmethod
    def from_env(cls) -> "Config":
        """Costruisce la config da `os.environ`, fallendo con un messaggio chiaro."""
        host = os.environ.get("HOST")
        password = os.environ.get("PASSWORD")
        if not host or not password:
            raise SystemExit(
                "HOST e PASSWORD mancanti: compila diagnostics/.env "
                "(vedi diagnostics/.env.example) o esportali come variabili d'ambiente."
            )
        return cls(
            host=host,
            port=int(os.environ.get("PORT", DEFAULT_PORT)),
            password=password,
            serial_number=os.environ.get("SERIAL_NUMBER") or None,
        )


class TraceWriter:
    """Scrive ogni riga su file (append, flush e fsync espliciti) e su stdout.

    Il flush esplicito evita di perdere le righe più recenti se il processo
    viene interrotto bruscamente (kill, crash, riavvio del server).
    """

    def __init__(self, log_path: Path) -> None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._file = log_path.open("a", encoding="utf-8")

    def write(self, line: str) -> None:
        print(line, flush=True)
        self._file.write(line + "\n")
        self._file.flush()
        os.fsync(self._file.fileno())

    def close(self) -> None:
        self._file.close()


def _timestamp() -> str:
    """Timestamp locale con microsecondi: serve a correlare eventi a pochi minuti."""
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def _own_logger() -> logging.Logger:
    """Logger passato a OWNd: solo i suoi avvisi/errori, separati dal trace."""
    logger = logging.getLogger("OWNd")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s [OWNd] %(levelname)s %(message)s")
        )
        logger.addHandler(handler)
    logger.setLevel(os.environ.get("OWND_LOG_LEVEL", "WARNING"))
    return logger


async def _trace_forever(
    config: Config, writer: TraceWriter, stop_event: asyncio.Event
) -> None:
    """Mantiene la sessione evento aperta, riconnettendo a backoff se cade.

    `connect()`/`get_next()` di OWNd non sollevano eccezioni verso il
    chiamante in condizioni note (gestiscono da sole i casi di libreria), ma
    il comportamento del gateway fisico dell'utente non è verificabile da
    remoto: il blocco try/except resta comunque ampio, per non terminare mai
    in silenzio davanti a un errore imprevisto.
    """
    backoff = INITIAL_BACKOFF
    logger = _own_logger()
    while not stop_event.is_set():
        gateway_info: dict[str, object] = {
            "address": config.host,
            "port": config.port,
            "password": config.password,
        }
        if config.serial_number:
            gateway_info["serialNumber"] = config.serial_number

        session = OWNEventSession(gateway=OWNGateway(gateway_info), logger=logger)
        try:
            result = await session.connect()
            if not result or not result.get("Success"):
                raise ConnectionError(f"connessione/negoziazione fallita: {result}")

            writer.write(
                f"{_timestamp()}\t[CONNESSO]\thost={config.host}:{config.port}"
            )
            backoff = INITIAL_BACKOFF  # reset dopo una connessione riuscita

            while not stop_event.is_set():
                message = await session.get_next()
                if message is None:
                    # get_next() gestisce già da sola la disconnessione
                    # interna (riconnette o scarta un frame illeggibile):
                    # None non è un errore fatale, si continua ad ascoltare.
                    continue
                raw = str(message)
                human = getattr(message, "human_readable_log", "") or ""
                writer.write(f"{_timestamp()}\t{raw}\t{human}")
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - vedi docstring: mai terminare in silenzio
            writer.write(
                f"{_timestamp()}\t[ERRORE]\t{exc!r} — riconnessione tra {backoff:.0f}s"
            )
            logger.exception("Errore nel loop di trace")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, MAX_BACKOFF)
        finally:
            try:
                await session.close()
            except Exception:  # noqa: BLE001 - chiusura best-effort
                pass


async def _main() -> None:
    """Carica la config, apre il file di log e ascolta finché non si ferma."""
    _load_dotenv(SCRIPT_DIR / ".env")
    config = Config.from_env()

    default_log = SCRIPT_DIR / f"own_bus_trace_{datetime.now():%Y%m%d_%H%M%S}.log"
    log_path = Path(os.environ.get("TRACE_LOG_FILE", default_log))
    writer = TraceWriter(log_path)
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass  # piattaforme senza add_signal_handler: KeyboardInterrupt copre SIGINT

    writer.write(
        f"{_timestamp()}\t[AVVIO]\tin ascolto su {config.host}:{config.port} "
        f"— log: {log_path}"
    )
    try:
        await _trace_forever(config, writer, stop_event)
    finally:
        writer.write(f"{_timestamp()}\t[STOP]")
        writer.close()


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass
