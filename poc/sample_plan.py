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

SHOTS = [  # asset, in, out, yaw, pitch, reason, extra Shot fields
    (C13, 238, 242, -70, 0, "opening: tiny planet unfolds over the ridge", {"effect": "planet_reveal"}),
    (C13, 80, 83, -60, -5, "ridge toward the sunset", {}),
    (C02, 30, 33, 0, -10, "over the summit tower", {}),
    (C02, 90, 94, 40, -5, "pan from the summit to the sea and islands", {"effect": "pan", "end_view": {"yaw": 100, "pitch": -5}}),
    (C13, 360, 363, -40, -5, "valley reveal", {}),
    (C13, 300, 304, 0, 0, "tiny planet over the forest", {"effect": "tiny_planet", "spin": 25}),
    (C02, 240, 243, 0, -15, "return to the landing pad", {}),
]

conn = connect(DB)
pid = conn.execute("SELECT project_id FROM assets WHERE id = ?", (C13,)).fetchone()[0]
OUT.mkdir(parents=True, exist_ok=True)
for preset in sys.argv[1:] or ["master_16x9", "short_9x16"]:
    fov = 100 if preset == "master_16x9" else 95
    plan = EditPlan(project_id=pid, brief="Dusk ridge flight sample", output={"preset": preset},
                    timeline=[Shot(asset_id=a, source_in=i, source_out=o, view=View(yaw=y, pitch=p, fov=fov), reason=r,
                                   **{**x, **({"end_view": {**x["end_view"], "fov": fov}} if "end_view" in x else {})})
                              for a, i, o, y, p, r, x in SHOTS])
    t = time.time()
    m = render(conn, plan, OUT / f"sample_{preset}.mp4")
    print(preset, m["render"], f"{time.time() - t:.0f}s", m["warnings"])
