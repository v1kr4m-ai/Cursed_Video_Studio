"""FFprobe wrapper and asset classification.

`probe(path)` returns a typed `MediaInfo`. `parse_probe(json, path)` does the pure part so it
can be tested without media files.

Classification is by observed structure, not by trusting tags: DJI writes bt709 colour tags on
every Avata 360 clip regardless of colour mode (TECHNICAL_RISKS R-02), so colour mode is not
decided here.
"""

from __future__ import annotations

import json
import re
from enum import StrEnum
from fractions import Fraction
from pathlib import Path

from pydantic import BaseModel

from .tools import find_tool, run

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".osv", ".insv", ".lrf", ".avi", ".mts", ".m2ts"}


class AssetKind(StrEnum):
    DUAL_FISHEYE = "dual_fisheye"            # DJI OSV: one square fisheye stream per lens
    DUAL_FISHEYE_PROXY = "dual_fisheye_proxy"  # DJI LRF: both circles side by side, low-res
    EQUIRECTANGULAR = "equirectangular"      # tagged spherical, or exported 360 MP4
    FLAT = "flat"                            # ordinary video


class ProbeError(RuntimeError):
    """File unreadable, truncated or not a video. The message is ffprobe's own."""


class VideoStream(BaseModel):
    index: int
    codec: str
    profile: str | None = None
    width: int
    height: int
    pix_fmt: str | None = None
    bit_depth: int | None = None
    fps: str                       # exact rational, e.g. "30000/1001"
    bit_rate: int | None = None
    frames: int | None = None
    color_range: str | None = None
    color_space: str | None = None
    color_transfer: str | None = None
    color_primaries: str | None = None
    projection: str | None = None  # from spherical side data, when present


class MediaInfo(BaseModel):
    path: str
    size_bytes: int
    container: str
    duration_s: float
    kind: AssetKind
    video: list[VideoStream]       # main picture streams only (thumbnails/cover art excluded)
    has_audio: bool
    data_handlers: list[str]       # e.g. ["CAM meta", "CAM dbgi"]
    creation_time: str | None = None
    maybe_equirectangular: bool = False  # 2:1 frame without a spherical tag; needs a look

    @property
    def fps_float(self) -> float:
        return float(Fraction(self.video[0].fps))


def _bit_depth(pix_fmt: str | None) -> int | None:
    if not pix_fmt:
        return None
    m = re.search(r"p(\d{2})(le|be)?$", pix_fmt)
    return int(m.group(1)) if m else 8


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _projection(stream: dict) -> str | None:
    for sd in stream.get("side_data_list", []) or []:
        if sd.get("side_data_type") == "Spherical Mapping":
            return str(sd.get("projection", "")).lower() or None
    return None


def parse_probe(data: dict, path: Path, size_bytes: int | None = None) -> MediaInfo:
    streams = data.get("streams", [])
    fmt = data.get("format", {})

    video: list[VideoStream] = []
    for s in streams:
        if s.get("codec_type") != "video":
            continue
        # Cover art / embedded thumbnails (OSV carries a 960x540 MJPEG) are not picture streams.
        if s.get("disposition", {}).get("attached_pic") or s.get("codec_name") in {"mjpeg", "png"}:
            continue
        video.append(VideoStream(
            index=s["index"],
            codec=s.get("codec_name", "unknown"),
            profile=s.get("profile"),
            width=int(s["width"]),
            height=int(s["height"]),
            pix_fmt=s.get("pix_fmt"),
            bit_depth=_bit_depth(s.get("pix_fmt")),
            fps=s.get("avg_frame_rate") if s.get("avg_frame_rate", "0/0") != "0/0" else s.get("r_frame_rate", "0/1"),
            bit_rate=_int(s.get("bit_rate")),
            frames=_int(s.get("nb_frames")),
            color_range=s.get("color_range"),
            color_space=s.get("color_space"),
            color_transfer=s.get("color_transfer"),
            color_primaries=s.get("color_primaries"),
            projection=_projection(s),
        ))
    if not video:
        raise ProbeError(f"no video stream in {path}")

    handlers = [s.get("tags", {}).get("handler_name", "") for s in streams if s.get("codec_type") == "data"]
    ext = path.suffix.lower()
    v0 = video[0]

    maybe_equi = False
    if len(video) >= 2 and all(v.width == v.height == v0.width for v in video[:2]):
        kind = AssetKind.DUAL_FISHEYE
        video = video[:2]
    elif ext == ".lrf" and v0.width == 2 * v0.height:
        kind = AssetKind.DUAL_FISHEYE_PROXY
    elif v0.projection == "equirectangular":
        kind = AssetKind.EQUIRECTANGULAR
    else:
        kind = AssetKind.FLAT
        maybe_equi = v0.width == 2 * v0.height

    return MediaInfo(
        path=str(path),
        size_bytes=size_bytes if size_bytes is not None else _int(fmt.get("size")) or 0,
        container=fmt.get("format_name", "unknown"),
        duration_s=float(fmt.get("duration") or 0.0),
        kind=kind,
        video=video,
        has_audio=any(s.get("codec_type") == "audio" for s in streams),
        data_handlers=[h for h in handlers if h],
        creation_time=fmt.get("tags", {}).get("creation_time"),
        maybe_equirectangular=maybe_equi,
    )


def probe(path: str | Path) -> MediaInfo:
    path = Path(path)
    if not path.is_file():
        raise ProbeError(f"not a file: {path}")
    proc = run([find_tool("ffprobe"), "-v", "error", "-show_format", "-show_streams",
                "-of", "json", str(path)])
    if proc.returncode != 0:
        raise ProbeError(proc.stderr.decode(errors="replace").strip() or f"ffprobe failed on {path}")
    data = json.loads(proc.stdout or b"{}")
    info = parse_probe(data, path, path.stat().st_size)
    if info.duration_s <= 0:
        raise ProbeError(f"zero duration (truncated or incomplete recording?): {path}")
    return info


def camera_model(path: str | Path) -> str | None:
    """Best-effort camera name from the first DJI metadata packet, e.g. 'DJI Avata360'.

    The packet is protobuf with an unpublished schema; this only scans for a readable
    'DJI ...' string and returns None when there is none. Not used for decisions.
    """
    proc = run([find_tool("ffmpeg"), "-v", "error", "-i", str(path), "-map", "0:d:0?",
                "-c", "copy", "-frames:d", "1", "-f", "data", "-"], timeout=30)
    if proc.returncode != 0 or not proc.stdout:
        return None
    for s in re.findall(rb"[\x20-\x7e]{6,}", proc.stdout[:4096]):
        if s.startswith(b"DJI ") and not s.startswith(b"DJI FC"):
            return s.decode()
    return None
