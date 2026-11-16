"""Render a hand-written plan from the real sample project: one 16:9 2.7K master and one 9:16 Short.

Shots chosen by eye from preview contact sheets; yaw read from horizontal position in the
equirectangular preview (centre = 0°). No music: none licensed is available yet.
Usage: cd backend && uv run python ../poc/sample_plan.py
"""

import sys
import time
from pathlib import Path

from cineflow.db import connect
from cineflow.edit_plan import EditPlan, Shot, View
from cineflow.render_service import render

DB = Path(__file__).parent / "out" / "real_project" / "cineflow.db"
OUT = Path(__file__).parent / "out" / "renders"
C13, C02 = "e5887df03afb44e1bda0e9c8933d4b52", "c4013143783646baa0252a339f1d542b"

SHOTS = [  # asset, in, out, yaw, pitch, reason
    (C13, 1, 4, 0, -5, "take-off from the rocks"),
    (C13, 80, 83, -60, -5, "ridge toward the sunset"),
    (C13, 240, 243, -70, 0, "level pass, glow on the horizon"),
    (C02, 30, 33, 0, -10, "over the summit tower"),
    (C02, 90, 93, 80, -5, "sea and islands"),
    (C13, 360, 363, -40, -5, "valley reveal"),
    (C02, 240, 243, 0, -15, "return to the landing pad"),
]

conn = connect(DB)
pid = conn.execute("SELECT id FROM projects").fetchone()[0]
OUT.mkdir(parents=True, exist_ok=True)
for preset in sys.argv[1:] or ["master_16x9", "short_9x16"]:
    fov = 100 if preset == "master_16x9" else 95
    plan = EditPlan(project_id=pid, brief="Dusk ridge flight sample", output={"preset": preset},
                    timeline=[Shot(asset_id=a, source_in=i, source_out=o, view=View(yaw=y, pitch=p, fov=fov), reason=r)
                              for a, i, o, y, p, r in SHOTS])
    t = time.time()
    m = render(conn, plan, OUT / f"sample_{preset}.mp4")
    print(preset, m["render"], f"{time.time() - t:.0f}s", m["warnings"])
