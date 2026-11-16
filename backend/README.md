# CineFlow backend

Python 3.12 (pinned via `uv`), FastAPI, SQLite.

```
uv sync
uv run pytest -q
uv run uvicorn cineflow.api:app --host 127.0.0.1 --port 47615
```

- FFmpeg/FFprobe come from PATH unless `CINEFLOW_FFMPEG` / `CINEFLOW_FFPROBE` are set.
- Real-footage tests read the folder in `CINEFLOW_SAMPLE_DIR` (DJI Avata 360 `.OSV`/`.LRF` files)
  and are skipped when it is not set. They only read the files.
- Always bind to 127.0.0.1. The per-launch auth token from ARCHITECTURE.md is not in yet.

## Modules so far

| File | What it does |
|---|---|
| `cineflow/tools.py` | finds ffmpeg/ffprobe, runs them with argument lists (no shell) |
| `cineflow/metadata_service.py` | `probe()` → typed `MediaInfo`; classifies dual fisheye (OSV), LRF proxy, equirectangular, flat; rejects truncated and non-video files |
| `cineflow/db.py` + `migrations/` | SQLite connection (WAL, foreign keys) and numbered, idempotent migrations |
| `cineflow/media_ingest.py` | recursive discovery, quick hash, duplicate/corrupt flags, LRF→OSV linking; resumable |
| `cineflow/project_service.py` | projects, asset lists, storage estimate, atomic `manifest.json` |
| `cineflow/agent_orchestrator.py` | job state machine, event history, cancel, crash recovery, worker loop |
| `cineflow/proxy_service.py` | thumbnails + previews (OSV/LRF → 1920x960 equirectangular, flat → 960 wide); NVENC with libx264 fallback; progress from FFmpeg itself |
| `cineflow/api.py` | `/health`, `/probe`, `/projects`, `/projects/{id}`, `/projects/{id}/assets`, `/projects/{id}/ingest`, `/jobs/{id}`, `/jobs/{id}/cancel`; background worker thread |

Database location: `CINEFLOW_DB`, default `%LOCALAPPDATA%\CineFlow\cineflow.db`.
