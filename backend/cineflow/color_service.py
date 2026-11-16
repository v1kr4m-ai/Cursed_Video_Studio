"""Technical colour transforms (log -> Rec.709), kept separate from creative grading.

Each profile is versioned and records where its transform came from. The DJI LUT is used from
the user's DJI Studio install or a folder they point to; it is never bundled (R-03).
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel


class ColorProfile(BaseModel):
    id: str
    input_mode: str                 # matches assets.color_mode
    lut_file: str | None            # file name searched for; None = no transform
    source: str


PROFILES = {
    "dlog_m": ColorProfile(
        id="avata360_dlogm_rec709_v1", input_mode="dlog_m",
        lut_file="DJI Avata 360 D-Log M to Rec.709 V1.cube",
        source="DJI, shipped with DJI Studio 1.0.0.30440 (LOG_Avata360_DLogM)"),
    "normal": ColorProfile(id="rec709_passthrough_v1", input_mode="normal", lut_file=None,
                           source="camera already outputs Rec.709"),
}


class ColorError(RuntimeError):
    pass


def _lut_dirs() -> list[Path]:
    dirs = []
    if os.environ.get("CINEFLOW_LUT_DIR"):
        dirs.append(Path(os.environ["CINEFLOW_LUT_DIR"]))
    studio = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "DJI Studio"
    if studio.is_dir():
        dirs += sorted(studio.glob("*/filter/LUT/*"), reverse=True)  # newest version folder first
    return dirs


def find_lut(name: str) -> Path:
    for d in _lut_dirs():
        p = d / name
        if p.is_file():
            return p
    raise ColorError(f"LUT '{name}' not found. Install DJI Studio or set CINEFLOW_LUT_DIR "
                     "to a folder containing the file from DJI's download page.")


def profile_for(color_mode: str | None, kind: str) -> ColorProfile:
    """Which technical transform an asset needs. Unknown colour mode is an error, not a guess."""
    if color_mode not in PROFILES:
        raise ColorError(f"colour mode unknown ({color_mode!r}); set it on the asset before rendering")
    if color_mode == "dlog_m" and kind not in ("dual_fisheye", "dual_fisheye_proxy"):
        # The LUT on disk is for the Avata 360 sensor; other DJI cameras need their own.
        raise ColorError("D-Log M on a non-Avata-360 clip: no validated LUT for that camera yet")
    return PROFILES[color_mode]


def _ff_path(p: Path) -> str:
    """Escape a Windows path for use inside an FFmpeg filter argument."""
    return str(p).replace("\\", "/").replace(":", "\\:").replace("'", "\\'")


def filter_for(profile: ColorProfile) -> str | None:
    if profile.lut_file is None:
        return None
    return f"lut3d=file='{_ff_path(find_lut(profile.lut_file))}':interp=tetrahedral"
