"""Per-frame aircraft attitude from DJI metadata, for 360 stabilisation and horizon levelling.

Field 3.4.14.4 of each `djmd` packet is a unit quaternion (w, x, y, z), one per video frame,
from the flight controller (found 2026-11-16; norm checked = 1.000). Field 3.3.2.1.3 holds
~134 gyro-rate samples per frame and is kept for later rolling-shutter work.
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path

from .dji_meta import decode
from .tools import find_tool, run

ATTITUDE_FIELD = "3.4.14.4"


def read_quaternions(path: str | Path, start: float, duration: float) -> list[tuple[float, tuple[float, float, float, float]]]:
    """[(pts_seconds, (w, x, y, z)), ...] for metadata packets in [start, start+duration]."""
    proc = run([find_tool("ffprobe"), "-v", "error", "-select_streams", "d:0",
                "-read_intervals", f"{max(0.0, start - 0.5)}%+{duration + 1.0}",
                "-show_entries", "packet=pts_time,pos,size", "-of", "json", str(path)], timeout=120)
    packets = json.loads(proc.stdout or b"{}").get("packets", [])
    out = []
    with open(path, "rb") as fh:
        for p in packets:
            t = float(p["pts_time"])
            if not (start - 0.1 <= t <= start + duration + 0.1):
                continue
            fh.seek(int(p["pos"]))
            f = decode(fh.read(int(p["size"])))
            comps = [f.get(f"{ATTITUDE_FIELD}.{i}", [None])[0] for i in (1, 2, 3, 4)] if f else []
            if len(comps) == 4 and all(isinstance(c, bytes) and len(c) == 4 for c in comps):
                q = tuple(struct.unpack("<f", c)[0] for c in comps)
                n = math.sqrt(sum(c * c for c in q))
                if 0.98 < n < 1.02:
                    out.append((t, tuple(c / n for c in q)))
    return out


def euler_zyx(q: tuple[float, float, float, float]) -> tuple[float, float, float]:
    """(yaw, pitch, roll) in degrees, aerospace Z-Y-X order, from (w, x, y, z)."""
    w, x, y, z = q
    yaw = math.atan2(2 * (w * z + x * y), 1 - 2 * (y * y + z * z))
    pitch = math.asin(max(-1.0, min(1.0, 2 * (w * y - z * x))))
    roll = math.atan2(2 * (w * x + y * z), 1 - 2 * (x * x + y * y))
    return math.degrees(yaw), math.degrees(pitch), math.degrees(roll)
