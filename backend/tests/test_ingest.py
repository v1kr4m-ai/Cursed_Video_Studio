import json
import shutil

import pytest

from cineflow.db import connect, migrate
from cineflow.media_ingest import discover, ingest_folder, quick_hash
from cineflow.project_service import create_project, list_assets, storage_estimate, write_manifest

from .conftest import SAMPLE_DIR


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "c.db")
    migrate(conn)
    return conn


@pytest.fixture
def footage(tmp_path, media):
    """Nested folder: OSV + matching LRF, a flat clip, a byte-identical copy, a broken file, a text file."""
    root = tmp_path / "card"
    (root / "DCIM" / "sub").mkdir(parents=True)
    shutil.copy(media["osv"], root / "DCIM" / "DJI_0001_D.OSV")
    shutil.copy(media["lrf"], root / "DCIM" / "DJI_0001_D.LRF")
    shutil.copy(media["flat"], root / "DCIM" / "sub" / "clip.mp4")
    shutil.copy(media["flat"], root / "DCIM" / "sub" / "clip_copy.mp4")
    shutil.copy(media["truncated"], root / "DCIM" / "broken.mp4")
    (root / "DCIM" / "readme.txt").write_text("ignore me")
    return root


def test_discover_finds_videos_only(footage):
    names = sorted(p.name for p in discover(footage))
    assert names == ["DJI_0001_D.LRF", "DJI_0001_D.OSV", "broken.mp4", "clip.mp4", "clip_copy.mp4"]


def test_ingest_classifies_links_and_flags(db, footage, tmp_path):
    before = {p: p.read_bytes() for p in discover(footage)}
    pid = create_project(db, "trip", tmp_path / "work")
    rep = ingest_folder(db, pid, footage)
    assert (rep.found, rep.added, rep.duplicates, rep.corrupt, rep.linked_proxies) == (5, 5, 1, 1, 1)

    by_name = {r["path"].replace("\\", "/").rsplit("/", 1)[1]: r for r in list_assets(db, pid)}
    assert by_name["DJI_0001_D.OSV"]["kind"] == "dual_fisheye"
    assert by_name["DJI_0001_D.LRF"]["proxy_of"] == by_name["DJI_0001_D.OSV"]["id"]
    assert by_name["clip_copy.mp4"]["status"] == "duplicate"
    assert by_name["broken.mp4"]["status"] == "corrupt" and by_name["broken.mp4"]["error"]

    # Originals untouched.
    assert all(p.read_bytes() == b for p, b in before.items())


def test_ingest_is_resumable(db, footage, tmp_path):
    pid = create_project(db, "trip", tmp_path / "work")
    ingest_folder(db, pid, footage)
    again = ingest_folder(db, pid, footage)
    assert (again.added, again.skipped_existing) == (0, 5)
    assert len(list_assets(db, pid)) == 5


def test_quick_hash_detects_change(tmp_path):
    f = tmp_path / "a.bin"
    f.write_bytes(b"x" * 100)
    h1 = quick_hash(f)
    f.write_bytes(b"x" * 99 + b"y")
    assert quick_hash(f) != h1


def test_manifest_and_estimate(db, footage, tmp_path):
    pid = create_project(db, "trip", tmp_path / "work")
    ingest_folder(db, pid, footage)
    est = storage_estimate(db, pid)
    assert est["assets"] == 2  # OSV + clip.mp4; LRF proxy, duplicate and broken file excluded
    m = json.loads(write_manifest(db, pid).read_text())
    assert m["project"]["name"] == "trip" and len(m["assets"]) == 5
    assert not (tmp_path / "work" / "manifest.json.tmp").exists()


@pytest.mark.sample
@pytest.mark.skipif(not SAMPLE_DIR.is_dir(), reason="sample footage not present")
def test_ingest_real_folder(db, tmp_path):
    pid = create_project(db, "avata", tmp_path / "work")
    rep = ingest_folder(db, pid, SAMPLE_DIR)
    # Counts are lower bounds: the user keeps adding clips to this folder.
    assert rep.found >= 13 and rep.corrupt == 0 and rep.duplicates == 0
    assert rep.linked_proxies >= 6
    est = storage_estimate(db, pid)
    assert est["assets"] >= 7 and est["source_seconds"] > 1100


def test_offline_and_relink(db, footage, tmp_path):
    """Card unplugged: render refuses clearly; card back under another 'drive letter': relink finds it."""
    from cineflow.auto_plan import AutoPlanError, build_plan
    from cineflow.edit_plan import EditPlan, PlanError, Shot, check_against_assets
    from cineflow.media_ingest import relink

    pid = create_project(db, "trip", tmp_path / "work")
    ingest_folder(db, pid, footage)
    db.execute("UPDATE assets SET color_mode='normal'")
    clip = next(r for r in list_assets(db, pid) if r["path"].endswith("clip.mp4"))

    moved = tmp_path / "other_drive"
    shutil.move(str(footage), str(moved))   # card removed / remounted elsewhere

    plan = EditPlan(project_id=pid, timeline=[Shot(asset_id=clip["id"], source_in=0, source_out=0.8)])
    with pytest.raises(PlanError, match="offline"):
        check_against_assets(plan, {clip["id"]: dict(clip)})
    with pytest.raises(AutoPlanError, match="offline"):
        build_plan(db, pid, target_s=5, shot_s=1)

    r = relink(db, pid, moved)
    assert r["relinked"] == 5 and r["still_offline"] == 0
    new_path = db.execute("SELECT path FROM assets WHERE id = ?", (clip["id"],)).fetchone()[0]
    assert new_path.startswith(str(moved))
