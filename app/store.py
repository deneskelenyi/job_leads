"""SQLite storage: dedupe + query. One connection, small lock — volumes are tiny."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import DATA_DIR

DB_PATH = DATA_DIR / "jobs.db"
_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def init() -> None:
    global _conn
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    _conn.execute("PRAGMA journal_mode=WAL")
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            source TEXT NOT NULL,
            external_id TEXT NOT NULL,
            title TEXT, company TEXT, url TEXT, location TEXT, salary TEXT,
            published TEXT, description TEXT,
            score INTEGER, prototype_fit INTEGER, matched TEXT,
            inserted_at TEXT NOT NULL,
            PRIMARY KEY (source, external_id)
        )""")
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT, external_id TEXT, created_at TEXT, draft TEXT,
            UNIQUE (source, external_id)
        )""")
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY, value TEXT
        )""")
    _conn.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def insert_new(job: dict) -> bool:
    """Insert if unseen. Returns True when the job is new."""
    with _lock:
        cur = _conn.execute(
            "INSERT OR IGNORE INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (job["source"], job["external_id"], job.get("title", ""),
             job.get("company", ""), job.get("url", ""), job.get("location", ""),
             job.get("salary", ""), job.get("published", ""),
             (job.get("description") or "")[:4000], int(job.get("score", 0)),
             int(job.get("prototype_fit", 0)),
             json.dumps(job.get("matched", {})), _now()))
        _conn.commit()
        return cur.rowcount > 0


def list_jobs(min_score: int = 0, limit: int = 50, new_since: str | None = None) -> list[dict]:
    q = ("SELECT source, external_id, title, company, url, location, salary, "
         "published, description, score, prototype_fit, matched, inserted_at "
         "FROM jobs WHERE score >= ?")
    params: list[Any] = [min_score]
    if new_since:
        q += " AND inserted_at >= ?"
        params.append(new_since)
    q += " ORDER BY score DESC, inserted_at DESC LIMIT ?"
    params.append(limit)
    with _lock:
        rows = _conn.execute(q, params).fetchall()
    out = []
    for r in rows:
        out.append({
            "source": r[0], "external_id": r[1], "title": r[2], "company": r[3],
            "url": r[4], "location": r[5], "salary": r[6], "published": r[7],
            "description": r[8], "score": r[9], "prototype_fit": r[10],
            "matched": json.loads(r[11] or "{}"), "inserted_at": r[12],
        })
    return out


def get_job(source: str, external_id: str) -> dict | None:
    q = ("SELECT source, external_id, title, company, url, location, salary, "
         "published, description, score, prototype_fit, matched, inserted_at "
         "FROM jobs WHERE source=? AND external_id=?")
    with _lock:
        r = _conn.execute(q, (source, external_id)).fetchone()
    if not r:
        return None
    return {
        "source": r[0], "external_id": r[1], "title": r[2], "company": r[3],
        "url": r[4], "location": r[5], "salary": r[6], "published": r[7],
        "description": r[8], "score": r[9], "prototype_fit": r[10],
        "matched": json.loads(r[11] or "{}"), "inserted_at": r[12],
    }


def save_draft(source: str, external_id: str, draft: str) -> None:
    with _lock:
        _conn.execute(
            "INSERT INTO drafts (source, external_id, created_at, draft) VALUES (?,?,?,?) "
            "ON CONFLICT(source, external_id) DO UPDATE SET draft=excluded.draft, "
            "created_at=excluded.created_at",
            (source, external_id, _now(), draft))
        _conn.commit()


def get_draft(source: str, external_id: str) -> str | None:
    with _lock:
        row = _conn.execute(
            "SELECT draft FROM drafts WHERE source=? AND external_id=?",
            (source, external_id)).fetchone()
    return row[0] if row else None


def meta_get(key: str, default: str = "") -> str:
    with _lock:
        row = _conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return row[0] if row else default


def meta_set(key: str, value: str) -> None:
    with _lock:
        _conn.execute(
            "INSERT INTO meta (key, value) VALUES (?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        _conn.commit()
