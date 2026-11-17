"""Time one gyro-stabilised 3 s shot with different v360 interpolation modes (decode + reframe only).
Usage: cd backend && CINEFLOW_SAMPLE_DIR=... uv run python ../poc/speed_test.py
"""

import os
import subprocess
import time
from pathlib import Path

from cineflow.attitude import read_quaternions
from cineflow.edit_plan import Shot, View
from cineflow.reframe_service import FfmpegV360Adapter
from cineflow.tools import find_tool

SRC = Path(os.environ["CINEFLOW_SAMPLE_DIR"]) / "DJI_20261026180320_0013_D.OSV"
OUT = Path(__file__).parent / "out" / "speed"
OUT.mkdir(parents=True, exist_ok=True)
shot = Shot(asset_id="x", source_in=80, source_out=83, view=View(yaw=0, pitch=-5, fov=95))
att = read_quaternions(SRC, 80, 3)
for w, h in ((1080, 1920), (2688, 1512)):
    r = FfmpegV360Adapter().build(None, shot, w, h, att)
    (OUT / "cmds.txt").write_text(r.commands)
    for interp in ("lanczos", "cubic", "linear"):
        for moving in (True, False):
            chain = r.chain.replace("interp=lanczos", f"interp={interp}")
            if not moving:
                chain = chain.replace("sendcmd=f=cmds.txt,", "")
            t = time.time()
            subprocess.run([find_tool("ffmpeg"), "-v", "error", "-ss", "80", "-t", "3", "-i", str(SRC),
                            "-filter_complex", chain, "-f", "null", "-"], cwd=OUT, check=True)
            print(f"{w}x{h} {interp:8} {'per-frame' if moving else 'fixed    '} {time.time() - t:6.1f} s for 3 s", flush=True)
