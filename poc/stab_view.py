"""Visual check of stabilisation candidates: 3 frames per row, one row per candidate.
First row = no stabilisation (same view angles fixed). Usage: uv run python ../poc/stab_view.py START DUR sy,sp,sr,y0 ...
"""

import os
import subprocess
import sys
from pathlib import Path

from cineflow.attitude import read_quaternions
from cineflow.stabilize import view_commands
from cineflow.tools import find_tool

SRC = Path(os.environ["CINEFLOW_SAMPLE_DIR"]) / "DJI_20261026180320_0013_D"
OUT = Path(__file__).parent / "out" / "stab"
start, dur = float(sys.argv[1]), float(sys.argv[2])
cands = [tuple(float(x) for x in c.split(",")) for c in sys.argv[3:]]
qs = read_quaternions(SRC.with_suffix(".OSV"), start, dur)
rows = []
base = "dfisheye:flat:ih_fov=195:iv_fov=195:rorder=pyr:reset_rot=1:pitch=85:h_fov=90:v_fov=56:w=320:h=180"
sel = f"select='eq(n\\,0)+eq(n\\,{int(dur*12)})+eq(n\\,{int(dur*25)-2})',tile=3x1"
for i, c in enumerate([None] + cands):
    vf = f"v360={base},{sel}"
    if c:
        conj, sig, y0 = c[0], c[1:4], c[4]
        q2 = [(t, (q[0], -q[1], -q[2], -q[3]) if conj else q) for t, q in qs]
        (OUT / f"c{i}.txt").write_text(view_commands(q2, start, 0, -5, signs=sig, yaw_offset=y0, follow_heading=True))
        vf = f"sendcmd=f=c{i}.txt,v360@s={base},{sel}"
    subprocess.run([find_tool("ffmpeg"), "-v", "error", "-y", "-ss", str(start), "-t", str(dur), "-i", str(SRC.with_suffix(".LRF")),
                    "-vf", vf, "-frames:v", "1", "-fps_mode", "passthrough", f"r{i}.png"], cwd=OUT, check=True)
    rows.append(f"r{i}.png")
args = sum([["-i", r] for r in rows], [])
subprocess.run([find_tool("ffmpeg"), "-v", "error", "-y", *args, "-filter_complex", f"vstack=inputs={len(rows)}", "compare.jpg"], cwd=OUT, check=True)
print(OUT / "compare.jpg")
