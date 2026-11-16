# CineFlow AI — Architecture

Principle: AI decides, deterministic software executes, quality control verifies, the user
steps in only when needed.

## Shape

```
Desktop UI (Tauri/React)  ──HTTP + server-sent events──►  Backend (FastAPI, localhost only)
                                                              │
                                             ┌────────────────┼─────────────────┐
                                          SQLite          Job worker        model_gateway
                                       (projects,       (one process,      (Ollama; cloud
                                     assets, jobs,      runs FFmpeg)        only if enabled)
                                     plans, feedback)
```

- The UI holds no state of its own; it renders what the backend reports. Progress numbers
  come from FFmpeg's own progress output and job records, never from timers.
- Original media is opened read-only. Everything the application writes goes under a
  per-project working folder chosen by the user.

## Pipeline

```
ingest ─► proxy ─► analyse ─► plan ─► (reframe + grade + edit) ─► render ─► QC ─► review
```

For Avata 360, reframe, grade and edit are a single FFmpeg filter graph per shot:

```
[lens A][lens B] hstack ─► v360 dfisheye→flat (yaw, pitch, roll, field of view)
                        ─► lut3d (technical transform) ─► creative grade ─► encode
```

Verified in Phase 0 up to and including `lut3d`. Stitching to a full equirectangular
intermediate is avoided: it is slower and larger, and the flat view can be taken directly.

## Modules

Packages under `backend/cineflow/`. Each exposes typed functions and Pydantic models; nothing
imports another module's internals.

| Module | Responsibility | Phase |
|---|---|---|
| `media_ingest` | find files, checksum, detect duplicates and broken files | 1 |
| `metadata_service` | FFprobe wrapper; classify asset kind (OSV dual fisheye, equirectangular, flat) | 1 |
| `project_service` | projects, assets, manifest, storage estimate | 1 |
| `proxy_service` | thumbnails and low-resolution flat proxies | 1 |
| `agent_orchestrator` | job state machine and persistent queue | 1 |
| `color_service` | colour-mode detection, versioned colour profiles, LUT application | 2 |
| `reframe_service` | adapter interface; `FfmpegV360Adapter`, `DjiStudioGuidedAdapter` | 2 / 5 |
| `timeline_engine` | edit plan → FFmpeg commands (argument lists, never shell strings) | 2 |
| `render_service` | presets, NVENC/x264/x265, export manifest | 2 |
| `audio_service` | music import, loudness, fades; beat analysis later | 2 / 6 |
| `scene_detection`, `motion_analysis` | `scdet`, optical flow, blur and exposure metrics | 3 |
| `analysis_service` | frame sampling, vision-model tagging, timestamped annotations with confidence | 3 |
| `qc_service` | black/frozen frames, stream checks, loudness; PASS / WARNING / FAIL with reasons | 3 / 6 |
| `model_gateway` | one interface over Ollama and optional cloud providers; logs model and version | 3 |
| `director_service` | brief + Creative Profile + annotations → edit plan JSON | 4 |
| `edit_plan_validator` | schema, asset existence, time ranges, safe parameter ranges, allowlist | 4 |
| `feedback_service` | approvals, rejections, manual corrections; stated vs inferred preferences | 7 |
| `learning_service` | dataset export, evaluation, adapter versions | 7 |
| `desktop_ui` | `ui/` — React application | 1 onward |

## Reframe adapter interface

```python
class ReframeAdapter(Protocol):
    name: str
    def can_handle(self, asset: Asset) -> bool: ...
    def render_shot(self, shot: Shot, out: Path, on_progress: Callable[[float], None]) -> RenderResult: ...
```

`FfmpegV360Adapter` runs unattended. `DjiStudioGuidedAdapter` puts the job into
`WAITING_FOR_USER`, shows instructions, watches an export folder and resumes when a matching
file appears. A third engine can be added without touching callers.

## Edit plan (outline; full schema is a Phase 4 deliverable)

```json
{
  "schema_version": "1.0",
  "project_id": "…", "plan_id": "…", "created_by": {"model": "qwen3:8b", "gateway": "ollama"},
  "brief": "…",
  "output": {"width": 2688, "height": 1512, "fps": "30000/1001", "codec": "h264", "container": "mp4"},
  "color": {"profile_id": "avata360_dlogm_rec709_v1", "look": "natural_cinematic"},
  "audio": {"music_asset_id": null, "target_lufs": -14},
  "timeline": [{
    "asset_id": "…", "source_in": 160.0, "source_out": 166.0, "speed": 1.0,
    "reframe": {"keyframes": [{"t": 0, "yaw": 0, "pitch": -10, "roll": 0, "h_fov": 100}]},
    "transition_in": "cut", "reason": "…", "confidence": 0.8
  }]
}
```

Timeline position is derived from order and durations, so it cannot be inconsistent.
Allowed transitions, speed range and field-of-view range are fixed lists and bounds in the validator.

## Job state machine

States as in the brief: NEW, INGESTING, PROXYING, ANALYSING, PLANNING, PLAN_READY, REFRAMING,
GRADING, EDITING, RENDERING, QC, READY_FOR_REVIEW, APPROVED, plus WAITING_FOR_USER, FAILED,
CANCELLED, PAUSED. One `jobs` row per job with state, progress, timestamps, inputs, outputs,
error, retry count and pipeline version; one `job_events` row per transition. Each stage
writes its output to a temporary name and renames on success, so a stage either finished or
is rerun. On start-up, jobs left in a running state are requeued at their last finished stage.

## Security

Backend binds to 127.0.0.1 with a per-launch token. FFmpeg is always started with an argument
list. Paths from plans are resolved against known asset records, never taken as given. API
keys go in Windows Credential Manager. Cloud calls are refused unless the setting is on, and
every one is logged.
