import json
import shutil

import pytest

from cineflow.agent_orchestrator import Handler, State, create_job, get_job, run_until_idle
from cineflow.db import connect, migrate
from cineflow.media_ingest import ingest_folder
from cineflow.metadata_service import probe
from cineflow.project_service import create_project
from cineflow.proxy_service import build_project_proxies

from .conftest import SAMPLE_DIR


def test_proxies_via_job(tmp_path, media):
    root = tmp_path / "card"
    root.mkdir()
    shutil.copy(media["osv"], root / "A_D.OSV")
    shutil.copy(media["lrf"], root / "A_D.LRF")
    shutil.copy(media["flat"], root / "b.mp4")
    conn = connect(tmp_path / "c.db")
    migrate(conn)
    pid = create_project(conn, "p", tmp_path / "work")
    ingest_folder(conn, pid, root)

    seen = []
    jid = create_job(conn, pid, "proxy", {})
    run_until_idle(conn, {"proxy": Handler(State.PROXYING,
                                           lambda c, job, rep: build_project_proxies(c, job["project_id"], lambda f: (seen.append(f), rep(f))))})
    job = get_job(conn, jid)
    assert job["state"] == "COMPLETED", job["error"]
    outs = json.loads(job["outputs_json"])
    assert len(outs) == 2  # OSV (via its LRF) and the flat clip; LRF itself gets no proxy

    for o in outs.values():
        info = probe(o["proxy"])
        assert info.video[0].fps == "25/1"
        assert o["thumbnail"].endswith(".jpg")
    osv_out = next(o for o in outs.values() if o["source"].endswith("A_D.LRF"))
    p = probe(osv_out["proxy"]).video[0]
    assert (p.width, p.height) == (1920, 960)  # equirectangular preview
    assert seen == sorted(seen) and seen[-1] == pytest.approx(1.0)  # real, monotonic progress
    assert not list((tmp_path / "work" / "proxies").glob("*.tmp.*"))


@pytest.mark.sample
@pytest.mark.skipif(not SAMPLE_DIR.is_dir(), reason="sample footage not present")
def test_real_lrf_preview(tmp_path):
    """One real clip: LRF -> equirectangular preview; checks dimensions and duration only."""
    from cineflow.proxy_service import make_proxy
    lrf = SAMPLE_DIR / "DJI_20260429215709_0002_D.LRF"  # the 20 s clip
    out = make_proxy(probe(lrf), str(lrf), tmp_path / "p.mp4")
    info = probe(out)
    assert (info.video[0].width, info.video[0].height) == (1920, 960)
    assert abs(info.duration_s - 19.96) < 0.2
