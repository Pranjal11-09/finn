"""SQLite: one KV cache (raw fetches + LLM outputs) and a few small app tables.

The KV cache is the backbone of the cost story: every network fetch and every LLM call is keyed by
(namespace, content hash, prompt version). Re-running anything is free. The same table can be dumped
to a seed file so a deployed demo boots pre-warmed.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sqlite3
import threading
import time
from typing import Any
from contextvars import ContextVar

from . import config

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None
reviewer: ContextVar[str | None] = ContextVar("reviewer", default=None)

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
  ns TEXT NOT NULL, k TEXT NOT NULL, v TEXT NOT NULL, ts REAL NOT NULL,
  PRIMARY KEY (ns, k)
);
CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK (id = 1), v TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS triage (
  item_id TEXT PRIMARY KEY, state TEXT NOT NULL, symbol TEXT, category TEXT, ts REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS alerts (
  id TEXT PRIMARY KEY, kind TEXT, symbol TEXT, title TEXT, why TEXT, payload TEXT,
  ts REAL NOT NULL, sent INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS llm_usage (
  ts REAL, task TEXT, model TEXT, tier TEXT, in_tok INTEGER, out_tok INTEGER, cached INTEGER, ms INTEGER
);
"""


def conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            _conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
            _conn.executescript(SCHEMA)
            _load_seed_if_empty(_conn)
        return _conn


def h(*parts: Any) -> str:
    return hashlib.sha1("\x1f".join(str(p) for p in parts).encode()).hexdigest()[:20]


def kv_get(ns: str, k: str, max_age: float | None = None) -> tuple[Any, float] | None:
    """Return (value, age_seconds) or None. If max_age is given and the row is older, still returned
    via kv_get_stale — callers decide whether stale data is acceptable."""
    with _lock:
        row = conn().execute("SELECT v, ts FROM kv WHERE ns=? AND k=?", (ns, k)).fetchone()
    if not row:
        return None
    age = time.time() - row[1]
    if max_age is not None and age > max_age:
        return None
    return json.loads(row[0]), age


def kv_get_stale(ns: str, k: str) -> tuple[Any, float] | None:
    return kv_get(ns, k, None)


def kv_set(ns: str, k: str, v: Any) -> None:
    with _lock:
        conn().execute("INSERT OR REPLACE INTO kv (ns, k, v, ts) VALUES (?,?,?,?)",
                       (ns, k, json.dumps(v, default=str), time.time()))
        conn().commit()


def execute(sql: str, args: tuple = ()) -> list[tuple]:
    with _lock:
        cur = conn().execute(sql, args)
        rows = cur.fetchall()
        conn().commit()
        return rows


# --- seed (pre-warmed cache) -------------------------------------------------

def _load_seed_if_empty(c: sqlite3.Connection) -> None:
    if not config.SEED_PATH.exists():
        return
    if c.execute("SELECT COUNT(*) FROM kv").fetchone()[0] > 0:
        return
    n = 0
    with gzip.open(config.SEED_PATH, "rt") as f:
        for line in f:
            r = json.loads(line)
            c.execute("INSERT OR REPLACE INTO kv (ns,k,v,ts) VALUES (?,?,?,?)", (r["ns"], r["k"], r["v"], r["ts"]))
            n += 1
    c.commit()
    print(f"[finn] loaded {n} seed cache rows")


def dump_seed(namespaces: list[str] | None = None) -> int:
    rows = execute("SELECT ns, k, v, ts FROM kv")
    n = 0
    with gzip.open(config.SEED_PATH, "wt") as f:
        for ns, k, v, ts in rows:
            if namespaces and ns not in namespaces:
                continue
            f.write(json.dumps({"ns": ns, "k": k, "v": v, "ts": ts}) + "\n")
            n += 1
    return n


# --- settings ----------------------------------------------------------------

DEFAULT_SETTINGS = {
    "window_hours": 24,
    "alert_categories": ["results", "M&A", "management_change", "fund_raise", "credit_rating",
                         "litigation", "pledging", "capex"],
    "volume_multiple": 2.0,
    "volume_lookback": 20,
    "price_move_pct": 4.0,
    "min_alert_priority": 60,
    "category_bias": {},       # learned from triage: category -> score delta
    "extra_symbols": [],
    "removed_symbols": [],
}


def get_settings() -> dict:
    scope = reviewer.get()
    if scope:
        data = kv_get("reviewer_settings", scope)
        return {**DEFAULT_SETTINGS, **(data[0] if data else {})}
    rows = execute("SELECT v FROM settings WHERE id=1")
    s = dict(DEFAULT_SETTINGS)
    if rows:
        s.update(json.loads(rows[0][0]))
    return s


def save_settings(patch: dict) -> dict:
    s = get_settings()
    s.update({k: v for k, v in patch.items() if k in DEFAULT_SETTINGS})
    scope = reviewer.get()
    if scope:
        kv_set("reviewer_settings", scope, s)
    else:
        execute("INSERT OR REPLACE INTO settings (id, v) VALUES (1, ?)", (json.dumps(s),))
    return s
