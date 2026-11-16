"""Gyro-based stabilisation and horizon levelling for 360 footage.

The drone's attitude per frame (attitude.py) tells how the camera is rotated. For each frame
we compute the view we want in the world (heading, elevation, level horizon), express it in
the camera's own frame, and send those angles to FFmpeg's v360 filter with `sendcmd`
(`reset_rot=1` makes each command absolute; checked 2026-11-16, poc/out/acc_test.jpg).

The sign/axis mapping between DJI's quaternion and v360's angles was measured, not assumed:
poc/stab_search.py tries every candidate and keeps the one that leaves the least motion.
"""

from __future__ import annotations

import math

Quat = tuple[float, float, float, float]

# Filled from poc/stab_search.py results (see DECISIONS D-017).
SIGNS = (1, 1, 1)
YAW_OFFSET = 0.0


def _mat(q: Quat) -> list[list[float]]:
    w, x, y, z = q
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]]


def _zyx(yaw: float, pitch: float, roll: float) -> list[list[float]]:
    cy, sy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
    cp, sp = math.cos(math.radians(pitch)), math.sin(math.radians(pitch))
    cr, sr = math.cos(math.radians(roll)), math.sin(math.radians(roll))
    return [[cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
            [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
            [-sp, cp * sr, cp * cr]]


def _to_zyx(m: list[list[float]]) -> tuple[float, float, float]:
    pitch = math.asin(max(-1.0, min(1.0, -m[2][0])))
    yaw = math.atan2(m[1][0], m[0][0])
    roll = math.atan2(m[2][1], m[2][2])
    return math.degrees(yaw), math.degrees(pitch), math.degrees(roll)


def _mul(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _t(a):
    return [list(r) for r in zip(*a)]


def _unwrap(angles: list[float]) -> list[float]:
    out = [angles[0]]
    for a in angles[1:]:
        d = (a - out[-1] + 180) % 360 - 180
        out.append(out[-1] + d)
    return out


def _smooth(xs: list[float], window: int) -> list[float]:
    """Centred moving average; window in frames (odd)."""
    h = window // 2
    return [sum(xs[max(0, i - h):i + h + 1]) / len(xs[max(0, i - h):i + h + 1]) for i in range(len(xs))]


def heading(q: Quat) -> float:
    return _to_zyx(_mat(q))[0]


def view_angles(q: Quat, view_heading: float, view_pitch: float, view_roll: float = 0.0,
                signs=None, yaw_offset=None) -> tuple[float, float, float]:
    """v360 (yaw, pitch, roll) that shows the world view (heading, pitch, roll) from a camera at attitude q."""
    sy, sp, sr = signs or SIGNS
    y0 = YAW_OFFSET if yaw_offset is None else yaw_offset
    rel = _mul(_t(_mat(q)), _zyx(view_heading, view_pitch, view_roll))
    y, p, r = _to_zyx(rel)
    return ((sy * y + y0 + 180) % 360 - 180, 90 + sp * p, sr * r)


def view_commands(samples: list[tuple[float, Quat]], start: float, view_yaw: float, view_pitch: float,
                  signs=None, yaw_offset=None, follow_heading: bool = True,
                  heading_smooth_s: float = 2.0, fps: float = 29.97, target: str = "v360@s") -> str:
    """sendcmd script. With follow_heading the view turns with the drone's smoothed heading
    (plus view_yaw), so turns stay smooth but shake and banking are removed."""
    if not samples:
        return ""
    hs = _unwrap([heading(q) for _, q in samples])
    if follow_heading:
        win = max(1, int(heading_smooth_s * fps)) | 1
        target_h = [h + view_yaw for h in _smooth(hs, win)]
    else:
        target_h = [hs[0] + view_yaw] * len(hs)
    lines = []
    for (t, q), h in zip(samples, target_h):
        y, p, r = view_angles(q, h, view_pitch, 0.0, signs, yaw_offset)
        lines.append(f"{max(0.0, t - start):.4f} {target} yaw {y:.3f}, {target} pitch {p:.3f}, {target} roll {r:.3f};")
    return "\n".join(lines) + "\n"
