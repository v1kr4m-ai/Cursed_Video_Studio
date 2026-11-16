"""Visual check of gyro stabilisation: 4 frames per row; first row unstabilised, then one row per
candidate "conj,mount". Usage: uv run python ../poc/stab_view.py START DUR 0,0 0,90 ...
"""

import os
import subprocess
import sys
from pathlib import Path

from cineflow.attitude import read_quaternions
from cineflow.stabilize import view_commands
from cineflow.tools import find_tool

SRC = Path(os.environ["CINEFLOW_SAMPLE_DIR"]) / os.environ.get("STAB_CLIP", "DJI_20261026180320_0013_D")
OUT = Path(__file__).parent / "out" / "stab"
OUT.mkdir(parents=True, exist_ok=True)
start, dur = float(sys.argv[1]), float(sys.argv[2])
cands = [tuple(int(x) for x in c.split(",")) for c in sys.argv[3:]]
qs = read_quaternions(SRC.with_suffix(".OSV"), start, dur)
n = int(dur * 25)
sel = "select='" + "+".join(f"eq(n\\,{int(n * k / 4)})" for k in range(4)) + "',tile=4x1"
rows = []
for i, c in enumerate([None] + cands):
    if c is None:
        vf = f"v360=dfisheye:flat:ih_fov=195:iv_fov=195:rorder=pyr:pitch=85:h_fov=90:v_fov=56:w=320:h=180,{sel}"
    else:
        (OUT / f"c{i}.txt").write_text(view_commands(qs, start, 0, -5, follow_heading=True, conjugate=bool(c[0]), mount_yaw=c[1]))
        vf = f"sendcmd=f=c{i}.txt,v360@s=dfisheye:flat:ih_fov=195:iv_fov=195:rorder=ypr:reset_rot=1:h_fov=90:v_fov=56:w=320:h=180,{sel}"
    subprocess.run([find_tool("ffmpeg"), "-v", "error", "-y", "-ss", str(start), "-t", str(dur), "-i", str(SRC.with_suffix(".LRF")),
                    "-vf", vf, "-frames:v", "1", "-fps_mode", "passthrough", f"r{i}.png"], cwd=OUT, check=True)
    rows.append(f"r{i}.png")
args = sum([["-i", r] for r in rows], [])
subprocess.run([find_tool("ffmpeg"), "-v", "error", "-y", *args, "-filter_complex", f"vstack=inputs={len(rows)}", "compare.jpg"], cwd=OUT, check=True)
print(OUT / "compare.jpg")
