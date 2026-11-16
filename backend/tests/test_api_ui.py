from cineflow.db import connect
import cineflow.api as api
from tests.test_db_api import client  # noqa: F401  (fixture)


def _asset(tmp_path, pid):
    conn = connect(api.db_path())
    conn.execute("INSERT INTO assets (id, project_id, path, size_bytes, quick_hash, kind, duration_s, probe_json)"
                 " VALUES ('a1', ?, 'x.mp4', 1, 'h', 'flat', 1, '{}')", (pid,))


def test_list_thumbnail_patch_cors(client, tmp_path):
    assert client.get("/projects").json() == []
    work = tmp_path / "work"
    pid = client.post("/projects", json={"name": "p", "work_dir": str(work)}).json()["id"]
    assert [p["id"] for p in client.get("/projects").json()] == [pid]
    _asset(tmp_path, pid)

    assert client.get("/assets/a1/thumbnail").status_code == 404
    assert client.get("/assets/nope/thumbnail").status_code == 404
    (work / "proxies").mkdir()
    (work / "proxies" / "a1.jpg").write_bytes(b"\xff\xd8jpg")
    r = client.get("/assets/a1/thumbnail")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"

    for v in ("dlog_m", "normal"):
        assert client.patch("/assets/a1", json={"color_mode": v}).status_code == 200
    row = [a for a in client.get(f"/projects/{pid}/assets").json()][0]
    assert row["color_mode"] == "normal" and row["color_mode_source"] == "user"
    for bad in ("DLOG", "", None, 3):
        assert client.patch("/assets/a1", json={"color_mode": bad}).status_code == 422
    assert client.patch("/assets/a1", json={}).status_code == 422
    assert client.patch("/assets/zzz", json={"color_mode": "normal"}).status_code == 404

    h = {"Origin": "http://tauri.localhost"}
    assert client.get("/projects", headers=h).headers["access-control-allow-origin"] == h["Origin"]
    assert "access-control-allow-origin" not in client.get("/projects", headers={"Origin": "http://evil.com"}).headers
