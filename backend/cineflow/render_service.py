"""Render an edit plan to a finished MP4 plus an export manifest.

Each shot is rendered to an intermediate with identical encoding settings, then the shots are
joined without re-encoding (concat demuxer). Music, if given, is trimmed, faded and
loudness-normalised in a final mux. All steps write temp files and rename on success.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Callable
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

from . import __version__
from .attitude import read_quaternions
from .color_service import filter_for, profile_for
from .edit_plan import EditPlan, check_against_assets
from .metadata_service import MediaInfo, probe
from .proxy_service import _ffmpeg_with_progress, video_encoder
from .reframe_service import FlatCropAdapter, adapter_for

PRESETS = {
    ("master_16x9", "2.7k"): (2688, 1512),
    ("master_16x9", "4k"): (3840, 2160),
    ("short_9x16", None): (1080, 1920),
    ("square_1x1", None): (1080, 1080),
}


def output_size(plan: EditPlan) -> tuple[int, int]:
    key = (plan.output.preset, plan.output.resolution if plan.output.preset == "master_16x9" else None)
    return PRESETS[key]


def _encoder(plan: EditPlan) -> list[str]:
    q = str(plan.output.quality)
    nv = video_encoder()[1] == "h264_nvenc"
    if plan.output.codec == "h265":
        return ["-c:v", "hevc_nvenc", "-preset", "p5", "-cq", q, "-tag:v", "hvc1"] if nv else \
               ["-c:v", "libx265", "-preset", "medium", "-crf", q, "-tag:v", "hvc1"]
    return ["-c:v", "h264_nvenc", "-preset", "p5", "-cq", q] if nv else \
           ["-c:v", "libx264", "-preset", "medium", "-crf", q]


def render(conn: sqlite3.Connection, plan: EditPlan, out: Path,
           on_progress: Callable[[float], None] | None = None) -> dict:
    rows = {r["id"]: dict(r) for r in conn.execute(
        f"SELECT * FROM assets WHERE id IN ({','.join('?' * len(plan.timeline))})",
        [s.asset_id for s in plan.timeline])}
    check_against_assets(plan, rows)
    w, h = output_size(plan)
    work = out.parent / f".{out.stem}_parts"
    work.mkdir(parents=True, exist_ok=True)
    total, done = plan.duration_s, 0.0
    parts, shots_meta, warnings = [], [], []

    for i, shot in enumerate(plan.timeline):
        a = rows[shot.asset_id]
        info = MediaInfo.model_validate_json(a["probe_json"])
        adapter = adapter_for(info)
        if isinstance(adapter, FlatCropAdapter) and (f := adapter.upscale_factor(info, w, h)) > 1.05:
            warnings.append(f"shot {i}: source is upscaled {f:.2f}x for this output size")
        profile = profile_for(a["color_mode"], a["kind"])
        attitude = None
        if plan.output.stabilize and a["kind"] == "dual_fisheye" and shot.effect in ("none", "pan"):
            attitude = read_quaternions(a["path"], shot.source_in, shot.source_out - shot.source_in) or None
            if attitude is None:
                warnings.append(f"shot {i}: no attitude data, using image-based stabilisation instead")
        r = adapter.build(info, shot, w, h, attitude)
        lut = filter_for(profile)
        pre = ",".join(x for x in (r.chain, lut) if x)
        stab = plan.output.stabilize and not r.moving   # vidstab only where the gyro path did not apply
        dur = shot.source_out - shot.source_in
        part = work / f"{i:04d}.mp4"
        sd = work / f"{i:04d}"
        sd.mkdir(exist_ok=True)
        if r.commands:
            (sd / "cmds.txt").write_text(r.commands, encoding="utf-8")
        src = ["-ss", f"{shot.source_in:.3f}", "-t", f"{dur:.3f}", "-i", a["path"]]
        share = 0.5 if stab else 1.0

        def prog(offset: float, frac: float, base=done, d=dur):
            if on_progress:
                on_progress(0.95 * (base + (offset + frac * share) * d) / total)

        if not part.exists():  # resume: finished parts are kept
            post = [f"fps={plan.output.fps}", "format=yuv420p"]
            if stab:
                # Pass 1 measures shake; pass 2 smooths it and crops/zooms just enough to hide edges.
                _ffmpeg_with_progress([*src, "-filter_complex", f"{pre},vidstabdetect=shakiness=6:accuracy=12:result=t.trf",
                                       "-an", "-f", "null", "-"], dur, lambda f: prog(0, f), cwd=sd)
                post = ["vidstabtransform=input=t.trf:smoothing=25:optzoom=1:interpol=bicubic",
                        "unsharp=5:5:0.4:3:3:0.2", *post]
            tmp = part.with_name(part.stem + ".tmp.mp4")
            _ffmpeg_with_progress([*src, "-filter_complex", ",".join([pre, *post]), "-an", *_encoder(plan),
                                   "-video_track_timescale", "90000", str(tmp)],
                                  dur, lambda f: prog(1 - share, f), cwd=sd)
            tmp.replace(part)
        parts.append(part)
        shots_meta.append({"index": i, "asset_id": a["id"], "source": a["path"], "in": shot.source_in,
                           "out": shot.source_out, "adapter": adapter.name, "color_profile": profile.id,
                           "color_mode_source": a["color_mode_source"], "view": shot.view.model_dump(),
                           "effect": shot.effect,
                           "stabilized": "gyro" if attitude else ("image" if stab else False)})
        done += dur

    concat = work / "list.txt"
    concat.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    tmp_out = out.with_name(out.stem + ".tmp" + out.suffix)
    music = plan.audio.music_path
    args = ["-f", "concat", "-safe", "0", "-i", str(concat)]
    if music:
        fade_start = max(0.0, total - plan.audio.fade_out_s)
        args += ["-i", music, "-filter_complex",
                 f"[1:a]atrim=0:{total:.3f},afade=t=out:st={fade_start:.3f}:d={plan.audio.fade_out_s},"
                 f"loudnorm=I={plan.audio.target_lufs}:TP=-1.5:LRA=11[a]",
                 "-map", "0:v", "-map", "[a]", "-c:a", "aac", "-b:a", "256k", "-ar", "48000"]
    _ffmpeg_with_progress([*args, "-c:v", "copy", "-movflags", "+faststart", "-t", f"{total:.3f}", str(tmp_out)],
                          total, (lambda f: on_progress(0.95 + 0.05 * f)) if on_progress else None)
    tmp_out.replace(out)

    result = probe(out)
    manifest = {
        "generator": f"cineflow {__version__}",
        "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "plan": json.loads(plan.model_dump_json()),
        "render": {"width": w, "height": h, "fps": plan.output.fps, "encoder": _encoder(plan)[1],
                   "duration_s": result.duration_s},
        "shots": shots_meta,
        "warnings": warnings,
        "models": [],   # filled once the Director exists (Phase 4)
        "output": str(out),
    }
    out.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    shutil.rmtree(work, ignore_errors=True)
    if on_progress:
        on_progress(1.0)
    return manifest


def expected_frames(plan: EditPlan) -> int:
    return round(plan.duration_s * float(Fraction(plan.output.fps)))
