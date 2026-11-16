"""Gyro-based stabilisation and horizon levelling for 360 footage.

Exact maths, from FFmpeg's vf_v360.c (LGPL, read 2026-11-16):
  - output flat pixel direction d_out = (x right, y down, z forward)
  - input sphere direction d_S = Q · d_out, with Q the rotation of quaternion
    q = m[o0] * m[o1] * m[o2]; yaw = rotation about y, pitch about x, roll about z
  - dual fisheye input: +z is the axis of the second lens stream (Avata 360: looks down)
For each frame we want a virtual camera fixed in the world (heading, pitch, level roll):
  Q = M · R_bw^T · R_vw
  R_bw  body->world rotation from the drone attitude quaternion (attitude.py)
  R_vw  virtual camera axes (right, down, forward) in world NED
  M     body->sphere mount rotation (fixed; calibrated by poc/stab_search.py, D-017)
Q is then split into v360 angles for rorder "ypr" (Q = Ry(yaw)·Rx(pitch)·Rz(roll)) and sent per
frame with sendcmd + reset_rot=1 (absolute angles).
"""

from __future__ import annotations

import math

Quat = tuple[float, float, float, float]
Mat = list[list[float]]

# Calibration (D-017): body->sphere yaw offset in degrees, and whether the DJI quaternion is
# world->body (needs conjugating) rather than body->world.
MOUNT_YAW = 90.0   # chosen by eye on two flights: level sea horizon (poc/out/stab/check_both.jpg)
CONJUGATE = False  # DJI field 3.4.14.4 is body->world as stored
HEADING_SMOOTH_S = 2.5


def q_to_mat(q: Quat) -> Mat:
    w, x, y, z = q
    return [[1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)]]


def mul(a: Mat, b: Mat) -> Mat:
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def tr(a: Mat) -> Mat:
    return [list(r) for r in zip(*a)]


def rx(d: float) -> Mat:
    c, s = math.cos(math.radians(d)), math.sin(math.radians(d))
    return [[1, 0, 0], [0, c, -s], [0, s, c]]


def ry(d: float) -> Mat:
    c, s = math.cos(math.radians(d)), math.sin(math.radians(d))
    return [[c, 0, s], [0, 1, 0], [-s, 0, c]]


def rz(d: float) -> Mat:
    c, s = math.cos(math.radians(d)), math.sin(math.radians(d))
    return [[c, -s, 0], [s, c, 0], [0, 0, 1]]


def camera_in_world(heading: float, pitch: float) -> Mat:
    """Columns = virtual camera axes (right, down, forward) in NED; level horizon."""
    h, p = math.radians(heading), math.radians(pitch)
    f = [math.cos(p) * math.cos(h), math.cos(p) * math.sin(h), -math.sin(p)]
    r = [-math.sin(h), math.cos(h), 0.0]
    d = [f[1] * r[2] - f[2] * r[1], f[2] * r[0] - f[0] * r[2], f[0] * r[1] - f[1] * r[0]]  # f x r
    return [[r[i], d[i], f[i]] for i in range(3)]


def split_ypr(Q: Mat) -> tuple[float, float, float]:
    """Q = Ry(a)·Rx(b)·Rz(c) -> (a, b, c) in degrees."""
    b = math.asin(max(-1.0, min(1.0, -Q[1][2])))
    if abs(Q[1][2]) < 0.999999:
        a = math.atan2(Q[0][2], Q[2][2])
        c = math.atan2(Q[1][0], Q[1][1])
    else:  # gimbal lock: put everything in yaw
        a, c = math.atan2(-Q[2][0], Q[0][0]), 0.0
    return math.degrees(a), math.degrees(b), math.degrees(c)


def body_to_world(q: Quat, conjugate: bool | None = None) -> Mat:
    conj = CONJUGATE if conjugate is None else conjugate
    return q_to_mat((q[0], -q[1], -q[2], -q[3]) if conj else q)


def heading_of(R_bw: Mat) -> float:
    """Direction of the body's forward axis in the world, degrees from north."""
    return math.degrees(math.atan2(R_bw[1][0], R_bw[0][0]))


def v360_angles(q: Quat, heading: float, pitch: float, mount_yaw: float | None = None,
                conjugate: bool | None = None) -> tuple[float, float, float]:
    M = rz(MOUNT_YAW if mount_yaw is None else mount_yaw)
    Q = mul(M, mul(tr(body_to_world(q, conjugate)), camera_in_world(heading, pitch)))
    return split_ypr(Q)


def _unwrap(xs: list[float]) -> list[float]:
    out = [xs[0]]
    for a in xs[1:]:
        out.append(out[-1] + ((a - out[-1] + 180) % 360 - 180))
    return out


def _smooth(xs: list[float], window: int) -> list[float]:
    h = window // 2
    return [sum(xs[max(0, i - h):i + h + 1]) / len(xs[max(0, i - h):i + h + 1]) for i in range(len(xs))]


def smoothed_headings(samples: list[tuple[float, Quat]], fps: float = 29.97) -> list[float]:
    heads = _unwrap([heading_of(body_to_world(q)) for _, q in samples])
    return _smooth(heads, max(1, int(HEADING_SMOOTH_S * fps)) | 1)


def view_commands(samples: list[tuple[float, Quat]], start: float, view_yaw: float, view_pitch: float,
                  follow_heading: bool = True, heading_smooth_s: float = 2.0, fps: float = 29.97,
                  mount_yaw: float | None = None, conjugate: bool | None = None, target: str = "v360@s") -> str:
    """sendcmd script for v360 (rorder=ypr, reset_rot=1). With follow_heading the view turns with
    the drone's smoothed heading (+ view_yaw); otherwise it stays locked to the first frame's heading."""
    if not samples:
        return ""
    heads = _unwrap([heading_of(body_to_world(q, conjugate)) for _, q in samples])
    if follow_heading:
        target_h = _smooth(heads, max(1, int(heading_smooth_s * fps)) | 1)
    else:
        target_h = [heads[0]] * len(heads)
    lines = []
    for (t, q), h in zip(samples, target_h):
        y, p, r = v360_angles(q, h + view_yaw, view_pitch, mount_yaw, conjugate)
        lines.append(f"{max(0.0, t - start):.4f} {target} yaw {y:.3f}, {target} pitch {p:.3f}, {target} roll {r:.3f};")
    return "\n".join(lines) + "\n"
