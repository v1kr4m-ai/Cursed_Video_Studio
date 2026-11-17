"""Turn a source clip into a flat frame of the requested shape.

`ReframeAdapter` is the seam for other 360 engines (e.g. the guided DJI Studio workflow,
DECISIONS D-002). Adapters return an FFmpeg filter chain plus an optional `sendcmd` script for
per-frame camera moves; they never run commands themselves.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

from .edit_plan import Crop, Shot, View
from .metadata_service import AssetKind, MediaInfo

AVATA360_LENS_FOV = 195  # picked by eye in Phase 0 (R-04)
PLANET_FOV = 250         # stereographic field of view for tiny planet / rabbit hole (poc/out/planet_test.jpg)
CMD_RATE = 30            # camera keyframes per second
# v360 rebuilds its remap table on every camera command. Measured (poc/speed_test.py, 3 s shot,
# 1080x1920): lanczos 209 s, cubic 28 s, fixed view 5 s. So moving views use cubic (R-15).
MOVING_INTERP = "interp=cubic"


@dataclass
class Reframe:
    chain: str               # filter chain from input pads to the reframed picture
    commands: str | None     # sendcmd script; the chain refers to it as "cmds.txt" in the work dir
    moving: bool             # deliberate camera motion: don't let shake removal fight it


class ReframeAdapter(Protocol):
    name: str

    def can_handle(self, info: MediaInfo) -> bool: ...
    def build(self, info: MediaInfo, shot: Shot, w: int, h: int) -> Reframe: ...


def fovs(fov_long: float, w: int, h: int) -> tuple[float, float]:
    """(h_fov, v_fov) for a rectilinear frame whose long side spans `fov_long` degrees."""
    t = math.tan(math.radians(min(fov_long, 179)) / 2)
    if w >= h:
        return fov_long, math.degrees(2 * math.atan(t * h / w))
    return math.degrees(2 * math.atan(t * w / h)), fov_long


def _ease(x: float) -> float:
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, x)))


class FfmpegV360Adapter:
    """Dual fisheye (OSV, both lens streams) straight to the output view in one pass.

    Lens axis points up, so pitch is offset by 90°; rotation order pyr makes yaw a pan along
    the horizon (checked on real footage 2026-11-16, poc/out/yaw_check2.jpg). Per-frame moves
    use sendcmd with reset_rot=1 so each command is absolute (poc/out/acc_test.jpg).
    """
    name = "ffmpeg_v360"

    def can_handle(self, info: MediaInfo) -> bool:
        return info.kind is AssetKind.DUAL_FISHEYE

    @staticmethod
    def _angles(v: View, fov: float, w: int, h: int, stereo: bool) -> dict[str, float]:
        hf, vf = (fov, fov * h / w) if stereo and w >= h else (fov * w / h, fov) if stereo else fovs(fov, w, h)
        return {"yaw": v.yaw, "pitch": 90 + v.pitch, "roll": v.roll, "h_fov": hf, "v_fov": vf}

    def build(self, info: MediaInfo, shot: Shot, w: int, h: int, attitude=None) -> Reframe:
        dur = shot.source_out - shot.source_in
        if attitude and shot.effect in ("none", "pan"):
            return self._gyro(shot, w, h, attitude)
        v = shot.view
        stereo = shot.effect in ("tiny_planet", "rabbit_hole", "planet_reveal")
        down, up = View(yaw=v.yaw, pitch=-90, roll=0), View(yaw=v.yaw, pitch=90, roll=0)

        def at(t: float) -> dict[str, float]:
            x = t / dur if dur else 0
            if shot.effect == "pan":
                e, b = _ease(x), shot.end_view
                yaw = v.yaw + (((b.yaw - v.yaw + 180) % 360) - 180) * e  # short way round
                mid = View(yaw=((yaw + 180) % 360) - 180, pitch=v.pitch + (b.pitch - v.pitch) * e,
                           roll=v.roll + (b.roll - v.roll) * e, fov=v.fov + (b.fov - v.fov) * e)
                return self._angles(mid, mid.fov, w, h, False)
            if shot.effect == "tiny_planet":
                return self._angles(View(yaw=((v.yaw + shot.spin * t + 180) % 360) - 180, pitch=-90), PLANET_FOV, w, h, True)
            if shot.effect == "rabbit_hole":
                return self._angles(View(yaw=((v.yaw + shot.spin * t + 180) % 360) - 180, pitch=90), PLANET_FOV, w, h, True)
            if shot.effect == "planet_reveal":
                e = _ease(x / 0.8)  # unfold over the first 80%, then hold
                return self._angles(View(yaw=v.yaw, pitch=-90 + (v.pitch + 90) * e), PLANET_FOV + (v.fov - PLANET_FOV) * e, w, h, True)
            return self._angles(v, v.fov, w, h, False)

        start = at(0)
        proj = "sg" if stereo else "flat"
        base = (f"v360@s=dfisheye:{proj}:ih_fov={AVATA360_LENS_FOV}:iv_fov={AVATA360_LENS_FOV}:rorder=pyr:reset_rot=1"
                f":yaw={start['yaw']:.3f}:pitch={start['pitch']:.3f}:roll={start['roll']:.3f}"
                f":h_fov={start['h_fov']:.3f}:v_fov={start['v_fov']:.3f}:w={w}:h={h}:interp=lanczos")
        if shot.effect == "none":
            return Reframe(f"[0:v:0][0:v:1]hstack,{base}", None, False)
        if shot.effect in ("tiny_planet", "rabbit_hole"):
            # Spinning a stereographic view about its axis = rotating the image. Render once on a
            # square big enough to cover the frame at any angle, then rotate and crop: no per-frame
            # projection rebuild (that is what made sendcmd effects slow).
            d = math.ceil(math.hypot(w, h) / 2) * 2
            fov = PLANET_FOV * d / max(w, h)
            pitch = 0 if shot.effect == "tiny_planet" else 180
            still = (f"v360=dfisheye:sg:ih_fov={AVATA360_LENS_FOV}:iv_fov={AVATA360_LENS_FOV}:rorder=pyr"
                     f":yaw={v.yaw:.3f}:pitch={pitch}:h_fov={fov:.3f}:v_fov={fov:.3f}:w={d}:h={d}:interp=lanczos")
            spin = math.radians(shot.spin)
            return Reframe(f"[0:v:0][0:v:1]hstack,{still},rotate=a={spin:.6f}*t:ow={w}:oh={h}:c=black", None, True)
        lines = []
        for i in range(int(dur * CMD_RATE) + 1):
            t = i / CMD_RATE
            a = at(t)
            lines.append(f"{t:.4f} " + ", ".join(f"v360@s {k} {a[k]:.3f}" for k in ("yaw", "pitch", "roll", "h_fov", "v_fov")) + ";")
        return Reframe(f"[0:v:0][0:v:1]hstack,sendcmd=f=cmds.txt,{base}", "\n".join(lines) + "\n", True)


    def _gyro(self, shot: Shot, w: int, h: int, attitude) -> Reframe:
        """Stabilised, horizon-levelled view from the drone's per-frame attitude (stabilize.py).
        View yaw is relative to the drone's smoothed heading; pitch is relative to the true horizon."""
        from .stabilize import smoothed_headings, v360_angles
        dur = shot.source_out - shot.source_in
        heads = smoothed_headings(attitude)
        v, b = shot.view, shot.end_view
        lines, first = [], None
        for (t, q), hd in zip(attitude, heads):
            rel = max(0.0, t - shot.source_in)
            e = _ease(rel / dur) if shot.effect == "pan" and dur else 0.0
            yaw = v.yaw + ((((b.yaw - v.yaw + 180) % 360) - 180) * e if b else 0)
            pitch = v.pitch + ((b.pitch - v.pitch) * e if b else 0)
            fov = v.fov + ((b.fov - v.fov) * e if b else 0)
            hf, vf = fovs(fov, w, h)
            a, p, r = v360_angles(q, hd + yaw, pitch)
            first = first or (a, p, r, hf, vf)
            lines.append(f"{rel:.4f} v360@s yaw {a:.3f}, v360@s pitch {p:.3f}, v360@s roll {r:.3f}, "
                         f"v360@s h_fov {hf:.3f}, v360@s v_fov {vf:.3f};")
        a, p, r, hf, vf = first
        base = (f"v360@s=dfisheye:flat:ih_fov={AVATA360_LENS_FOV}:iv_fov={AVATA360_LENS_FOV}:rorder=ypr:reset_rot=1"
                f":yaw={a:.3f}:pitch={p:.3f}:roll={r:.3f}:h_fov={hf:.3f}:v_fov={vf:.3f}:w={w}:h={h}:{MOVING_INTERP}")
        return Reframe(f"[0:v:0][0:v:1]hstack,sendcmd=f=cmds.txt,{base}", "\n".join(lines) + "\n", True)


class FlatCropAdapter:
    """Ordinary video: largest crop of the target aspect at `crop` position, then scale.

    If the crop is smaller than the output, the result is scaled up and `upscale_factor`
    reports by how much so the UI can warn.
    """
    name = "flat_crop"

    def can_handle(self, info: MediaInfo) -> bool:
        return info.kind in (AssetKind.FLAT, AssetKind.EQUIRECTANGULAR)

    @staticmethod
    def crop_box(src_w: int, src_h: int, w: int, h: int, crop: Crop) -> tuple[int, int, int, int]:
        target = w / h
        if src_w / src_h > target:
            ch, cw = src_h, round(src_h * target)
        else:
            cw, ch = src_w, round(src_w / target)
        cw, ch = cw - cw % 2, ch - ch % 2
        return cw, ch, round((src_w - cw) * crop.x), round((src_h - ch) * crop.y)

    def upscale_factor(self, info: MediaInfo, w: int, h: int) -> float:
        cw, _, _, _ = self.crop_box(info.video[0].width, info.video[0].height, w, h, Crop())
        return max(1.0, w / cw)

    def build(self, info: MediaInfo, shot: Shot, w: int, h: int, attitude=None) -> Reframe:
        cw, ch, x, y = self.crop_box(info.video[0].width, info.video[0].height, w, h, shot.crop)
        return Reframe(f"[0:v:0]crop={cw}:{ch}:{x}:{y},scale={w}:{h}:flags=lanczos", None, False)


ADAPTERS: list[ReframeAdapter] = [FfmpegV360Adapter(), FlatCropAdapter()]


def adapter_for(info: MediaInfo) -> ReframeAdapter:
    for a in ADAPTERS:
        if a.can_handle(info):
            return a
    raise ValueError(f"no reframe adapter for {info.kind}")
