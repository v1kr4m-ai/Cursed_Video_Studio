import pytest

from cineflow.db import connect, migrate
from cineflow.dji_meta import ColorMode, color_mode, color_mode_from_fields, decode
from cineflow.media_ingest import ingest_folder
from cineflow.project_service import create_project, list_assets

from .conftest import SAMPLE_DIR

# Labelled by the user on 2026-11-16.
DLOG_M = ["DJI_20261026182115_0002_D.OSV", "DJI_20261026180320_0013_D.OSV", "DJI_20261020234747_0012_D.OSV"]
NORMAL = ["DJI_20260429132244_0001_D.OSV", "DJI_20260429215709_0002_D.OSV",
          "DJI_20260925050123_0003_D.OSV", "DJI_20260927122159_0011_D.OSV"]


def msg(field: int, payload: bytes) -> bytes:
    return bytes([field << 3 | 2, len(payload)]) + payload


def header(code: int | None) -> bytes:
    inner = b"" if code is None else bytes([1 << 3 | 0, code])  # 2.2.4.1 = code (varint)
    return msg(2, msg(2, msg(4, inner)))


def test_codes():
    assert color_mode_from_fields(decode(header(19))).mode is ColorMode.DLOG_M
    assert color_mode_from_fields(decode(header(None))).mode is ColorMode.NORMAL  # proto3 zero omitted
    r = color_mode_from_fields(decode(header(7)))
    assert r.mode is ColorMode.UNKNOWN and r.raw == 7
    assert color_mode_from_fields(decode(msg(1, b"x"))).mode is ColorMode.UNKNOWN  # field missing


def test_garbage_is_unknown(media):
    assert decode(b"\x00\x01\x02") is None
    assert color_mode(media["flat"]).mode is ColorMode.UNKNOWN  # no data track at all


@pytest.mark.sample
@pytest.mark.skipif(not SAMPLE_DIR.is_dir(), reason="sample footage not present")
@pytest.mark.parametrize("name,expected", [(n, ColorMode.DLOG_M) for n in DLOG_M] + [(n, ColorMode.NORMAL) for n in NORMAL])
def test_real_clips_match_user_labels(name, expected):
    r = color_mode(SAMPLE_DIR / name)
    assert r.mode is expected and r.source == "camera_metadata"


@pytest.mark.sample
@pytest.mark.skipif(not SAMPLE_DIR.is_dir(), reason="sample footage not present")
def test_ingest_records_mode_and_keeps_user_override(tmp_path):
    conn = connect(tmp_path / "c.db")
    migrate(conn)
    pid = create_project(conn, "p", tmp_path / "w")
    ingest_folder(conn, pid, SAMPLE_DIR)
    modes = {r["path"].rsplit("\\", 1)[-1]: r["color_mode"] for r in list_assets(conn, pid) if r["kind"] == "dual_fisheye"}
    assert {n for n, m in modes.items() if m == "dlog_m"} == set(DLOG_M)

    conn.execute("UPDATE assets SET color_mode='normal', color_mode_source='user', size_bytes=0 WHERE path LIKE ?",
                 (f"%{DLOG_M[0]}",))  # size_bytes=0 forces a re-ingest of that file
    ingest_folder(conn, pid, SAMPLE_DIR)
    row = conn.execute("SELECT color_mode, color_mode_source FROM assets WHERE path LIKE ?", (f"%{DLOG_M[0]}",)).fetchone()
    assert (row[0], row[1]) == ("normal", "user")

    # Assets recorded before detection existed get filled in on the next ingest.
    conn.execute("UPDATE assets SET color_mode=NULL, color_mode_source=NULL WHERE path LIKE ?", (f"%{DLOG_M[1]}",))
    ingest_folder(conn, pid, SAMPLE_DIR)
    row = conn.execute("SELECT color_mode, color_mode_source FROM assets WHERE path LIKE ?", (f"%{DLOG_M[1]}",)).fetchone()
    assert (row[0], row[1]) == ("dlog_m", "camera_metadata")
