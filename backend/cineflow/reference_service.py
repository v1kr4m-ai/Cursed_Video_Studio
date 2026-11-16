"""Reference videos: measure the style of a video the user likes, so edits can follow it.

Measured, not guessed: length, aspect, frame rate, cut rhythm (FFmpeg scene detection),
brightness / saturation / contrast (signalstats), loudness (EBU R128). References are
analysed locally and never copied into the user's output.

Links: YouTube and Instagram pages are fetched with yt-dlp, only when the user adds them.
The user is responsible for having the right to download a given video; Instagram may refuse
without a login, which is reported as an error, not worked around.
"""

from __future__ import annotations

import json
import re
import statistics as st
import uuid
from pathlib import Path
from urllib.parse import urlparse

from pydantic import BaseModel

from .metadata_service import probe
from .tools import find_tool, run

ALLOWED_HOSTS = ("youtube.com", "youtu.be", "instagram.com")
SCENE_THRESHOLD = 10.0   # scdet score (0-100); hard cuts in edited videos score well above this


class StyleProfile(BaseModel):
    id: str
    source: str
    title: str
    duration_s: float
    width: int
    height: int
    vertical: bool
    fps: str
    cuts: list[float]                 # seconds
    shot_len_median: float
    shot_len_p25: float
    shot_len_p75: float
    cuts_per_min: float
    brightness: float                 # mean luma 0-1
    saturation: float                 # mean saturation 0-1 (relative)
    contrast: float                   # mean (p90 - p10) luma 0-1
    loudness_lufs: float | None
    has_audio: bool


class ReferenceError(RuntimeError):
    pass


def validate_url(url: str) -> str:
    u = urlparse(url.strip())
    host = (u.hostname or "").lower()
    if u.scheme not in ("http", "https") or not any(host == h or host.endswith("." + h) for h in ALLOWED_HOSTS):
        raise ReferenceError("only YouTube and Instagram links are supported")
    return u.geturl()


def download(url: str, out_dir: Path) -> Path:
    """Fetch one video with yt-dlp into out_dir (max 1080p, mp4). Returns the file path."""
    url = validate_url(url)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmpl = str(out_dir / "%(id)s.%(ext)s")
    proc = run([find_tool("yt-dlp"), "--no-playlist", "--no-progress", "--restrict-filenames",
                "-f", "bv*[height<=1080]+ba/b[height<=1080]/b", "--merge-output-format", "mp4",
                "--max-filesize", "500M", "-o", tmpl, "--print", "after_move:filepath", url], timeout=900)
    if proc.returncode != 0:
        msg = proc.stderr.decode(errors="replace").strip().splitlines()
        raise ReferenceError(msg[-1] if msg else "download failed")
    path = Path(proc.stdout.decode(errors="replace").strip().splitlines()[-1])
    if not path.is_file():
        raise ReferenceError("download finished but the file was not found")
    return path


def _q(xs: list[float], p: float) -> float:
    xs = sorted(xs)
    return xs[min(len(xs) - 1, max(0, round(p * (len(xs) - 1))))] if xs else 0.0


def analyse(path: Path, source: str) -> StyleProfile:
    info = probe(path)
    v = info.video[0]
    ff = find_tool("ffmpeg")
    # One decode at low resolution for both cut detection and picture statistics.
    p = run([ff, "-hide_banner", "-nostats", "-i", str(path), "-an", "-vf",
             f"scale=320:-2,scdet=threshold={SCENE_THRESHOLD},signalstats,metadata=print:file=-",
             "-f", "null", "-"], timeout=1800)
    text = p.stdout.decode(errors="replace") + p.stderr.decode(errors="replace")
    cuts = sorted({round(float(t), 3) for t in re.findall(r"lavfi\.scd\.time[=:]\s*([\d.]+)", text)})
    yavg = [float(x) for x in re.findall(r"signalstats\.YAVG=([\d.]+)", text)]
    ylow = [float(x) for x in re.findall(r"signalstats\.YLOW=([\d.]+)", text)]
    yhigh = [float(x) for x in re.findall(r"signalstats\.YHIGH=([\d.]+)", text)]
    sat = [float(x) for x in re.findall(r"signalstats\.SATAVG=([\d.]+)", text)]
    maxv = 1023 if (v.bit_depth or 8) > 8 else 255
    bounds = [0.0, *cuts, info.duration_s]
    shots = [b - a for a, b in zip(bounds, bounds[1:]) if b - a > 0.05]

    lufs = None
    if info.has_audio:
        a = run([ff, "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", "ebur128", "-f", "null", "-"], timeout=900)
        m = re.findall(r"I:\s*(-?[\d.]+) LUFS", a.stderr.decode(errors="replace"))
        lufs = float(m[-1]) if m else None

    return StyleProfile(
        id=uuid.uuid4().hex[:12], source=source, title=path.stem, duration_s=info.duration_s,
        width=v.width, height=v.height, vertical=v.height > v.width, fps=v.fps, cuts=cuts,
        shot_len_median=round(st.median(shots), 2) if shots else info.duration_s,
        shot_len_p25=round(_q(shots, 0.25), 2), shot_len_p75=round(_q(shots, 0.75), 2),
        cuts_per_min=round(len(cuts) / info.duration_s * 60, 1) if info.duration_s else 0.0,
        brightness=round(st.fmean(yavg) / maxv, 3) if yavg else 0.0,
        saturation=round(st.fmean(sat) / (maxv / 2), 3) if sat else 0.0,
        contrast=round(st.fmean(h - l for h, l in zip(yhigh, ylow)) / maxv, 3) if yhigh else 0.0,
        loudness_lufs=lufs, has_audio=info.has_audio)


def ref_dir(work_dir: str | Path) -> Path:
    return Path(work_dir) / "references"


def add_reference(work_dir: str | Path, source: str) -> StyleProfile:
    """`source` is a local video file, a folder of videos (each analysed), or a YouTube/Instagram URL."""
    d = ref_dir(work_dir)
    d.mkdir(parents=True, exist_ok=True)
    if source.lower().startswith(("http://", "https://")):
        path = download(source, d / "downloads")
    else:
        path = Path(source)
        if not path.is_file():
            raise ReferenceError(f"not a video file: {source}")
    prof = analyse(path, source)
    (d / f"{prof.id}.json").write_text(prof.model_dump_json(indent=2), encoding="utf-8")
    return prof


def list_references(work_dir: str | Path) -> list[StyleProfile]:
    d = ref_dir(work_dir)
    return [StyleProfile.model_validate_json(f.read_text(encoding="utf-8")) for f in sorted(d.glob("*.json"))] if d.is_dir() else []


def get_reference(work_dir: str | Path, ref_id: str) -> StyleProfile:
    if not re.fullmatch(r"[0-9a-f]{12}", ref_id):
        raise ReferenceError("bad reference id")
    f = ref_dir(work_dir) / f"{ref_id}.json"
    if not f.is_file():
        raise ReferenceError("no such reference")
    return StyleProfile.model_validate_json(f.read_text(encoding="utf-8"))
