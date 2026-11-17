"""Basic automatic edit: a stand-in until footage analysis and the AI Director exist.

It does not look at the pictures. It spreads shots evenly across the usable part of each clip
(skipping take-off and landing), points 360 views forward and slightly down, and adds effects
in fixed places. A reference style, when given, sets the length and the cut rhythm.
Everything it decides is written into the plan's `reason` fields so the result is explainable.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .edit_plan import Audio, EditPlan, Output, Shot, View
from .reference_service import StyleProfile

EDGE_SKIP_S = 5.0     # take-off / landing at clip start and end
MIN_USABLE_S = 4.0
PAN_PAIRS = [(-35, 35), (30, -30)]


class AutoPlanError(ValueError):
    pass


def build_plan(conn: sqlite3.Connection, project_id: str, preset: str = "short_9x16", resolution: str = "2.7k",
               target_s: float | None = None, shot_s: float | None = None, effects: bool = True,
               music_path: str | None = None, reference: StyleProfile | None = None,
               asset_ids: list[str] | None = None) -> EditPlan:
    if reference:
        target_s = target_s or min(max(reference.duration_s, 10), 180)
        shot_s = shot_s or min(max(reference.shot_len_median, 1.0), 8.0)
    target_s = target_s or (30 if preset == "short_9x16" else 60)
    shot_s = shot_s or 3.0

    rows = conn.execute("SELECT * FROM assets WHERE project_id = ? AND status = 'ok' AND proxy_of IS NULL "
                        "AND color_mode IS NOT NULL ORDER BY path", (project_id,)).fetchall()
    if asset_ids:
        rows = [r for r in rows if r["id"] in set(asset_ids)]
    offline = [r for r in rows if not Path(r["path"]).is_file()]
    rows = [r for r in rows if Path(r["path"]).is_file()]
    if offline and not rows:
        raise AutoPlanError(f"all {len(offline)} clips are offline (e.g. {offline[0]['path']}). "
                            "Reconnect the drive or card, or use Re-link in the Footage tab")
    clips = [(r, EDGE_SKIP_S, r["duration_s"] - EDGE_SKIP_S) for r in rows if r["duration_s"] - 2 * EDGE_SKIP_S >= MIN_USABLE_S]
    if not clips:
        raise AutoPlanError("no usable clips (need colour mode set and at least "
                            f"{MIN_USABLE_S + 2 * EDGE_SKIP_S:.0f} s of footage)")

    n = max(1, round(target_s / shot_s))
    total = sum(b - a for _, a, b in clips)
    # Shots per clip in proportion to usable length (largest remainder), at least one if it fits.
    raw = [(b - a) / total * n for _, a, b in clips]
    counts = [int(x) for x in raw]
    for i in sorted(range(len(raw)), key=lambda i: raw[i] - counts[i], reverse=True)[: n - sum(counts)]:
        counts[i] += 1

    shots: list[Shot] = []
    fov = 100 if preset == "master_16x9" else 95
    for (r, a, b), k in zip(clips, counts):
        for j in range(k):
            t = a + (b - a) * (j + 0.5) / k - shot_s / 2
            t = max(a, min(b - shot_s, t))
            shots.append(Shot(asset_id=r["id"], source_in=round(t, 3), source_out=round(t + shot_s, 3),
                              view=View(yaw=0, pitch=-8, fov=fov),
                              reason=f"evenly spaced shot {j + 1}/{k} from {r['path'].replace(chr(92), '/').rsplit('/', 1)[-1]}"))

    is360 = {r["id"]: r["kind"] == "dual_fisheye" for r, _, _ in clips}
    if effects:
        for i, s in enumerate(shots):
            if not is360[s.asset_id]:
                continue
            if i == 0:
                s.effect, s.reason = "planet_reveal", "opening: tiny planet unfolds into the first shot"
                s.source_out = round(s.source_in + max(shot_s, 3.5), 3)
            elif i == len(shots) // 2 and len(shots) >= 5:
                s.effect, s.spin, s.reason = "tiny_planet", 20, "mid-point accent: spinning tiny planet"
            elif i % 4 == 2:
                y0, y1 = PAN_PAIRS[(i // 4) % 2]
                s.view = View(yaw=y0, pitch=-8, fov=fov)
                s.effect, s.end_view, s.reason = "pan", View(yaw=y1, pitch=-8, fov=fov), "slow pan for movement"

    return EditPlan(project_id=project_id,
                    brief=f"basic auto edit{' following reference ' + reference.title if reference else ''}",
                    output=Output(preset=preset, resolution=resolution), audio=Audio(music_path=music_path),
                    timeline=shots)
