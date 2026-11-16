"""Calibrate the camera mount for gyro stabilisation, by measurement.

Unknowns: body->sphere yaw offset (0/90/180/270) and whether the DJI quaternion needs
conjugating. For each candidate, lock the view to the first frame's heading with a level
horizon, render a few seconds at low res from the LRF, and score residual motion (mean
frame-to-frame difference). The right candidate cancels the drone's rotation, so it scores lowest.
Usage: cd backend && CINEFLOW_SAMPLE_DIR=... STAB_START=278 STAB_DUR=4 uv run python ../poc/stab_search.py
"""

import itertools
import os
import re
import subprocess
from pathlib import Path

from cineflow.attitude import read_quaternions
from cineflow.stabilize import view_commands
from cineflow.tools import find_tool

SRC = Path(os.environ["CINEFLOW_SAMPLE_DIR"]) / "DJI_20261026180320_0013_D"
START, DUR = float(os.environ.get("STAB_START", 278)), float(os.environ.get("STAB_DUR", 4))
OUT = Path(__file__).parent / "out" / "stab"
OUT.mkdir(parents=True, exist_ok=True)
BASE = "dfisheye:flat:ih_fov=195:iv_fov=195:rorder=ypr:reset_rot=1:h_fov=90:v_fov=56:w=320:h=180"

qs = read_quaternions(SRC.with_suffix(".OSV"), START, DUR)
results = []
for conj, mount in itertools.product((False, True), (0, 90, 180, -90)):
    (OUT / "cmd.txt").write_text(view_commands(qs, START, 0, -5, follow_heading=False, mount_yaw=mount, conjugate=conj))
    vf = (f"sendcmd=f=cmd.txt,v360@s={BASE},format=gray,tblend=all_mode=difference,"
          "signalstats,metadata=print:key=lavfi.signalstats.YAVG:file=-")
    p = subprocess.run([find_tool("ffmpeg"), "-v", "error", "-ss", str(START), "-t", str(DUR), "-i", str(SRC.with_suffix(".LRF")),
                        "-vf", vf, "-f", "null", "-"], capture_output=True, text=True, cwd=OUT)
    vals = [float(v) for v in re.findall(r"YAVG=([\d.]+)", p.stdout)]
    results.append((round(sum(vals) / len(vals), 3) if vals else 999, conj, mount))
    print(results[-1], flush=True)
print("BEST", sorted(results)[:3])
