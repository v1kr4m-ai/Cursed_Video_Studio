import shutil
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from cineflow.api import app
from cineflow.auto_plan import AutoPlanError, build_plan
from cineflow.db import connect, migrate
from cineflow.media_ingest import ingest_folder
from cineflow.project_service import create_project, list_assets
from cineflow.reference_service import ReferenceError, analyse, validate_url
from cineflow.tools import find_tool


def ff(*a):
    subprocess.run([find_tool("ffmpeg"), "-hide_banner", "-v", "error", "-y", *a], check=True)


@pytest.fixture
def long_project(tmp_path):
    """Two 20 s clips (usable after skipping 5 s at each end), colour mode set."""
    card = tmp_path / "card"
    card.mkdir()
    for n, src in (("a.mp4", "testsrc2"), ("b.mp4", "smptebars")):
        ff("-f", "lavfi", "-i", f"{src}=s=320x180:r=25:d=20", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(card / n))
    conn = connect(tmp_path / "c.db")
    migrate(conn)
    pid = create_project(conn, "p", tmp_path / "work")
    ingest_folder(conn, pid, card)
    conn.execute("UPDATE assets SET color_mode='normal', color_mode_source='user'")
    return conn, pid, card, tmp_path


def test_auto_plan_spreads_shots(long_project):
    conn, pid, _, _ = long_project
    plan = build_plan(conn, pid, "short_9x16", target_s=12, shot_s=3, effects=True)
    assert len(plan.timeline) == 4 and plan.duration_s == pytest.approx(12, abs=0.1)
    for s in plan.timeline:
        assert s.source_in >= 5 and s.source_out <= 15 + 1e-6  # take-off/landing skipped
        assert s.effect == "none"                               # flat clips get no 360 effects
    assert {s.asset_id for s in plan.timeline} == {r["id"] for r in list_assets(conn, pid)}


def test_auto_plan_refuses_without_colour_mode(long_project):
    conn, pid, _, _ = long_project
    conn.execute("UPDATE assets SET color_mode=NULL")
    with pytest.raises(AutoPlanError):
        build_plan(conn, pid)


def test_reference_analysis_finds_cuts(tmp_path):
    ref = tmp_path / "ref.mp4"
    ff("-f", "lavfi", "-i", "testsrc2=s=640x360:r=25:d=2", "-f", "lavfi", "-i", "color=c=red:s=640x360:r=25:d=2",
       "-f", "lavfi", "-i", "smptebars=s=640x360:r=25:d=2",
       "-filter_complex", "[0][1][2]concat=n=3:v=1", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(ref))
    p = analyse(ref, str(ref))
    assert len(p.cuts) == 2 and p.cuts[0] == pytest.approx(2, abs=0.1) and p.cuts[1] == pytest.approx(4, abs=0.1)
    assert p.shot_len_median == pytest.approx(2, abs=0.15)
    assert not p.vertical and not p.has_audio


def test_url_allowlist():
    assert validate_url("https://www.youtube.com/shorts/abc")
    assert validate_url("https://www.instagram.com/reel/xyz/")
    for bad in ("file:///C:/x.mp4", "https://evil.example/youtube.com", "ftp://youtube.com/x"):
        with pytest.raises(ReferenceError):
            validate_url(bad)


def test_render_and_reference_endpoints(long_project, monkeypatch, tmp_path):
    conn, pid, card, _ = long_project
    monkeypatch.setenv("CINEFLOW_DB", str(tmp_path / "c.db"))
    with TestClient(app) as c:
        jid = c.post(f"/projects/{pid}/render", json={"preset": "square_1x1", "target_s": 6, "shot_s": 2,
                                                       "stabilize": False}).json()["job_id"]
        end = time.time() + 120
        while (j := c.get(f"/jobs/{jid}").json())["state"] not in ("COMPLETED", "FAILED") and time.time() < end:
            time.sleep(0.3)
        assert j["state"] == "COMPLETED", j["error"]
        ex = c.get(f"/projects/{pid}/exports").json()
        assert ex and ex[0]["render"]["width"] == 1080
        assert c.get(f"/projects/{pid}/exports/{ex[0]['name']}").status_code == 200
        assert c.get(f"/projects/{pid}/exports/..%5Cc.db").status_code in (404, 422)

        jr = c.post(f"/projects/{pid}/references", json={"source": str(card / "a.mp4")}).json()["job_id"]
        while (j := c.get(f"/jobs/{jr}").json())["state"] not in ("COMPLETED", "FAILED"):
            time.sleep(0.3)
        assert j["state"] == "COMPLETED", j["error"]
        refs = c.get(f"/projects/{pid}/references").json()
        assert len(refs) == 1 and refs[0]["duration_s"] == pytest.approx(20, abs=0.2)
        assert c.post(f"/projects/{pid}/references", json={"source": "https://evil.example/x"}).status_code == 422
