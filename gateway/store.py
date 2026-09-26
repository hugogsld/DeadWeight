"""D1.2 — Persistance des événements capturés dans SQLite, hors du chemin critique.

La passerelle dépose chaque événement dans une file (``put`` ne bloque jamais) ;
un thread d'écriture les vide par lots dans SQLite. La base reste chez le client.

    python -m gateway.store count                 # nombre d'événements
    python -m gateway.store export > events.jsonl # pour report.audit
"""
import argparse
import json
import logging
import os
import queue
import sqlite3
import sys
import threading

log = logging.getLogger("deadweight.store")

DEFAULT_PATH = os.environ.get("GATEWAY_DB", "out/events.db")
BATCH = 500
_STOP = object()

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id    TEXT PRIMARY KEY,
    ts_start    TEXT NOT NULL,
    app_id      TEXT NOT NULL,
    provider    TEXT NOT NULL,
    model       TEXT NOT NULL,
    trace_id    TEXT,
    http_status INTEGER NOT NULL,
    event       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_ts ON events (ts_start);
CREATE INDEX IF NOT EXISTS events_app_model ON events (app_id, model);
CREATE INDEX IF NOT EXISTS events_trace ON events (trace_id);
"""


def connect(path):
    if os.path.dirname(path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
    db = sqlite3.connect(path, check_same_thread=False)
    db.execute("PRAGMA journal_mode=WAL")  # lecture pendant que la passerelle écrit
    db.execute("PRAGMA synchronous=NORMAL")
    db.executescript(SCHEMA)
    return db


class EventStore:
    """File en mémoire + thread d'écriture. ``put`` est le sink de ``make_app``."""

    def __init__(self, path=DEFAULT_PATH, max_pending=50_000):
        self.path = path
        self.dropped = 0
        self._queue = queue.Queue(maxsize=max_pending)
        self._db = connect(path)
        self._thread = threading.Thread(target=self._run, name="deadweight-store", daemon=True)
        self._thread.start()

    def put(self, event):
        try:
            self._queue.put_nowait(event)
        except queue.Full:  # la base ne suit plus : on perd l'événement, jamais la réponse
            self.dropped += 1
            if self.dropped == 1 or self.dropped % 1000 == 0:
                log.warning("store: file pleine, %d événement(s) perdu(s)", self.dropped)

    def close(self):
        """Vide la file puis ferme la base."""
        self._queue.put(_STOP)
        self._thread.join()
        self._db.close()

    def _run(self):
        while True:
            batch, stop = [self._queue.get()], False
            while len(batch) < BATCH:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            if _STOP in batch:
                batch.remove(_STOP)
                stop = True
            if batch:
                self._write(batch)
            if stop:
                return

    def _write(self, batch):
        rows = [(e["event_id"], e["ts_start"], e["app_id"], e["provider"], e["model"],
                 e["trace"]["id"], e["http_status"], json.dumps(e, ensure_ascii=False))
                for e in batch]
        try:
            with self._db:
                self._db.executemany("INSERT OR REPLACE INTO events VALUES (?,?,?,?,?,?,?,?)", rows)
        except sqlite3.Error:
            self.dropped += len(rows)
            log.exception("store: écriture de %d événement(s) en échec", len(rows))


def read_events(path=DEFAULT_PATH, app_id=None):
    """Événements au schéma v1, dans l'ordre chronologique."""
    db = connect(path)
    try:
        sql, args = "SELECT event FROM events", ()
        if app_id:
            sql, args = sql + " WHERE app_id = ?", (app_id,)
        for (raw,) in db.execute(sql + " ORDER BY ts_start, rowid", args):
            yield json.loads(raw)
    finally:
        db.close()


def count(path=DEFAULT_PATH, app_id=None):
    db = connect(path)
    try:
        if app_id:
            return db.execute("SELECT COUNT(*) FROM events WHERE app_id = ?", (app_id,)).fetchone()[0]
        return db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    finally:
        db.close()


def main():
    ap = argparse.ArgumentParser(description="Événements capturés par la passerelle")
    ap.add_argument("command", choices=["count", "export"])
    ap.add_argument("--db", default=DEFAULT_PATH)
    ap.add_argument("--app", help="filtrer sur un app_id")
    args = ap.parse_args()
    if not os.path.exists(args.db):
        sys.exit(f"{args.db} introuvable : lancer la passerelle d'abord (python -m gateway)")
    if args.command == "count":
        print(count(args.db, args.app))
    else:
        for event in read_events(args.db, args.app):
            sys.stdout.write(json.dumps(event, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
