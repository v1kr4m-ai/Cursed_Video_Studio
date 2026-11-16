import shutil
import subprocess

import pytest
from pydantic import ValidationError

from cineflow.color_service import ColorError, find_lut, profile_for
from cineflow.db import connect, migrate
from cineflow.edit_plan import Crop, EditPlan, PlanError, Shot, View
from cineflow.media_ingest import ingest_folder
from cineflow.metadata_service import probe
from cineflow.project_service import create_project, list_assets
from cineflow.reframe_service import FlatCropAdapter, fovs
from cineflow.render_service import render
from cineflow.tools import find_tool

from .conftest import SAMPLE_DIR


def test_fovs_long_side():
    # 2*atan(tan(50°) * 9/16) = 67.67°
    h, v = fovs(100, 1920, 1080)
    assert h == 100 and v == pytest.approx(67.67, abs=0.01)
    h, v = fovs(100, 1080, 1920)
    assert v == 100 and h == pytest.approx(67.67, abs=0.01)


def test_flat_crop_box_916_from_169():
    cw, ch, x, y = FlatCropAdapter.crop_box(1920, 1080, 1080, 1920, Crop(x=0.5))
    assert (cw, ch) == (608, 1080) and x == (1920 - 608) // 2 and y == 0  # 607.5 -> even 608
    assert FlatCropAdapter.crop_box(1920, 1080, 1080, 1920, Crop(x=0))[2] == 0


def test_plan_validation():
    with pytest.raises(ValidationError):
        Shot(asset_id="a", source_in=5, source_out=5.2)          # too short
    with pytest.raises(ValidationError):
        Shot(asset_id="a", source_in=0, source_out=3, view=View(fov=170))  # out of range
    with pytest.raises(ValidationError):
        EditPlan(project_id="p", timeline=[])


def test_unknown_colour_mode_refuses():
    with pytest.raises(ColorError):
        profile_for(None, "flat")
    with pytest.raises(ColorError):
        profile_for("dlog_m", "flat")  # no validated LUT for other cameras


@pytest.fixture
def project(tmp_path, media):
    card = tmp_path / "card"
    card.mkdir()
    shutil.copy(media["osv"], card / "A_D.OSV")
    shutil.copy(media["flat"], card / "b.mp4")
    conn = connect(tmp_path / "c.db")
    migrate(conn)
    pid = create_project(conn, "p", tmp_path / "work")
    ingest_folder(conn, pid, card)
    conn.execute("UPDATE assets SET color_mode='normal', color_mode_source='user' WHERE project_id=?", (pid,))
    ids = {r["path"].rsplit("\\", 1)[-1].rsplit("/", 1)[-1]: r["id"] for r in list_assets(conn, pid)}
    return conn, pid, ids


@pytest.mark.parametrize("preset,size", [("master_16x9", (2688, 1512)), ("short_9x16", (1080, 1920))])
def test_render_mixed_timeline(project, tmp_path, preset, size):
    conn, pid, ids = project
    plan = EditPlan(project_id=pid, output={"preset": preset, "fps": "25/1"}, timeline=[
        Shot(asset_id=ids["A_D.OSV"], source_in=0, source_out=0.8, view=View(yaw=30, pitch=-10)),
        Shot(asset_id=ids["b.mp4"], source_in=0.1, source_out=0.9),
    ])
    out = tmp_path / f"{preset}.mp4"
    seen = []
    m = render(conn, plan, out, seen.append)
    info = probe(out)
    assert (info.video[0].width, info.video[0].height) == size
    assert abs(info.duration_s - 1.6) < 0.1
    assert [s["adapter"] for s in m["shots"]] == ["ffmpeg_v360", "flat_crop"]
    assert out.with_suffix(".manifest.json").exists()
    assert seen[-1] == 1.0
    if preset == "master_16x9":
        assert any("upscaled" in w for w in m["warnings"])  # 320x180 test clip to 2.7K


def test_render_with_music(project, tmp_path):
    conn, pid, ids = project
    music = tmp_path / "m.wav"
    subprocess.run([find_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=5", str(music)], check=True)
    plan = EditPlan(project_id=pid, audio={"music_path": str(music), "fade_out_s": 0.5}, output={"fps": "25/1"},
                    timeline=[Shot(asset_id=ids["b.mp4"], source_in=0, source_out=0.9)])
    out = tmp_path / "m.mp4"
    render(conn, plan, out)
    info = probe(out)
    assert info.has_audio and abs(info.duration_s - 0.9) < 0.1


def test_render_rejects_bad_times(project, tmp_path):
    conn, pid, ids = project
    plan = EditPlan(project_id=pid, timeline=[Shot(asset_id=ids["b.mp4"], source_in=0, source_out=30)])
    with pytest.raises(PlanError, match="clip is"):
        render(conn, plan, tmp_path / "x.mp4")


@pytest.mark.sample
@pytest.mark.skipif(not SAMPLE_DIR.is_dir(), reason="sample footage not present")
def test_real_dlogm_short(tmp_path):
    find_lut("DJI Avata 360 D-Log M to Rec.709 V1.cube")
    conn = connect(tmp_path / "c.db")
    migrate(conn)
    pid = create_project(conn, "p", tmp_path / "work")
    ingest_folder(conn, pid, SAMPLE_DIR)  # reads originals in place, never writes them
    a = next(r for r in list_assets(conn, pid) if r["path"].endswith("DJI_20261026182115_0002_D.OSV"))
    assert a["color_mode"] == "dlog_m"
    plan = EditPlan(project_id=pid, output={"preset": "short_9x16"}, timeline=[
        Shot(asset_id=a["id"], source_in=160, source_out=162, view=View(yaw=0, pitch=-10, fov=95)),
        Shot(asset_id=a["id"], source_in=200, source_out=202, view=View(yaw=90, pitch=-5, fov=95)),
    ])
    m = render(conn, plan, tmp_path / "short.mp4")
    info = probe(tmp_path / "short.mp4")
    assert (info.video[0].width, info.video[0].height) == (1080, 1920)
    assert abs(info.duration_s - 4.0) < 0.15
    assert all(s["color_profile"] == "avata360_dlogm_rec709_v1" for s in m["shots"])
