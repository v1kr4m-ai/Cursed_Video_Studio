import os
import subprocess
from pathlib import Path

import pytest

from cineflow.tools import find_tool

# Real Avata 360 footage for the `sample` tests; they are skipped when this is unset.
SAMPLE_DIR = Path(os.environ.get("CINEFLOW_SAMPLE_DIR") or "__no_sample_dir__")


def ffmpeg(*args: str) -> None:
    subprocess.run([find_tool("ffmpeg"), "-hide_banner", "-v", "error", "-y", *args], check=True)


@pytest.fixture(scope="session")
def media(tmp_path_factory) -> dict[str, Path]:
    """Small synthetic files that mimic each asset shape. Generated, never real footage."""
    d = tmp_path_factory.mktemp("media")
    src = ["-f", "lavfi", "-i"]
    out = {}

    out["flat"] = d / "flat.mp4"
    ffmpeg(*src, "testsrc2=s=320x180:r=25:d=1", *src, "sine=d=1",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out["flat"]))

    # Two square 10-bit HEVC streams in one MP4-family container, like a DJI OSV.
    out["osv"] = d / "fake.OSV"
    ffmpeg(*src, "testsrc2=s=256x256:r=30000/1001:d=1", *src, "testsrc=s=256x256:r=30000/1001:d=1",
           "-map", "0", "-map", "1", "-c:v", "libx265", "-x265-params", "log-level=none",
           "-pix_fmt", "yuv420p10le", "-f", "mp4", str(out["osv"]))

    out["lrf"] = d / "fake.LRF"
    ffmpeg(*src, "testsrc2=s=384x192:r=25:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           "-f", "mp4", str(out["lrf"]))

    out["two_to_one"] = d / "pano.mp4"
    ffmpeg(*src, "testsrc2=s=384x192:r=25:d=1", "-c:v", "libx264", "-pix_fmt", "yuv420p",
           str(out["two_to_one"]))

    out["truncated"] = d / "truncated.mp4"
    out["truncated"].write_bytes(out["flat"].read_bytes()[:2000])

    out["not_video"] = d / "notes.mp4"
    out["not_video"].write_text("not a video")
    return out
