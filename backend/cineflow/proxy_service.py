"""Thumbnails and lightweight preview proxies.

Dual-fisheye clips are converted to a 2:1 equirectangular preview, using the camera's own LRF
proxy as the source when one is linked (it is ~10x smaller than the OSV). Flat clips are
scaled down. Proxies are not colour-graded: colour mode is unknown until confirmed (R-02).

Outputs go to <work_dir>/proxies/<asset_id>.* via a temp name and rename, so a killed job
leaves either nothing or a finished file, and re-running skips finished files.
"""

from __future__ import annotations

import functools
import sqlite3
import subprocess
from collections.abc import Callable
from pathlib import Path

from .metadata_service import AssetKind, MediaInfo
from .tools import find_tool, run

# Lens field of view for Avata 360, picked by eye in Phase 0 (TECHNICAL_RISKS R-04).
AVATA360_LENS_FOV = 195
# pitch=90 puts the horizon across the middle of the equirectangular frame (Phase 0 fov_compare).
DFISHEYE_TO_EQUI = f"v360=dfisheye:e:ih_fov={AVATA360_LENS_FOV}:iv_fov={AVATA360_LENS_FOV}:pitch=90"
PROXY_FPS = 25


class ProxyError(RuntimeError):
    pass


@functools.cache
def video_encoder() -> list[str]:
    """NVENC when the encoder actually opens on this machine, else libx264."""
    probe = run([find_tool("ffmpeg"), "-v", "error", "-f", "lavfi", "-i", "color=s=256x256:d=0.1",
                 "-c:v", "h264_nvenc", "-f", "null", "-"], timeout=30)
    if probe.returncode == 0:
        return ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "28"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "26"]


def _inputs_and_filter(info: MediaInfo, source: str, width: int) -> tuple[list[str], str]:
    if info.kind is AssetKind.DUAL_FISHEYE:
        return ["-i", source], f"[0:v:0][0:v:1]hstack,{DFISHEYE_TO_EQUI}:w={width}:h={width // 2}"
    if info.kind is AssetKind.DUAL_FISHEYE_PROXY:  # LRF: circles already side by side
        return ["-i", source], f"[0:v:0]{DFISHEYE_TO_EQUI}:w={width}:h={width // 2}"
    return ["-i", source], f"[0:v:0]scale={width}:-2"


def _ffmpeg_with_progress(args: list[str], duration_s: float,
                          on_progress: Callable[[float], None] | None, cwd: Path | None = None) -> None:
    """Run ffmpeg, reporting progress from its own `-progress` output (out_time vs duration).

    `cwd` lets filter arguments name helper files (sendcmd scripts, vidstab transforms) by a
    plain relative name, avoiding Windows drive-letter escaping inside filter graphs.
    """
    cmd = [find_tool("ffmpeg"), "-hide_banner", "-v", "error", "-nostdin", "-y",
           "-progress", "pipe:1", *args]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=cwd)
    try:
        for line in proc.stdout:
            if line.startswith("out_time_us=") and on_progress and duration_s > 0:
                us = line.split("=", 1)[1].strip()
                if us.isdigit():
                    on_progress(min(1.0, int(us) / 1e6 / duration_s))
        err = proc.stderr.read()
        if proc.wait() != 0:
            raise ProxyError(err.strip()[-2000:] or "ffmpeg failed")
    except BaseException:
        proc.kill()  # cancelled or failed: don't leave ffmpeg running
        proc.wait()
        raise


def make_thumbnail(info: MediaInfo, source: str, out: Path) -> Path:
    if out.exists():
        return out
    inputs, vf = _inputs_and_filter(info, source, 640)
    tmp = out.with_name(out.stem + ".tmp" + out.suffix)
    seek = ["-ss", f"{info.duration_s / 2:.3f}"]  # middle avoids take-off / black first frames
    proc = run([find_tool("ffmpeg"), "-hide_banner", "-v", "error", "-y", *seek, *inputs,
                "-filter_complex", vf, "-frames:v", "1", "-q:v", "4", str(tmp)])
    if proc.returncode != 0 or not tmp.exists():
        raise ProxyError(proc.stderr.decode(errors="replace").strip()[-2000:])
    tmp.replace(out)
    return out


def make_proxy(info: MediaInfo, source: str, out: Path,
               on_progress: Callable[[float], None] | None = None) -> Path:
    if out.exists():
        return out
    width = 1920 if info.kind in (AssetKind.DUAL_FISHEYE, AssetKind.DUAL_FISHEYE_PROXY) else 960
    inputs, vf = _inputs_and_filter(info, source, width)
    tmp = out.with_name(out.stem + ".tmp" + out.suffix)
    _ffmpeg_with_progress([*inputs, "-filter_complex", f"{vf},fps={PROXY_FPS},format=yuv420p",
                           "-an", *video_encoder(), "-movflags", "+faststart", str(tmp)],
                          info.duration_s, on_progress)
    tmp.replace(out)
    return out


def build_project_proxies(conn: sqlite3.Connection, project_id: str,
                          on_progress: Callable[[float], None] | None = None) -> dict:
    """Thumbnail + proxy for every usable main asset. Progress is weighted by clip duration."""
    work = Path(conn.execute("SELECT work_dir FROM projects WHERE id = ?", (project_id,)).fetchone()[0])
    out_dir = work / "proxies"
    out_dir.mkdir(parents=True, exist_ok=True)
    assets = conn.execute("SELECT * FROM assets WHERE project_id = ? AND status = 'ok' AND proxy_of IS NULL "
                          "ORDER BY path", (project_id,)).fetchall()
    lrf = {r["proxy_of"]: r for r in conn.execute(
        "SELECT * FROM assets WHERE project_id = ? AND proxy_of IS NOT NULL AND status = 'ok'", (project_id,))}
    total = sum(a["duration_s"] for a in assets) or 1.0
    done_s, outputs = 0.0, {}
    for a in assets:
        src = lrf.get(a["id"], a)  # prefer the camera's own low-res proxy
        info = MediaInfo.model_validate_json(src["probe_json"])
        thumb = make_thumbnail(info, src["path"], out_dir / f"{a['id']}.jpg")
        proxy = make_proxy(info, src["path"], out_dir / f"{a['id']}.mp4",
                           (lambda f, base=done_s, d=a["duration_s"]: on_progress((base + f * d) / total))
                           if on_progress else None)
        outputs[a["id"]] = {"thumbnail": str(thumb), "proxy": str(proxy), "source": src["path"]}
        done_s += a["duration_s"]
        if on_progress:
            on_progress(done_s / total)
    return outputs
