"""
EasyMyTicket Desktop Agent — Offline SQLite Queue

When the backend WebSocket is unreachable, tasks sent to the agent
(or results from completed tasks) are persisted in a local SQLite database.
On reconnection, the queue is drained automatically.

DB path: ~/.easymyticket/offline_queue.db  (overridable via AGENT_QUEUE_PATH)
"""
import asyncio
import json
import logging
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger("agent.offline_queue")

_DEFAULT_PATH = Path.home() / ".easymyticket" / "offline_queue.db"
QUEUE_PATH = Path(os.getenv("AGENT_QUEUE_PATH", str(_DEFAULT_PATH)))


# ─────────────────────────────────────────────────────────────────────────────
#  Schema
# ─────────────────────────────────────────────────────────────────────────────

_DDL = """
CREATE TABLE IF NOT EXISTS pending_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT    NOT NULL,
    payload     TEXT    NOT NULL,   -- JSON blob (task_result message)
    created_at  TEXT    NOT NULL,
    attempts    INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS pending_tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT    NOT NULL,
    payload     TEXT    NOT NULL,   -- JSON blob (task message from server)
    created_at  TEXT    NOT NULL,
    status      TEXT    DEFAULT 'queued'  -- queued | running | done
);
"""


# ─────────────────────────────────────────────────────────────────────────────
#  Connection helper
# ─────────────────────────────────────────────────────────────────────────────

@contextmanager
def _db():
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(QUEUE_PATH), check_same_thread=False)
    con.row_factory = sqlite3.Row
    try:
        con.executescript(_DDL)
        con.commit()
        yield con
    finally:
        con.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Write helpers
# ─────────────────────────────────────────────────────────────────────────────

def enqueue_result(task_id: str, payload: Dict[str, Any]) -> None:
    """
    Store a completed task result so it can be sent to the backend
    once the WebSocket reconnects.
    """
    with _db() as con:
        con.execute(
            "INSERT INTO pending_results (task_id, payload, created_at) VALUES (?, ?, ?)",
            (task_id, json.dumps(payload), datetime.now(timezone.utc).isoformat()),
        )
        con.commit()
    log.debug("Queued offline result for task %s", task_id)


def enqueue_task(task: Dict[str, Any]) -> None:
    """
    Store a server task that arrived but couldn't be executed (e.g. dependency
    missing) so it can be retried later.
    """
    task_id = task.get("task_id", "?")
    with _db() as con:
        con.execute(
            "INSERT INTO pending_tasks (task_id, payload, created_at) VALUES (?, ?, ?)",
            (task_id, json.dumps(task), datetime.now(timezone.utc).isoformat()),
        )
        con.commit()
    log.debug("Queued offline task %s for later execution", task_id)


# ─────────────────────────────────────────────────────────────────────────────
#  Drain helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_pending_results(limit: int = 50) -> List[Dict]:
    """Return up to `limit` unsent results, oldest first."""
    with _db() as con:
        rows = con.execute(
            "SELECT id, task_id, payload FROM pending_results ORDER BY id ASC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"_row_id": r["id"], "task_id": r["task_id"], **json.loads(r["payload"])} for r in rows]


def delete_result(row_id: int) -> None:
    """Remove a successfully sent result."""
    with _db() as con:
        con.execute("DELETE FROM pending_results WHERE id = ?", (row_id,))
        con.commit()


def get_pending_tasks(limit: int = 20) -> List[Dict]:
    """Return queued tasks that need execution."""
    with _db() as con:
        rows = con.execute(
            "SELECT id, payload FROM pending_tasks WHERE status='queued' ORDER BY id ASC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{"_row_id": r["id"], **json.loads(r["payload"])} for r in rows]


def mark_task_done(row_id: int) -> None:
    with _db() as con:
        con.execute("UPDATE pending_tasks SET status='done' WHERE id=?", (row_id,))
        con.commit()


# ─────────────────────────────────────────────────────────────────────────────
#  Drain coroutine — called once per successful WebSocket reconnect
# ─────────────────────────────────────────────────────────────────────────────

async def drain_to_websocket(ws) -> int:
    """
    Send all pending task results to the server over `ws`.
    Returns the number of results successfully flushed.
    """
    pending = get_pending_results()
    if not pending:
        return 0

    log.info("Draining %d offline result(s) to backend", len(pending))
    flushed = 0
    for item in pending:
        row_id = item.pop("_row_id")
        try:
            await ws.send(json.dumps(item))
            delete_result(row_id)
            flushed += 1
            await asyncio.sleep(0.05)   # avoid flooding
        except Exception as e:
            log.warning("Could not flush result %d: %s — will retry later", row_id, e)
            break

    if flushed:
        log.info("Flushed %d offline result(s)", flushed)
    return flushed


async def drain_pending_tasks(handle_task_fn) -> int:
    """
    Execute tasks that were queued while offline.
    `handle_task_fn` is the agent's existing handle_task coroutine.
    Returns the count of tasks executed.
    """
    pending = get_pending_tasks()
    if not pending:
        return 0

    log.info("Executing %d offline-queued task(s)", len(pending))
    executed = 0
    for item in pending:
        row_id = item.pop("_row_id")
        try:
            await handle_task_fn(item, ws=None)
            mark_task_done(row_id)
            executed += 1
        except Exception as e:
            log.warning("Offline task %s failed: %s", item.get("task_id"), e)

    return executed


def queue_stats() -> Dict[str, int]:
    """Return counts for dashboard / health check."""
    with _db() as con:
        results_cnt = con.execute("SELECT COUNT(*) FROM pending_results").fetchone()[0]
        tasks_cnt = con.execute(
            "SELECT COUNT(*) FROM pending_tasks WHERE status='queued'"
        ).fetchone()[0]
    return {"pending_results": results_cnt, "pending_tasks": tasks_cnt}
