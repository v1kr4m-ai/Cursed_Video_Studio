"""Persistent job state machine and single-process worker.

Every state change is a row in `job_events`, so the history survives crashes. On start-up,
`recover()` puts jobs that were mid-run back in the queue; handlers must therefore be safe to
re-run (ingest skips recorded files, proxies write to a temp name and rename).
"""

from __future__ import annotations

import json
import sqlite3
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum

from . import __version__


class State(StrEnum):
    NEW = "NEW"
    INGESTING = "INGESTING"
    PROXYING = "PROXYING"
    ANALYSING = "ANALYSING"
    PLANNING = "PLANNING"
    PLAN_READY = "PLAN_READY"
    REFRAMING = "REFRAMING"
    GRADING = "GRADING"
    EDITING = "EDITING"
    RENDERING = "RENDERING"
    QC = "QC"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"  # end state for utility jobs (ingest, proxy) that need no review
    WAITING_FOR_USER = "WAITING_FOR_USER"
    PAUSED = "PAUSED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


RUNNING = {State.INGESTING, State.PROXYING, State.ANALYSING, State.PLANNING, State.REFRAMING,
           State.GRADING, State.EDITING, State.RENDERING, State.QC}
TERMINAL = {State.APPROVED, State.COMPLETED, State.FAILED, State.CANCELLED}


class InvalidTransition(ValueError):
    pass


class Cancelled(Exception):
    pass


def _check(frm: State, to: State) -> None:
    if frm in TERMINAL and not (frm is State.FAILED and to is State.NEW):  # FAILED may be retried
        raise InvalidTransition(f"{frm} is final")
    if frm is to:
        raise InvalidTransition(f"already {to}")


def create_job(conn: sqlite3.Connection, project_id: str, type_: str, inputs: dict) -> str:
    jid = uuid.uuid4().hex
    conn.execute("BEGIN")
    conn.execute("INSERT INTO jobs (id, project_id, type, inputs_json, pipeline_version) VALUES (?, ?, ?, ?, ?)",
                 (jid, project_id, type_, json.dumps(inputs), __version__))
    conn.execute("INSERT INTO job_events (job_id, to_state, message) VALUES (?, 'NEW', 'created')", (jid,))
    conn.execute("COMMIT")
    return jid


def get_job(conn: sqlite3.Connection, job_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        raise KeyError(job_id)
    return row


def transition(conn: sqlite3.Connection, job_id: str, to: State, message: str | None = None,
               **fields) -> None:
    conn.execute("BEGIN IMMEDIATE")
    try:
        frm = State(conn.execute("SELECT state FROM jobs WHERE id = ?", (job_id,)).fetchone()["state"])
        _check(frm, to)
        sets = ["state = ?", "updated_at = datetime('now')"]
        vals: list = [to.value]
        if to in RUNNING and frm is State.NEW:
            sets.append("started_at = COALESCE(started_at, datetime('now'))")
        for k, v in fields.items():  # only internal callers; keys are fixed column names
            if k not in {"progress", "error", "outputs_json", "retries"}:
                raise ValueError(k)
            sets.append(f"{k} = ?")
            vals.append(v)
        conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", (*vals, job_id))
        conn.execute("INSERT INTO job_events (job_id, from_state, to_state, message) VALUES (?, ?, ?, ?)",
                     (job_id, frm.value, to.value, message))
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def cancel(conn: sqlite3.Connection, job_id: str) -> None:
    transition(conn, job_id, State.CANCELLED, "cancelled by user")


def recover(conn: sqlite3.Connection) -> list[str]:
    """Requeue jobs left in a running state by a crash or forced exit."""
    stuck = [r["id"] for r in conn.execute(
        f"SELECT id FROM jobs WHERE state IN ({','.join('?' * len(RUNNING))})", [s.value for s in RUNNING])]
    for jid in stuck:
        retries = get_job(conn, jid)["retries"] + 1
        transition(conn, jid, State.NEW, "requeued after restart", retries=retries, progress=0.0)
    return stuck


@dataclass
class Handler:
    running_state: State
    run: Callable[[sqlite3.Connection, sqlite3.Row, Callable[[float], None]], dict]


def run_next(conn: sqlite3.Connection, handlers: dict[str, Handler]) -> str | None:
    """Run the oldest NEW job whose type has a handler. Returns its id, or None if idle."""
    types = list(handlers)
    row = conn.execute(f"SELECT * FROM jobs WHERE state = 'NEW' AND type IN ({','.join('?' * len(types))}) "
                       "ORDER BY rowid LIMIT 1", types).fetchone()
    if row is None:
        return None
    h = handlers[row["type"]]
    transition(conn, row["id"], h.running_state, "started")

    def report(progress: float) -> None:
        state = conn.execute("SELECT state FROM jobs WHERE id = ?", (row["id"],)).fetchone()["state"]
        if state == State.CANCELLED:
            raise Cancelled
        conn.execute("UPDATE jobs SET progress = ?, updated_at = datetime('now') WHERE id = ?",
                     (max(0.0, min(1.0, progress)), row["id"]))

    try:
        outputs = h.run(conn, get_job(conn, row["id"]), report)
        transition(conn, row["id"], State.COMPLETED, "finished", progress=1.0,
                   outputs_json=json.dumps(outputs or {}))
    except Cancelled:
        pass  # state already CANCELLED
    except Exception as e:
        transition(conn, row["id"], State.FAILED, f"{type(e).__name__}: {e}",
                   error=traceback.format_exc()[-4000:])
    return row["id"]


def run_until_idle(conn: sqlite3.Connection, handlers: dict[str, Handler]) -> int:
    n = 0
    while run_next(conn, handlers):
        n += 1
    return n
