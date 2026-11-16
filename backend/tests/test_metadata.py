import pytest

from cineflow.metadata_service import AssetKind, ProbeError, camera_model, parse_probe, probe

from .conftest import SAMPLE_DIR


def test_flat(media):
    info = probe(media["flat"])
    assert info.kind is AssetKind.FLAT
    assert (info.video[0].width, info.video[0].height) == (320, 180)
    assert info.video[0].fps == "25/1"
    assert info.has_audio
    assert not info.maybe_equirectangular


def test_dual_fisheye(media):
    info = probe(media["osv"])
    assert info.kind is AssetKind.DUAL_FISHEYE
    assert len(info.video) == 2
    assert info.video[0].bit_depth == 10
    assert info.video[0].fps == "30000/1001"
    assert abs(info.fps_float - 29.97) < 0.01
    assert not info.has_audio


def test_lrf_proxy(media):
    assert probe(media["lrf"]).kind is AssetKind.DUAL_FISHEYE_PROXY


def test_untagged_two_to_one_is_flat_but_flagged(media):
    info = probe(media["two_to_one"])
    assert info.kind is AssetKind.FLAT
    assert info.maybe_equirectangular


def test_spherical_tag_wins(tmp_path):
    data = {"format": {"duration": "1", "format_name": "mov"},
            "streams": [{"index": 0, "codec_type": "video", "codec_name": "hevc", "width": 7680,
                         "height": 3840, "avg_frame_rate": "30/1",
                         "side_data_list": [{"side_data_type": "Spherical Mapping",
                                             "projection": "equirectangular"}]}]}
    assert parse_probe(data, tmp_path / "x.mp4", 1).kind is AssetKind.EQUIRECTANGULAR


def test_cover_art_is_not_a_picture_stream(tmp_path):
    data = {"format": {"duration": "1", "format_name": "mov"},
            "streams": [{"index": 0, "codec_type": "video", "codec_name": "h264", "width": 1920,
                         "height": 1080, "avg_frame_rate": "25/1"},
                        {"index": 1, "codec_type": "video", "codec_name": "mjpeg", "width": 960,
                         "height": 540, "disposition": {"attached_pic": 1}}]}
    info = parse_probe(data, tmp_path / "x.mp4", 1)
    assert len(info.video) == 1 and info.kind is AssetKind.FLAT


@pytest.mark.parametrize("name", ["truncated", "not_video"])
def test_broken_files_raise(media, name):
    with pytest.raises(ProbeError):
        probe(media[name])


def test_missing_file_raises(tmp_path):
    with pytest.raises(ProbeError):
        probe(tmp_path / "nope.mp4")


@pytest.mark.sample
@pytest.mark.skipif(not SAMPLE_DIR.is_dir(), reason="sample footage not present")
def test_real_avata360_clips():
    osv = sorted(SAMPLE_DIR.glob("*.OSV"))
    assert osv, "no OSV files in sample dir"
    for f in osv:
        info = probe(f)
        assert info.kind is AssetKind.DUAL_FISHEYE, f
        assert info.video[0].codec == "hevc" and info.video[0].bit_depth == 10
        assert info.video[0].width in (3000, 3840)
        assert not info.has_audio
        assert "CAM meta" in info.data_handlers
    for f in sorted(SAMPLE_DIR.glob("*.LRF")):
        assert probe(f).kind is AssetKind.DUAL_FISHEYE_PROXY, f
    assert camera_model(osv[0]) == "DJI Avata360"
