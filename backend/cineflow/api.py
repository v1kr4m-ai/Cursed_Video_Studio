"""HTTP API. Binds to localhost only (see backend/README.md).

A single background worker thread runs queued jobs one at a time with its own DB connection.
Ingest jobs queue a proxy job when they finish.
"""

from __future__ import annotations

import json
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_validator

from . import __version__
from .agent_orchestrator import Handler, InvalidTransition, State, cancel, create_job, get_job, recover, run_next
from .db import connect, migrate
from .media_ingest import ingest_folder
from .metadata_service import MediaInfo, ProbeError, probe
from .project_service import create_project, get_project, list_assets, storage_estimate, write_manifest
from .proxy_service import build_project_proxies
from .tools import ToolNotFound, find_tool


def db_path() -> Path:
    p = Path(os.environ.get("CINEFLOW_DB") or Path(os.environ.get("LOCALAPPDATA", ".")) / "CineFlow" / "cineflow.db")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _ingest(conn, job, report):
    inputs = json.loads(job["inputs_json"])
    rep = ingest_folder(conn, job["project_id"], inputs["folder"],
                        lambda i, n, _p: report(i / n if n else 1.0))
    manifest = write_manifest(conn, job["project_id"])
    proxy_job = create_job(conn, job["project_id"], "proxy", {})
    return {**rep.model_dump(), "manifest": str(manifest), "proxy_job": proxy_job}


def _proxy(conn, job, report):
    return build_project_proxies(conn, job["project_id"], report)


HANDLERS = {"ingest": Handler(State.INGESTING, _ingest), "proxy": Handler(State.PROXYING, _proxy)}


def _worker(stop: threading.Event) -> None:
    conn = connect(db_path())
    while not stop.is_set():
        if run_next(conn, HANDLERS) is None:
            stop.wait(0.5)


@asynccontextmanager
async def lifespan(app: FastAPI):
    conn = connect(db_path())
    migrate(conn)
    recover(conn)
    conn.close()
    stop = threading.Event()
    t = threading.Thread(target=_worker, args=(stop,), daemon=True, name="cineflow-worker")
    t.start()
    yield
    stop.set()
    t.join(timeout=5)


app = FastAPI(title="CineFlow AI", version=__version__, lifespan=lifespan)


# Vite dev server; Tauri v2 webview origins (Windows http/https://tauri.localhost, macOS/Linux tauri://localhost).
app.add_middleware(CORSMiddleware, allow_methods=["*"], allow_headers=["*"], allow_origins=[
    "http://localhost:1420", "http://tauri.localhost", "https://tauri.localhost", "tauri://localhost"])


def _conn():
    return connect(db_path())


@app.get("/health")
def health() -> dict:
    tools = {}
    for name in ("ffmpeg", "ffprobe"):
        try:
            tools[name] = find_tool(name)
        except ToolNotFound as e:
            tools[name] = None
            tools[f"{name}_error"] = str(e)
    return {"status": "ok" if all(tools.get(n) for n in ("ffmpeg", "ffprobe")) else "degraded",
            "version": __version__, "tools": tools}


class ProbeRequest(BaseModel):
    path: str


@app.post("/probe", response_model=MediaInfo)
def probe_file(req: ProbeRequest) -> MediaInfo:
    try:
        return probe(req.path)
    except ProbeError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


class NewProject(BaseModel):
    name: str
    work_dir: str


@app.post("/projects")
def new_project(req: NewProject) -> dict:
    return {"id": create_project(_conn(), req.name, req.work_dir)}


@app.get("/projects/{project_id}")
def project(project_id: str) -> dict:
    conn = _conn()
    try:
        p = dict(get_project(conn, project_id))
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    return {**p, "storage": storage_estimate(conn, project_id)}


@app.get("/projects/{project_id}/assets")
def assets(project_id: str) -> list[dict]:
    return [{k: r[k] for k in r.keys() if k != "probe_json"} | {"probe": json.loads(r["probe_json"])}
            for r in list_assets(_conn(), project_id)]


class IngestRequest(BaseModel):
    folder: str


@app.post("/projects/{project_id}/ingest")
def ingest(project_id: str, req: IngestRequest) -> dict:
    conn = _conn()
    try:
        get_project(conn, project_id)
    except KeyError as e:
        raise HTTPException(404, str(e)) from e
    if not Path(req.folder).is_dir():
        raise HTTPException(422, f"not a folder: {req.folder}")
    return {"job_id": create_job(conn, project_id, "ingest", {"folder": req.folder})}


@app.get("/jobs/{job_id}")
def job(job_id: str) -> dict:
    conn = _conn()
    try:
        j = dict(get_job(conn, job_id))
    except KeyError as e:
        raise HTTPException(404, "no such job") from e
    j["outputs"] = json.loads(j.pop("outputs_json"))
    j["inputs"] = json.loads(j.pop("inputs_json"))
    j["events"] = [dict(r) for r in conn.execute(
        "SELECT from_state, to_state, message, at FROM job_events WHERE job_id = ? ORDER BY id", (job_id,))]
    return j


@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str) -> dict:
    try:
        cancel(_conn(), job_id)
    except InvalidTransition as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True}


@app.get("/projects")
def list_projects() -> list[dict]:
    return [dict(r) for r in _conn().execute("SELECT * FROM projects ORDER BY created_at DESC, rowid DESC")]


@app.get("/assets/{asset_id}/thumbnail")
def thumbnail(asset_id: str) -> FileResponse:
    row = _conn().execute("SELECT p.work_dir FROM assets a JOIN projects p ON p.id = a.project_id WHERE a.id = ?",
                          (asset_id,)).fetchone()
    f = Path(row["work_dir"]) / "proxies" / f"{asset_id}.jpg" if row else None
    if f is None or not f.is_file():
        raise HTTPException(404, "no thumbnail")
    return FileResponse(f, media_type="image/jpeg")


class AssetPatch(BaseModel):
    color_mode: str

    @field_validator("color_mode")
    @classmethod
    def _valid(cls, v: str) -> str:
        if v not in ("dlog_m", "normal"):
            raise ValueError("color_mode must be 'dlog_m' or 'normal'")
        return v


@app.patch("/assets/{asset_id}")
def patch_asset(asset_id: str, req: AssetPatch) -> dict:
    conn = _conn()
    cur = conn.execute("UPDATE assets SET color_mode = ?, color_mode_source = 'user' WHERE id = ?",
                       (req.color_mode, asset_id))
    if cur.rowcount == 0:
        raise HTTPException(404, "no such asset")
    return {"id": asset_id, "color_mode": req.color_mode, "color_mode_source": "user"}
