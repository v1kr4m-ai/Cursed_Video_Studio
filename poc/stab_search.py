"""Find how DJI attitude maps onto v360 angles, by measurement.

For each candidate (sign of yaw/pitch/roll, constant yaw offset between lens and body), lock the
view to the first frame's heading and level horizon, render 3 s at low res from the LRF, and
score residual motion as the mean frame-to-frame difference. The right mapping removes the
drone's rotation, leaving only slow translation, so it scores lowest.
Usage: cd backend && uv run python ../poc/stab_search.py
"""

import itertools
import os
import re
import subprocess
import sys
from pathlib import Path

from cineflow.attitude import read_quaternions
from cineflow.stabilize import view_commands
from cineflow.tools import find_tool

SRC = Path(os.environ["CINEFLOW_SAMPLE_DIR"]) / "DJI_20261026180320_0013_D"
START, DUR = float(os.environ.get("STAB_START", 80)), float(os.environ.get("STAB_DUR", 3))
OUT = Path(__file__).parent / "out" / "stab"
OUT.mkdir(parents=True, exist_ok=True)

raw = read_quaternions(SRC.with_suffix(".OSV"), START, DUR)


def variant(q, order, conj):
    w, x, y, z = q if order == "wxyz" else (q[3], q[0], q[1], q[2])
    return (w, -x, -y, -z) if conj else (w, x, y, z)


results = []
for order, conj, sy, sp, sr, y0 in itertools.product(("wxyz", "xyzw"), (False, True), (1, -1), (1, -1), (1, -1), (0, 90, 180, -90)):
    qs = [(t, variant(q, order, conj)) for t, q in raw]
    cmds = view_commands(qs, START, view_yaw=0, view_pitch=-5, signs=(sy, sp, sr), yaw_offset=y0, follow_heading=False)
    cf = OUT / "cmd.txt"
    cf.write_text(cmds)
    vf = (f"sendcmd=f=cmd.txt,v360@s=dfisheye:flat:ih_fov=195:iv_fov=195:rorder=pyr:reset_rot=1"
          f":pitch=90:h_fov=90:v_fov=56:w=320:h=180,format=gray,tblend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-")
    p = subprocess.run([find_tool("ffmpeg"), "-v", "error", "-ss", str(START), "-t", str(DUR), "-i", str(SRC.with_suffix(".LRF")),
                        "-vf", vf, "-f", "null", "-"], capture_output=True, text=True, cwd=OUT)
    vals = [float(v) for v in re.findall(r"YAVG=([\d.]+)", p.stdout)]
    score = sum(vals) / len(vals) if vals else 999
    results.append((round(score, 3), order, conj, sy, sp, sr, y0))

results.sort()
for r in results[:8]:
    print("BEST", r)
print("WORST", results[-1])
sys.exit(0)
