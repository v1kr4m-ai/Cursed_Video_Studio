# Project Status

Last updated: 2026-11-16

## Where things stand

Phase 0 is **partly complete**. Investigation and proof of concept are done; three items
need the user before Phase 1 starts (see "Waiting on the user").

## Implemented and tested

- Proof of concept `poc/poc_reframe.sh`: real Avata 360 OSV → stitched, reframed, LUT-graded
  1080p H.264. Output `poc/out/poc_reframed_lut_1080p.mp4` (181 frames, 6.04 s, no black or
  frozen frames). Render speed 0.42x realtime.

- Phase 1 steps 1–2 (backend skeleton + `metadata_service`), in `backend/`:
  - `uv run pytest -q` → 13 passed, including the test that probes all 7 real OSV and 6 LRF files.
  - Server started on 127.0.0.1:8765 (since moved to 47615); `/health` ok, `/probe` on a real 324 s OSV returned
    `dual_fisheye`, two 3840² 10-bit 29.97 fps streams, no audio.
  - SQLite schema `0001_init` (projects, assets, jobs, job_events); migrations idempotent.

- Phase 1 steps 3–5 (backend complete for Phase 1):
  - Ingest: recursive scan, quick hash, duplicate and corrupt flags, LRF→OSV linking, manifest,
    storage estimate. Resumable. Real card: 13 files, 6 LRF linked, 0 corrupt.
  - Job orchestrator: states, event history, cancel, crash recovery. Test kills a worker
    process mid-job, restarts, job completes.
  - Proxies: thumbnail + 1920x960 equirectangular preview from LRF (OSV when no LRF); flat
    clips 960 wide. Progress read from FFmpeg. Real thumbnail checked by eye: horizon centred.
  - API drives it all: create project → ingest job → proxy job queued automatically.
  - `uv run pytest -q` → 27 passed (4 of them read the real footage).
  - Live server, real card (7 clips, 24.4 GB, 19.3 min): ingest 6 s, all 7 proxies 225 s
    (~5x realtime), 532 MB of proxies vs 580 MB estimated. Output in `poc/out/real_project/`.

- Phase 1 step 6, desktop shell (Tauri v2 + React), built by a Sonnet subagent, reviewed:
  projects, import folder (native picker), live job progress, footage grid with thumbnails,
  colour-mode dropdown (user override). `tsc`, `vite build`, `cargo check` pass; window launches.
  LRF camera preview files hidden from the grid. API: `GET /projects`, `GET /assets/{id}/thumbnail`,
  `PATCH /assets/{id}`, CORS for the Tauri origins.
- Phase 2 core (render path), in backend:
  - `edit_plan.py` (schema v1 subset with safe ranges), `color_service.py` (versioned profiles,
    DJI LUT found in the DJI Studio install), `reframe_service.py` (v360 adapter for 360, crop
    adapter for flat video), `render_service.py` (2.7K/4K 16:9, 9:16 Short, 1:1; per-shot render
    then lossless join; optional music with fade and loudness normalisation; export manifest).
  - 360 camera angles verified on real footage: rotation order `pyr`, pitch offset 90°.
  - Real sample: `poc/sample_plan.py` rendered 7 shots from the two dusk flights to
    `poc/out/renders/sample_master_16x9.mp4` (2688x1512, 21 s, 68 s to render) and
    `sample_short_9x16.mp4` (1080x1920, 21 s, 50 s). No black or frozen frames; colour natural.
  - Ingest now back-fills colour mode for clips recorded before detection existed.
- `uv run pytest -q` → 47 passed.

- 2026-11-16 (later): gyro stabilisation + horizon levelling for 360 (D-017), 360 effects
  (tiny planet, rabbit hole, planet reveal, pans), vidstab for flat clips, basic auto edit,
  render and reference jobs with endpoints, reference-video analysis (D-019), Export and
  References screens (Sonnet subagent, reviewed; fixed reference length being ignored),
  CineFlow.cmd launcher, public GitHub repo github.com/v1kr4m-ai/cineflow-ai.
  Real sample `poc/out/renders/sample_short_9x16.mp4`: 5 gyro shots with level horizon,
  planet reveal + tiny planet; 24 s took 620 s to render (R-15).
- External skills reviewed (D-018): ideas adopted, no code copied.

- 2026-11-17: CineFlow moved to port 47615 (8765 belongs to another local app). Offline footage
  (e.g. SD card unplugged) is flagged, skipped by the auto edit, refused with a clear message at
  render, and can be re-linked by content fingerprint (`POST /projects/{id}/relink`, Footage tab).
  Moving 360 views use cubic interpolation (R-15): sample Short 620 s -> 271 s. Clip picker in
  Make a video shows thumbnails. 55 tests pass.

## Not implemented

API auth token; render as a job/endpoint and a UI export screen; keyframed camera moves
(views are fixed per shot); horizon levelling (R-01: visible tilt in banking shots);
shot-to-shot colour matching (the later dusk flight renders greyer); creative grade; transitions
other than cut; slow motion.

## Key facts learned

- OSV = two square HEVC 10-bit fisheye streams (up lens, down lens), no audio, proprietary metadata.
- FFmpeg `v360` stitches and reframes it; lens field of view ≈ 195°.
- DJI Studio 1.0.0.30440 is installed, has no automation, and ships the official Avata 360 D-Log M LUT.
- Colour mode is not readable from the file.
- No stabilisation or horizon levelling without DJI's gyro data — biggest open risk.
- Real detail supports about 2.7K at a 100° view; 4K is an upscale.
- DaVinci Resolve and Rust are not installed.

## Waiting on the user

1. Optional: a 5-second indoor D-Log M clip, to rule out the indoor/outdoor confound (R-02).
2. Optional: export one frame from DJI Studio with the Avata 360 LUT, for colour validation.

Decided 2026-11-16: own git repository (D-009); user picks 2.7K or 4K at export (D-006);
Tauri (D-007); colour mode read from DJI metadata (D-014); scope covers all video (D-015);
Reels/Shorts output (D-016).

- Colour mode detected automatically at ingest from DJI metadata; 37 tests pass.

## Next task

1. Faster stabilised rendering (R-15) and gyro on effect shots.
2. Phase 3 analysis (scene detection, sharpness/exposure, local vision tagging) so the auto
   edit picks good moments instead of evenly spaced ones.
3. Narrated Shorts: local Kokoro voice + word-highlight captions (D-018).

## How to run

Backend + desktop window: `run-dev.ps1` (Windows may need the user to allow local scripts).
Or by hand: `cd backend && uv run uvicorn cineflow.api:app --host 127.0.0.1 --port 47615`, then
`cd ui && npm run tauri dev`. Set `CINEFLOW_DB` to open a specific project database.

## Documents

ENVIRONMENT_REPORT.md, TECHNICAL_RISKS.md, DECISIONS.md, ARCHITECTURE.md, IMPLEMENTATION_PLAN.md

## Log

- 2026-11-16 — Phase 0 inspection, research and proof of concept. No commits made.
- 2026-11-16 — Phase 1 steps 1–2: backend skeleton, metadata_service, SQLite migrations. Fixed
  migration runner splitting on a semicolon inside an SQL comment. No commits made (D-009 pending).
- 2026-11-16 — Phase 1 steps 3–5: ingest, project service, job orchestrator, proxies, API endpoints.
