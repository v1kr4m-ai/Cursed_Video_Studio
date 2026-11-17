# Cursed Video Studio

_Formerly CineFlow AI. Internal code names (the `cineflow` package, `CINEFLOW_*` settings, the `%LOCALAPPDATA%\CineFlow` data folder) keep the old name so existing setups keep working._

Cursed Video Studio is a local-first AI cinematography studio for Windows. The first target is footage from the DJI Avata 360 recorded in D-Log M: the app imports the raw dual-fisheye files, stitches and reframes them into flat shots, applies DJI's own colour transform, and renders finished 16:9 and 9:16 videos. The design rule is: AI decides, deterministic software (FFmpeg) executes, and quality control verifies. Models are meant to produce a validated edit plan, never commands, and everything runs on your own machine.

This is early work. Only the import, preview, colour and render path exist today. The AI parts (analysis, the Director that writes edit plans, the QC engine) are not built yet. See the status table below before you try it.

## Status

| Area | State | Notes |
|---|---|---|
| Probe and classify media (OSV, LRF, equirectangular, flat) | Implemented and tested | `metadata_service` |
| Ingest: recursive scan, quick hash, duplicate and corrupt flags, LRF-to-OSV linking, manifest | Implemented and tested | Checked on a real card of 7 OSV and 6 LRF files |
| SQLite storage, migrations, job queue with crash recovery | Implemented and tested | A test kills the worker mid-job and the job completes after restart |
| Thumbnails and 1920x960 previews (from LRF when present) | Implemented and tested | NVENC with libx264 fallback |
| D-Log M detection from DJI metadata | Implemented and tested | Verified on 7 labelled clips; see caveat below |
| Colour: official DJI Avata 360 D-Log M to Rec.709 LUT | Implemented, validated by eye only | No numeric comparison against DJI Studio yet |
| Edit plan schema (subset) and render path: 2.7K/4K 16:9, 9:16 Short, 1:1, optional music, per-shot render then lossless join, export manifest | Implemented and tested | Driven from a hand-written plan; sample renders exist for 16:9 and 9:16 |
| Backend HTTP API and desktop shell: projects, folder import, job progress, footage grid, colour-mode override | Implemented | `tsc`, `vite build` and `cargo check` pass; the window launches |
| Gyro-based 360 stabilisation and horizon levelling | Implemented | Uses the drone's per-frame attitude from DJI metadata; level horizon checked by eye on two flights. Slow to render (per-frame projection rebuild). Not yet applied to effect shots |
| Export screen: Short/Film/Square, 2.7K/4K, music, stabilise, effects, exports list with player | Implemented | Uses a basic automatic edit (shots spread evenly) until footage analysis exists |
| 360 effects: tiny planet (spinning), rabbit hole, planet reveal, smooth pans | Implemented | |
| Reference videos (file, or YouTube/Instagram link via yt-dlp): measured length, cut rhythm, brightness, colour, loudness | Implemented | The automatic edit follows length and cut rhythm; fuller style matching comes with the Director |
| Image-based stabilisation (vidstab) for flat clips | Implemented | Little effect on slow drone tilt; the gyro path is the real fix for 360 |
| Analysis (scene detection, vision-model tagging), AI Director, QC engine | Planned | Not started |
| API auth token, shot-to-shot colour matching, creative grade, transitions other than cut, slow motion | Planned | Not started |

Main open items: render speed for stabilised shots, smarter shot choice (analysis), and the AI Director.

## What we learned about the footage

Facts marked (reverse engineered) come from inspecting sample files, not from DJI documentation, and could change with firmware.

- **OSV format.** An `.OSV` file holds two square 3840x3840 HEVC 10-bit fisheye streams (one per lens) and no audio. A data track called `djmd` carries camera metadata as protobuf with an unpublished schema (`dvtm_AVATA360.proto`). One sample clip was recorded at 3000x3000, 50 fps. `.LRF` files are low-resolution preview copies.
- **D-Log M detection** (reverse engineered). The clip header field `2.2.4.1` in the `djmd` track is absent or 0 for Normal and 19 for D-Log M. It matched all 7 clips the owner had labelled (3 D-Log M, 4 Normal) across firmware 01.00.01 and 01.00.06. Caveat: in that sample every D-Log M clip was outdoor and every Normal clip was indoor. The field sits in the static camera header rather than the GPS block, so a confound is unlikely, but one indoor D-Log M clip would settle it. Unknown codes are reported as unknown, never guessed, and a manual setting always wins.
- **FFmpeg `v360` conventions.** `v360` converts dual fisheye straight to a flat reframed view in one pass, without a full equirectangular intermediate. Camera angles use rotation order `rorder=pyr` and a pitch offset of 90 degrees (verified on real footage). When angles are sent per frame through `sendcmd`, `reset_rot=1` makes each command absolute.
- **Lens field of view** is about 195 degrees. This was picked by eye, not measured with a calibration target.
- **Attitude and gyro data** (reverse engineered). Field `3.4.14.4` of each `djmd` packet is a unit quaternion (w, x, y, z), one per video frame; its norm checks out at 1.000. Field `3.3.2.1.3` holds about 134 gyro-rate samples per frame. The quaternion drives the stabiliser (exact rotation maths from FFmpeg's `vf_v360.c`, camera mount offset 90°); the gyro samples are kept for possible rolling-shutter work.
- **Real detail.** At a 100 degree view the footage holds about 2.7K of real detail, so a 4K export is an upscale at narrow fields of view. The export choice between 2.7K and 4K is left to the user.

## Architecture

```
Desktop UI (Tauri v2 + React)  --HTTP-->  Backend (FastAPI, 127.0.0.1 only)
                                              |
                              +---------------+----------------+
                           SQLite          Job worker         FFmpeg / FFprobe
                     (projects, assets,   (background        (argument lists,
                      jobs, job events)    thread)             never a shell)

ingest -> proxy -> analyse -> plan -> reframe + grade + edit -> render -> QC -> review
 done     done     planned    planned        done (hand plan)     done     planned
```

For Avata 360, reframe, grade and edit are one FFmpeg filter graph per shot: `hstack` of the two lenses, `v360` (dual fisheye to flat), `lut3d` (technical transform), then encode. The UI keeps no state of its own; it shows what the backend reports.

### Backend modules (`backend/cineflow/`)

| Module | What it does |
|---|---|
| `tools.py` | Finds ffmpeg/ffprobe and runs them with argument lists |
| `metadata_service.py` | `probe()` returns typed media info; classifies dual fisheye, LRF proxy, equirectangular, flat; rejects truncated files |
| `dji_meta.py` | Reads facts from the DJI `djmd` track (colour mode); fails safe to "unknown" |
| `attitude.py` | Reads the per-frame attitude quaternion (work in progress) |
| `stabilize.py` | Turns attitude into `v360` angles for stabilisation and levelling (work in progress, mapping being calibrated) |
| `db.py`, `migrations/` | SQLite (WAL, foreign keys) and numbered idempotent migrations |
| `media_ingest.py` | Discovery, quick hash, duplicate/corrupt flags, LRF linking; resumable |
| `project_service.py` | Projects, asset lists, storage estimate, atomic `manifest.json` |
| `agent_orchestrator.py` | Job state machine, event history, cancel, crash recovery, worker loop |
| `proxy_service.py` | Thumbnails and previews; progress read from FFmpeg itself |
| `color_service.py` | Versioned colour profiles and LUT lookup |
| `edit_plan.py` | Edit plan schema (v1 subset) with safe parameter ranges |
| `reframe_service.py` | `v360` adapter for 360 footage, crop adapter for flat video |
| `render_service.py` | Presets, per-shot render, lossless join, music, export manifest |
| `api.py` | FastAPI app and background worker thread |

The UI is in `ui/` (React, TypeScript, Tauri v2). `poc/` holds the proof-of-concept script, sample plan renderer and stabilisation experiments.

## Requirements

- Windows 11.
- Python 3.12, managed with [uv](https://docs.astral.sh/uv/).
- Node.js 18 or newer.
- Rust toolchain (Tauri v2), with the usual Windows build tools and WebView2.
- FFmpeg and FFprobe, on `PATH` or named by `CINEFLOW_FFMPEG` / `CINEFLOW_FFPROBE`. The build needs the `v360` and `lut3d` filters.
- Optional: an NVIDIA GPU for NVENC encoding. Without one the app falls back to libx264.
- Optional: DJI Studio, which is where the official Avata 360 D-Log M LUT comes from. The LUT is not bundled with this repository. Point `CINEFLOW_LUT_DIR` at a folder containing it if you do not have DJI Studio installed.

## Quick start

Double-click `Cursed_Video_Studio.cmd`. It stops Cursed Video Studio processes left over from an earlier run (matched by command line; it never stops other programs), refuses to start if port 47615 belongs to another program, starts the backend in a minimised window, waits for `/health` to answer as Cursed Video Studio, installs UI packages on first run, and opens the desktop window with `npm run tauri dev`. Closing the window stops Cursed Video Studio's backend and frees the port. The first launch compiles the Rust shell and takes a while.

By hand, in two terminals:

```
cd backend
uv sync
uv run uvicorn cineflow.api:app --host 127.0.0.1 --port 47615
```

```
cd ui
npm install
npm run tauri dev
```

`run-dev.ps1` does the same from PowerShell (Windows may ask you to allow local scripts).

### Tests

```
cd backend
uv run pytest -q
```

Tests that read real footage use the folder named by `CINEFLOW_SAMPLE_DIR` and are skipped when it is not set or does not exist. They only read the files.

## Environment variables

| Variable | Purpose | Default |
|---|---|---|
| `CINEFLOW_DB` | Path of the SQLite database | `%LOCALAPPDATA%\Cursed Video Studio\cineflow.db` |
| `CINEFLOW_FFMPEG` | Path to `ffmpeg.exe` | Looked up on `PATH` |
| `CINEFLOW_FFPROBE` | Path to `ffprobe.exe` | Looked up on `PATH` |
| `CINEFLOW_LUT_DIR` | Extra folder searched for the Avata 360 LUT | DJI Studio install |
| `CINEFLOW_SAMPLE_DIR` | Folder of real OSV/LRF files for the real-footage tests | Tests skipped if absent |
| `VITE_API_URL` | Backend URL used by the UI at build time | `http://127.0.0.1:47615` |

## API

The backend listens on `127.0.0.1:47615` only. There is no auth token yet.

| Method and path | Purpose |
|---|---|
| `GET /health` | Status and the ffmpeg/ffprobe paths found |
| `POST /probe` | Probe one media file |
| `GET /projects` | List projects |
| `POST /projects` | Create a project |
| `GET /projects/{project_id}` | One project |
| `GET /projects/{project_id}/assets` | Assets in a project |
| `POST /projects/{project_id}/ingest` | Start an ingest job; a proxy job is queued automatically |
| `GET /jobs/{job_id}` | Job state, progress and events |
| `POST /jobs/{job_id}/cancel` | Cancel a job |
| `GET /assets/{asset_id}/thumbnail` | Thumbnail image |
| `PATCH /assets/{asset_id}` | Edit an asset, for example the colour mode override |
| `POST /projects/{project_id}/render` | Start a render job (preset, resolution, length, effects, stabilise, music, reference) |
| `GET /projects/{project_id}/exports` | Finished videos |
| `GET /projects/{project_id}/exports/{name}` | Stream one finished video |
| `POST /projects/{project_id}/references` | Add a reference video (file or YouTube/Instagram link) |
| `GET /projects/{project_id}/references` | Measured reference styles |

## Privacy and safety

- Local first. Footage is never uploaded. Cloud models are off by design unless you turn them on, and none are wired in yet.
- GPS data in the DJI metadata is never exported to rendered files.
- Original media is opened read-only. Everything the app writes goes under a working folder you choose.
- FFmpeg is always started with an argument list. Model output will be validated against a schema and an allowlist of operations and never reaches a shell.
- Models are meant to see low-resolution reframed flat frames, never raw fisheye or full recordings.
- The backend binds to localhost only.

## Roadmap

1. Foundation: backend, ingest, jobs, proxies, desktop shell. Done.
2. Video processing: colour, reframe, render presets. Core done; export screen and keyframed camera moves remain.
3. Video intelligence: scene detection, quality metrics, local vision-model tagging, QC checks.
4. AI Director: Creative Profile, full edit plan schema and validator, "film" and "short" modes.
5. 360 reframing: gyro stabilisation and horizon levelling (in progress), guided DJI Studio adapter as a fallback, subject-following camera paths.
6. Audio and QC: beat-aligned cuts, bounded repair, review and approval screens.
7. Personalisation: feedback capture, dataset export, evaluation.
8. Release: installer, bundled FFmpeg, onboarding.

Next planned: narrated Shorts (local AI voice + word-highlight captions), gyro on effect shots, faster stabilised rendering.

More detail: [PROJECT_STATUS.md](PROJECT_STATUS.md), [ARCHITECTURE.md](ARCHITECTURE.md), [DECISIONS.md](DECISIONS.md), [TECHNICAL_RISKS.md](TECHNICAL_RISKS.md), [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md), [ENVIRONMENT_REPORT.md](ENVIRONMENT_REPORT.md), [backend/README.md](backend/README.md).

## Licence

No licence chosen yet — all rights reserved until one is added.
