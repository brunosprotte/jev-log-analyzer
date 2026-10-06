"""SQLite-backed dedupe store. Stdlib only."""
from __future__ import annotations

import hashlib
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from .config import Config
from .models import LogEvent

_TS = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
_HASH = re.compile(r"\b[0-9a-f]{32,64}\b", re.I)
_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
_PORT = re.compile(r":\d{2,5}\b")
_NUM = re.compile(r"\b\d+\b")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    sig TEXT PRIMARY KEY,
    service TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 1,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    jira_key TEXT,
    agent_run_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_last_seen ON events(last_seen);
"""


def init_db(cfg: Config) -> None:
    with sqlite3.connect(cfg.DEDUPE_DB_PATH) as cx:
        for stmt in _SCHEMA.strip().split(";"):
            if stmt.strip():
                cx.execute(stmt)
        cx.commit()


def normalize(message: str) -> str:
    s = _TS.sub("<TS>", message)
    s = _UUID.sub("<UUID>", s)
    s = _HASH.sub("<HASH>", s)
    s = _IP.sub("<IP>", s)
    s = _PORT.sub(":<PORT>", s)
    s = _NUM.sub("<N>", s)
    return s.strip()


def sig_of(event: LogEvent) -> str:
    base = f"{event.service}|{normalize(event.message)}"
    return hashlib.sha1(base.encode()).hexdigest()[:16]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _conn(path: str) -> sqlite3.Connection:
    cx = sqlite3.connect(path)
    cx.row_factory = sqlite3.Row
    return cx


def lookup(cfg: Config, service: str, sig: str) -> Optional[sqlite3.Row]:
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=cfg.DEDUPE_WINDOW_HOURS)).isoformat()
    with _conn(cfg.DEDUPE_DB_PATH) as cx:
        cur = cx.execute(
            "SELECT * FROM events WHERE sig = ? AND service = ? AND last_seen >= ?",
            (sig, service, cutoff),
        )
        return cur.fetchone()


def record(cfg: Config, event: LogEvent, sig: str, *,
           jira_key: Optional[str] = None,
           agent_run_id: Optional[str] = None) -> sqlite3.Row:
    ts = _now()
    with _conn(cfg.DEDUPE_DB_PATH) as cx:
        cx.execute(
            "INSERT INTO events(sig, service, count, first_seen, last_seen, jira_key, agent_run_id) "
            "VALUES(?, ?, 1, ?, ?, ?, ?)",
            (sig, event.service, ts, ts, jira_key, agent_run_id),
        )
        cx.commit()
        cur = cx.execute("SELECT * FROM events WHERE sig = ?", (sig,))
        return cur.fetchone()


def bump(cfg: Config, row: sqlite3.Row) -> None:
    with _conn(cfg.DEDUPE_DB_PATH) as cx:
        cx.execute(
            "UPDATE events SET count = count + 1, last_seen = ? WHERE sig = ?",
            (_now(), row["sig"]),
        )
        cx.commit()