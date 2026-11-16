import json
import subprocess
import sys
import time

import pytest

from cineflow.agent_orchestrator import (Handler, InvalidTransition, State, cancel, create_job, get_job,
                                         recover, run_until_idle, transition)
from cineflow.db import connect, migrate
from cineflow.project_service import create_project


@pytest.fixture
def setup(tmp_path):
    conn = connect(tmp_path / "c.db")
    migrate(conn)
    return conn, create_project(conn, "p", tmp_path / "w"), tmp_path / "c.db"


def ok_handler(conn, job, report):
    report(0.5)
    return {"echo": json.loads(job["inputs_json"])["x"]}


def boom(conn, job, report):
    raise RuntimeError("disk full")


def test_success_records_outputs_and_history(setup):
    conn, pid, _ = setup
    jid = create_job(conn, pid, "t", {"x": 7})
    assert run_until_idle(conn, {"t": Handler(State.INGESTING, ok_handler)}) == 1
    job = get_job(conn, jid)
    assert job["state"] == "COMPLETED" and job["progress"] == 1.0
    assert json.loads(job["outputs_json"]) == {"echo": 7}
    states = [r[0] for r in conn.execute("SELECT to_state FROM job_events WHERE job_id = ? ORDER BY id", (jid,))]
    assert states == ["NEW", "INGESTING", "COMPLETED"]


def test_failure_is_recorded_and_retryable(setup):
    conn, pid, _ = setup
    jid = create_job(conn, pid, "t", {})
    run_until_idle(conn, {"t": Handler(State.INGESTING, boom)})
    job = get_job(conn, jid)
    assert job["state"] == "FAILED" and "disk full" in job["error"]
    transition(conn, jid, State.NEW, "user retry")
    assert get_job(conn, jid)["state"] == "NEW"


def test_terminal_states_are_final(setup):
    conn, pid, _ = setup
    jid = create_job(conn, pid, "t", {})
    cancel(conn, jid)
    with pytest.raises(InvalidTransition):
        transition(conn, jid, State.INGESTING)


def test_cancel_during_run(setup):
    conn, pid, _ = setup
    jid = create_job(conn, pid, "t", {})

    def handler(c, job, report):
        cancel(c, job["id"])
        report(0.1)  # must raise Cancelled
        raise AssertionError("not reached")

    run_until_idle(conn, {"t": Handler(State.INGESTING, handler)})
    assert get_job(conn, jid)["state"] == "CANCELLED"


WORKER = """
import sys, time
from cineflow.agent_orchestrator import Handler, State, run_until_idle
from cineflow.db import connect
def slow(conn, job, report):
    for i in range(600):
        report(i / 600); time.sleep(0.05)
    return {}
run_until_idle(connect(sys.argv[1]), {"slow": Handler(State.PROXYING, slow)})
"""


def test_job_resumes_after_worker_is_killed(setup):
    conn, pid, db_path = setup
    jid = create_job(conn, pid, "slow", {})
    p = subprocess.Popen([sys.executable, "-c", WORKER, str(db_path)])
    try:
        deadline = time.time() + 20
        while time.time() < deadline:
            job = get_job(conn, jid)
            if job["state"] == "PROXYING" and job["progress"] > 0:
                break
            time.sleep(0.1)
        else:
            pytest.fail("worker never started the job")
    finally:
        p.kill()
        p.wait()

    assert get_job(conn, jid)["state"] == "PROXYING"  # stranded by the kill
    assert recover(conn) == [jid]
    assert get_job(conn, jid)["retries"] == 1
    run_until_idle(conn, {"slow": Handler(State.PROXYING, ok_handler_noinput)})
    assert get_job(conn, jid)["state"] == "COMPLETED"


def ok_handler_noinput(conn, job, report):
    return {}
