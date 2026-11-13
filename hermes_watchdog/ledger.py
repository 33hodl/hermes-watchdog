"""Durable repair ledger — one row per repair attempt, in the plugin's own DB.

The ledger is what makes the plugin honest: a repair that "worked" is a row with an
outcome, and a bounded number of attempts per incident per day stops a repair loop
from becoming a second failure mode. It also feeds the pane's recent-activity list.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

PLUGIN_ID = "hermes-watchdog"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS repairs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id TEXT NOT NULL,
    job_id      TEXT NOT NULL DEFAULT '',
    job_name    TEXT NOT NULL DEFAULT '',
    playbook    TEXT NOT NULL DEFAULT '',
    source      TEXT NOT NULL DEFAULT '',
    started_at  REAL NOT NULL,
    finished_at REAL,
    outcome     TEXT NOT NULL DEFAULT 'running',
    detail      TEXT NOT NULL DEFAULT '',
    demo        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS repairs_incident ON repairs(incident_id, started_at);
CREATE INDEX IF NOT EXISTS repairs_started ON repairs(started_at);
"""

# Columns added after the first release. SQLite has no "ADD COLUMN IF NOT EXISTS", so
# an older ledger gets them by hand — the pane must never crash on a stale DB.
_MIGRATIONS = (("demo", "INTEGER NOT NULL DEFAULT 0"),)


def _fallback_db_path() -> Path:
    """Where the ledger lives when the host's plugin storage is unavailable.

    A bare checkout (CI, a reviewer running the tests, a host build that renamed
    `plugins.plugin_storage`) has no core storage module. Falling back to a file
    under `$HERMES_HOME/plugin-data/<plugin>/` keeps the ledger and the pane
    working instead of raising on every dashboard request.
    """
    base = os.environ.get("HERMES_HOME")
    root = Path(base) if base else Path.home() / ".hermes"
    return root / "plugin-data" / PLUGIN_ID / "ledger.db"


_CORE_STORAGE_WARNED = False


def _conn() -> sqlite3.Connection:
    global _CORE_STORAGE_WARNED
    try:
        from plugins.plugin_storage import plugin_db
    except Exception:  # noqa: BLE001 - a bare checkout has no core storage module
        plugin_db = None
    if plugin_db is not None:
        conn = plugin_db(PLUGIN_ID)
    else:
        if not _CORE_STORAGE_WARNED:
            log.warning(
                "watchdog: host plugin storage unavailable; ledger is plugin-local at %s",
                _fallback_db_path(),
            )
            _CORE_STORAGE_WARNED = True
        path = _fallback_db_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path)
    conn.executescript(_SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    try:
        have = {row[1] for row in conn.execute("PRAGMA table_info(repairs)").fetchall()}
    except Exception as exc:  # noqa: BLE001 - a locked/odd DB must not break the pane
        log.debug("watchdog: ledger migration skipped: %s", exc)
        return
    for column, ddl in _MIGRATIONS:
        if column not in have:
            try:
                conn.execute(f"ALTER TABLE repairs ADD COLUMN {column} {ddl}")
                conn.commit()
            except Exception as exc:  # noqa: BLE001
                log.debug("watchdog: could not add %s: %s", column, exc)


def start_attempt(
    incident_id: str, job_id: str, job_name: str, playbook: str, source: str,
) -> int:
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO repairs (incident_id, job_id, job_name, playbook, source, started_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (incident_id, job_id, job_name, playbook, source, time.time()),
    )
    conn.commit()
    return int(cur.lastrowid)


def finish_attempt(repair_id: int, outcome: str, detail: str = "") -> None:
    conn = _conn()
    conn.execute(
        "UPDATE repairs SET finished_at = ?, outcome = ?, detail = ? WHERE id = ?",
        (time.time(), outcome, detail[:2000], repair_id),
    )
    conn.commit()


def attempts_today(incident_id: str) -> int:
    """Attempts for this incident in the last 24h — the budget the playbook author set."""
    conn = _conn()
    row = conn.execute(
        "SELECT COUNT(*) FROM repairs WHERE incident_id = ? AND started_at >= ?",
        (incident_id, time.time() - 86400),
    ).fetchone()
    return int(row[0]) if row else 0


def last_attempt(incident_id: str) -> Optional[Dict[str, Any]]:
    """The newest attempt for one incident, or None. Drives the auto-close rule."""
    conn = _conn()
    row = conn.execute(
        "SELECT incident_id, job_id, job_name, playbook, started_at, outcome, detail "
        "FROM repairs WHERE incident_id = ? ORDER BY started_at DESC LIMIT 1",
        (incident_id,),
    ).fetchone()
    if not row:
        return None
    # plugin_db hands back plain tuples (see recent()); dict(row) would raise.
    keys = ("incident_id", "job_id", "job_name", "playbook", "started_at", "outcome", "detail")
    return dict(zip(keys, row))


def recent(limit: int = 20) -> List[Dict[str, Any]]:
    conn = _conn()
    rows = conn.execute(
        "SELECT incident_id, job_id, job_name, playbook, source, started_at, finished_at, "
        "outcome, detail, demo FROM repairs ORDER BY started_at DESC LIMIT ?",
        (max(1, min(int(limit), 200)),),
    ).fetchall()
    return [_row_view(r) for r in rows]


def mark_demo(incident_id: str) -> int:
    """Tag the newest attempt for an incident as a demo, so it never counts as fleet health."""
    conn = _conn()
    row = conn.execute(
        "SELECT id FROM repairs WHERE incident_id = ? ORDER BY started_at DESC LIMIT 1",
        (incident_id,),
    ).fetchone()
    if not row:
        return 0
    conn.execute("UPDATE repairs SET demo = 1 WHERE id = ?", (int(row[0]),))
    conn.commit()
    return int(row[0])


def _row_view(row) -> Dict[str, Any]:
    return {
        "incident_id": row[0],
        "job_id": row[1],
        "job_name": row[2],
        "playbook": row[3],
        "source": row[4],
        "started_at": row[5],
        "finished_at": row[6],
        "outcome": row[7],
        "detail": row[8],
        "demo": bool(row[9]) if len(row) > 9 else False,
    }


def summary() -> Dict[str, Any]:
    """Counts for the pane header: repaired / failed in the last 7 days.

    Demo rows are excluded on purpose: the demo runs a real repair, but counting it
    would make the fleet look healthier than it is.
    """
    conn = _conn()
    since = time.time() - 7 * 86400
    out: Dict[str, Any] = {"repaired_7d": 0, "failed_7d": 0, "escalated_7d": 0}
    for outcome, key in (("repaired", "repaired_7d"), ("failed", "failed_7d"), ("escalated", "escalated_7d")):
        row = conn.execute(
            "SELECT COUNT(*) FROM repairs WHERE outcome = ? AND started_at >= ? AND demo = 0",
            (outcome, since),
        ).fetchone()
        out[key] = int(row[0]) if row else 0
    row = conn.execute("SELECT MAX(started_at) FROM repairs").fetchone()
    out["last_attempt_at"] = row[0] if row else None
    return out


def last_attempt_for(incident_id: str) -> Optional[Dict[str, Any]]:
    conn = _conn()
    row = conn.execute(
        "SELECT incident_id, job_id, job_name, playbook, source, started_at, finished_at, "
        "outcome, detail FROM repairs WHERE incident_id = ? ORDER BY started_at DESC LIMIT 1",
        (incident_id,),
    ).fetchone()
    return _row_view(row) if row else None
