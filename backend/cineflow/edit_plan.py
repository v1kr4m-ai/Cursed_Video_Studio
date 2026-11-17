"""Edit plan schema (v1, Phase 2 subset).

The Director (Phase 4) will emit this JSON; for now plans are hand-written. Pydantic enforces
types and safe ranges; `check_against_assets` enforces facts that need the database (assets
exist, times inside the clip). Only operations listed here can ever be executed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, model_validator

SCHEMA_VERSION = "1.0"


class View(BaseModel):
    """Virtual camera for 360 footage. Angles in degrees; pitch < 0 looks down.

    `fov` is the field of view along the frame's long side (width for 16:9, height for 9:16).
    Ignored for flat footage.
    """
    yaw: float = Field(0, ge=-180, le=180)
    pitch: float = Field(0, ge=-90, le=90)
    roll: float = Field(0, ge=-45, le=45)
    fov: float = Field(100, ge=40, le=140)


class Crop(BaseModel):
    """Where to cut a narrower frame out of flat footage: 0 = left/top edge, 1 = right/bottom."""
    x: float = Field(0.5, ge=0, le=1)
    y: float = Field(0.5, ge=0, le=1)


Effect = Literal["none", "pan", "tiny_planet", "rabbit_hole", "planet_reveal"]


class Shot(BaseModel):
    """`effect` (360 footage only):
    pan            - view moves smoothly from `view` to `end_view`
    tiny_planet    - stereographic "little planet", slowly spinning (`spin` °/s)
    rabbit_hole    - stereographic looking straight up
    planet_reveal  - starts as a tiny planet and unfolds into `view`
    """
    asset_id: str
    source_in: float = Field(ge=0)
    source_out: float
    view: View = View()
    end_view: View | None = None
    effect: Effect = "none"
    spin: float = Field(20, ge=-90, le=90)
    crop: Crop = Crop()
    speed: Literal[1.0] = 1.0          # slow motion arrives with frame-rate checks (Phase 4)
    transition_in: Literal["cut"] = "cut"
    reason: str = ""
    confidence: float | None = Field(None, ge=0, le=1)

    @model_validator(mode="after")
    def _times(self):
        if self.source_out - self.source_in < 0.5:
            raise ValueError("shot must be at least 0.5 s long")
        if self.source_out - self.source_in > 600:
            raise ValueError("shot longer than 10 minutes")
        if self.effect == "pan" and self.end_view is None:
            raise ValueError("pan needs end_view")
        return self


class Output(BaseModel):
    preset: Literal["master_16x9", "short_9x16", "square_1x1"] = "master_16x9"
    resolution: Literal["2.7k", "4k"] = "2.7k"   # applies to master_16x9 only (D-006)
    fps: Literal["24000/1001", "24/1", "25/1", "30000/1001", "30/1", "50/1", "60000/1001"] = "30000/1001"
    codec: Literal["h264", "h265"] = "h264"
    quality: int = Field(20, ge=14, le=32)       # constant-quality value; lower = better
    stabilize: bool = True   # remove shake (vidstab) on shots without a deliberate camera effect


class Audio(BaseModel):
    music_path: str | None = None    # only music the user owns or is licensed to use
    target_lufs: float = Field(-14, ge=-24, le=-9)
    fade_out_s: float = Field(2, ge=0, le=10)


class EditPlan(BaseModel):
    schema_version: Literal["1.0"] = SCHEMA_VERSION
    project_id: str
    brief: str = ""
    output: Output = Output()
    audio: Audio = Audio()
    timeline: list[Shot] = Field(min_length=1, max_length=500)

    @property
    def duration_s(self) -> float:
        return sum(s.source_out - s.source_in for s in self.timeline)


class PlanError(ValueError):
    pass


def check_against_assets(plan: EditPlan, assets: dict[str, dict]) -> None:
    """`assets` maps id -> asset row (dict). Raises PlanError listing every problem."""
    problems = []
    for i, s in enumerate(plan.timeline):
        a = assets.get(s.asset_id)
        if a is None:
            problems.append(f"shot {i}: unknown asset {s.asset_id}")
            continue
        if a["project_id"] != plan.project_id:
            problems.append(f"shot {i}: asset belongs to another project")
        if a["status"] != "ok":
            problems.append(f"shot {i}: asset is {a['status']}")
        if a.get("proxy_of"):
            problems.append(f"shot {i}: asset is a proxy file, use the original")
        if s.effect != "none" and a["kind"] != "dual_fisheye":
            problems.append(f"shot {i}: effect '{s.effect}' needs 360 footage")
        if not Path(a["path"]).is_file():
            problems.append(f"shot {i}: footage is offline ({a['path']}). Reconnect the drive or card, "
                            "or use Re-link in the Footage tab")
        if s.source_out > a["duration_s"] + 1e-3:
            problems.append(f"shot {i}: ends at {s.source_out:.2f}s but clip is {a['duration_s']:.2f}s")
    if problems:
        raise PlanError("; ".join(problems))
