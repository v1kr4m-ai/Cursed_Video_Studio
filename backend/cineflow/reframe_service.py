"""Turn a source clip into a flat frame of the requested shape.

`ReframeAdapter` is the seam for other 360 engines (e.g. the guided DJI Studio workflow,
DECISIONS D-002). Adapters return an FFmpeg filter chain; they never run commands themselves.
"""

from __future__ import annotations

import math
from typing import Protocol

from .edit_plan import Crop, View
from .metadata_service import AssetKind, MediaInfo

AVATA360_LENS_FOV = 195  # picked by eye in Phase 0 (R-04)


class ReframeAdapter(Protocol):
    name: str

    def can_handle(self, info: MediaInfo) -> bool: ...
    def filter(self, info: MediaInfo, view: View, crop: Crop, w: int, h: int) -> str: ...


def fovs(fov_long: float, w: int, h: int) -> tuple[float, float]:
    """(h_fov, v_fov) for a rectilinear frame whose long side spans `fov_long` degrees."""
    t = math.tan(math.radians(fov_long) / 2)
    if w >= h:
        return fov_long, math.degrees(2 * math.atan(t * h / w))
    return math.degrees(2 * math.atan(t * w / h)), fov_long


class FfmpegV360Adapter:
    """Dual fisheye (OSV, both lens streams) straight to a flat view in one pass.

    Lens axis points up, so pitch is offset by 90°; rotation order pyr makes yaw a pan along
    the horizon (checked on real footage 2026-11-16, poc/out/yaw_check2.jpg).
    """
    name = "ffmpeg_v360"

    def can_handle(self, info: MediaInfo) -> bool:
        return info.kind is AssetKind.DUAL_FISHEYE

    def filter(self, info: MediaInfo, view: View, crop: Crop, w: int, h: int) -> str:
        hf, vf = fovs(view.fov, w, h)
        return (f"[0:v:0][0:v:1]hstack,v360=dfisheye:flat:ih_fov={AVATA360_LENS_FOV}:iv_fov={AVATA360_LENS_FOV}"
                f":rorder=pyr:yaw={view.yaw:.3f}:pitch={90 + view.pitch:.3f}:roll={view.roll:.3f}"
                f":h_fov={hf:.3f}:v_fov={vf:.3f}:w={w}:h={h}:interp=lanczos")


class FlatCropAdapter:
    """Ordinary video: largest crop of the target aspect at `crop` position, then scale.

    Never upscales beyond the crop: if the crop is smaller than the output, the result is
    scaled up and `upscale_factor` reports by how much so the UI can warn.
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

    def filter(self, info: MediaInfo, view: View, crop: Crop, w: int, h: int) -> str:
        cw, ch, x, y = self.crop_box(info.video[0].width, info.video[0].height, w, h, crop)
        return f"[0:v:0]crop={cw}:{ch}:{x}:{y},scale={w}:{h}:flags=lanczos"


ADAPTERS: list[ReframeAdapter] = [FfmpegV360Adapter(), FlatCropAdapter()]


def adapter_for(info: MediaInfo) -> ReframeAdapter:
    for a in ADAPTERS:
        if a.can_handle(info):
            return a
    raise ValueError(f"no reframe adapter for {info.kind}")
