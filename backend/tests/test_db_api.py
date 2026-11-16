import shutil
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient

from cineflow.api import app
from cineflow.db import connect, migrate


def test_migrate_is_idempotent(tmp_path):
    conn = connect(tmp_path / "c.db")
    assert migrate(conn) == ["0001_init"]
    assert migrate(conn) == []
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"projects", "assets", "jobs", "job_events"} <= tables


def test_foreign_keys_enforced(tmp_path):
    conn = connect(tmp_path / "c.db")
    migrate(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO jobs (id, project_id, type, pipeline_version) VALUES ('j', 'missing', 'x', '0')")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CINEFLOW_DB", str(tmp_path / "api.db"))
    with TestClient(app) as c:  # runs lifespan: migrate, recover, start worker
        yield c


def wait_job(c, jid, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        j = c.get(f"/jobs/{jid}").json()
        if j["state"] in ("COMPLETED", "FAILED", "CANCELLED"):
            return j
        time.sleep(0.2)
    raise AssertionError(f"job {jid} stuck: {j['state']}")


def test_health_and_probe(client, media):
    h = client.get("/health").json()
    assert h["status"] == "ok" and h["tools"]["ffprobe"]
    r = client.post("/probe", json={"path": str(media["osv"])})
    assert r.status_code == 200 and r.json()["kind"] == "dual_fisheye"
    assert client.post("/probe", json={"path": str(media["not_video"])}).status_code == 422


def test_import_flow_end_to_end(client, media, tmp_path):
    card = tmp_path / "card"
    card.mkdir()
    shutil.copy(media["osv"], card / "X_D.OSV")
    shutil.copy(media["lrf"], card / "X_D.LRF")
    shutil.copy(media["flat"], card / "y.mp4")

    pid = client.post("/projects", json={"name": "t", "work_dir": str(tmp_path / "work")}).json()["id"]
    assert client.post(f"/projects/{pid}/ingest", json={"folder": str(tmp_path / "nope")}).status_code == 422
    jid = client.post(f"/projects/{pid}/ingest", json={"folder": str(card)}).json()["job_id"]

    ing = wait_job(client, jid)
    assert ing["state"] == "COMPLETED", ing["error"]
    assert ing["outputs"]["added"] == 3 and ing["outputs"]["linked_proxies"] == 1
    assert [e["to_state"] for e in ing["events"]] == ["NEW", "INGESTING", "COMPLETED"]

    prox = wait_job(client, ing["outputs"]["proxy_job"])
    assert prox["state"] == "COMPLETED", prox["error"]
    assert len(prox["outputs"]) == 2

    a = client.get(f"/projects/{pid}/assets").json()
    assert {x["kind"] for x in a} == {"dual_fisheye", "dual_fisheye_proxy", "flat"}
    assert client.get(f"/projects/{pid}").json()["storage"]["assets"] == 2
    assert client.post(f"/jobs/{jid}/cancel").status_code == 409  # finished jobs can't be cancelled
