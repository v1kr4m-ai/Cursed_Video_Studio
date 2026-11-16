# Decisions

Each entry: decision, reason, status. PROPOSED entries need the user's approval.

**D-001 Native FFmpeg is the primary stitch and reframe engine. — ACCEPTED**
Proven on real footage in Phase 0. DJI Studio has no automation interface. FFmpeg `v360`
converts dual fisheye straight to a flat reframed view in one pass.

**D-002 DJI Studio is a second, guided adapter behind the same interface. — ACCEPTED**
Needed for stabilised output until R-01 is solved. The user exports a panoramic MP4 into a
watched folder; the pipeline resumes on its own. The UI always says which path a clip took.

**D-003 Technical colour transform = DJI's own Avata 360 D-Log M to Rec.709 LUT, referenced
from the DJI Studio install or the user's download. — ACCEPTED, validation pending (R-03)**
It is the manufacturer's transform for this exact camera. Creative grade is a separate,
later stage working on the Rec.709 result.

**D-004 Colour mode is detected statistically and confirmed by the user. — ACCEPTED**
The file does not carry it (R-02).

**D-005 Resolve is not a dependency. — ACCEPTED**
Not installed; scripting is paid or removed (R-08).

**D-006 Master resolution is chosen by the user at export: 2.7K or 4K. — ACCEPTED (user, 2026-11-16)**
The export screen offers both. Follows R-05: at a ~100° view the footage holds ~2.7K of real
detail, so the 4K option shows a one-line note that it is upscaled at narrow fields of view.
The choice is recorded in the export manifest and remembered in the Creative Profile.

**D-007 Desktop shell: Tauri + React + TypeScript, as the brief recommends. — PROPOSED**
Requires installing Rust (not present). Build tools and WebView2 are already there.
Alternative: Electron, which this machine already builds (two existing Electron projects) and
needs no new toolchain. Tauri gives a smaller installer; Electron gives zero setup.

**D-008 Backend: Python + FastAPI + SQLite, interpreter pinned with uv to 3.12/3.13. — ACCEPTED**
Per brief; pin because of R-13. Jobs run in a worker process; state lives in SQLite so a
restart resumes.

**D-009 Own git repository in this folder, branch `main`. — ACCEPTED (user, 2026-11-16)**
The folder sits inside the `D:\Claude` repository, which never tracked it; the parent's
`.gitignore` now excludes it. Footage, venv and render output are ignored.

**D-010 Modules are Python packages inside one backend, not separate services. — ACCEPTED**
The brief's 20 modules become packages with typed interfaces. Several start as a single file
and are split when they grow. No module is created empty.

**D-011 The Director emits JSON validated against a schema; the engine executes only
allowlisted operations. No model output ever reaches a shell. — ACCEPTED**

**D-012 Models see reframed flat frames at low resolution, never raw fisheye or full
recordings. Cloud models are off unless the user turns them on. — ACCEPTED**

**D-013 The application ships its own pinned FFmpeg (full build). — ACCEPTED**
Because of R-12.

**D-007 update: Tauri chosen. — ACCEPTED (user, 2026-11-16)** Rust 1.100.0 installed via rustup.

**D-014 Colour mode is read from DJI's own metadata; detection by picture statistics is only a
fallback for files without it. — ACCEPTED (2026-11-16)**
Field 2.2.4.1 of the `djmd` clip header: absent/0 = Normal, 19 = D-Log M. Matches all 7 clips
the user labelled (3 D-Log M, 4 Normal). Unknown codes are reported, never guessed. A user's
manual setting always wins over detection. Replaces the statistics-first plan in D-004.

**D-015 Scope is all video, not only 360. — ACCEPTED (user, 2026-11-16)**
360 (OSV) is one input path among several: flat drone video, action cameras, phones, other
cameras. Flat clips skip the reframe stage and use crop/scale instead. Every stage after
ingest takes a flat, Rec.709 shot as its common format.

**D-016 Vertical short-form output is a first-class product: Reels and YouTube Shorts. — ACCEPTED (user, 2026-11-16)**
Render presets include 9:16 1080x1920. For 360 footage the virtual camera is aimed in a
vertical frame, so nothing is cropped away. For flat 16:9 footage the 9:16 frame is a moving
crop that follows the subject, with a visible warning that it keeps ~32% of the width.
The Director gets a "short" mode: hook in the first seconds, faster cutting, length chosen by
the user (default 30 s). Platform length limits change; they live in a settings file, not code.
