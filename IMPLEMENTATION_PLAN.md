# Implementation Plan

Each phase ends with something that runs, tests that pass, and an update to PROJECT_STATUS.md.

## Phase 0 — Environment and feasibility (this document set)

Done: machine inspection, footage inspection, DJI Studio and Resolve findings, proof of
concept (stitch + reframe + LUT + NVENC + basic QC on real footage).

Still open before Phase 0 can be called complete:
1. User confirms which sample clips were shot in D-Log M (R-02).
2. One frame exported from DJI Studio with its Avata 360 LUT, for a numeric comparison (R-03).
3. User decisions D-006 (master resolution), D-007 (Tauri or Electron), D-009 (repository).

## Phase 1 — Foundation

1. Backend skeleton: uv project, FastAPI, SQLite with numbered migration files, logging, pytest.
2. `metadata_service`: FFprobe wrapper and asset classification. Test against the 7 real clips.
3. `media_ingest` + `project_service`: recursive scan, checksum (first/last 16 MB plus size —
   full hashing of 10 GB files is too slow), duplicate and corruption detection, manifest.
4. `agent_orchestrator`: job table, state machine, worker, resume after kill. Test: kill the
   worker mid-job, restart, job completes.
5. `proxy_service`: thumbnail and a 960x540 flat proxy per clip, built from the LRF when present.
6. UI shell: project dashboard, import folder, asset grid, live job progress.

Exit: import the sample folder from the UI, see 7 assets with thumbnails and correct
metadata, close the application mid-proxy and watch it resume.

## Phase 2 — Video processing

`color_service` (profile registry; colour mode already detected at ingest, D-014),
`reframe_service` with the FFmpeg adapter and keyframed camera paths, a flat-clip path
(crop/scale, no reframe), `timeline_engine` for a hand-written plan, `render_service` presets
(16:9 at 2.7K or 4K by user choice, 9:16 1080x1920 for Reels/Shorts, 1:1), music-only
`audio_service` with loudness normalisation, export manifest.

Exit: a hand-written edit plan JSON renders to a finished, graded MP4 as a 16:9 master and a
9:16 short, from both a 360 clip and a flat clip.

## Phase 3 — Video intelligence

Scene detection, sharpness/exposure/motion metrics on proxies, `model_gateway`, vision-model
tagging of sampled flat frames, deterministic QC. Includes a small benchmark of the installed
vision models on these clips to pick the default.

## Phase 4 — AI Director

Creative Profile store, full edit plan schema, validator, Director prompt with
schema-constrained output and a repair loop limited to two retries, plan preview in the UI.
Two Director modes: "film" (16:9 narrative) and "short" (9:16, hook first, faster cuts,
user-chosen length). One import can produce both.

Exit: brief in, validated plan out, rendered video out, without manual steps.

## Phase 5 — 360 reframing

Horizon levelling (R-01), guided DJI Studio adapter, subject-following camera paths,
smoothing limits on angular velocity.

## Phase 6 — Audio and quality control

Beat analysis and cut alignment, bounded repair policy, review and approval screens.

## Phase 7 — Personalisation

Feedback capture, dataset export, evaluation harness. Fine-tuning only after enough approved
edits exist; threshold to be set from real data.

## Phase 8 — Release

Installer, bundled FFmpeg, onboarding, diagnostics, backup and restore.

## Complexity estimate

| Phase | Size | Main uncertainty |
|---|---|---|
| 1 | medium | none |
| 2 | medium | colour validation |
| 3 | medium | local vision-model quality |
| 4 | large | plan quality from an 8 GB-class model |
| 5 | large | stabilisation without DJI's gyro data |
| 6 | medium | — |
| 7 | large | amount of feedback data |
| 8 | medium | — |

## Dependencies to add

Rust toolchain (if Tauri is chosen), a pinned full FFmpeg build, Python packages: fastapi,
uvicorn, pydantic, pytest; later opencv-python and numpy for motion metrics.
