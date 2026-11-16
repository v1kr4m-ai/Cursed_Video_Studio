"""Projects, asset records, manifest and storage estimate."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import __version__

# Planned proxy: 960x540 H.264 at ~4 Mbit/s, plus one ~100 KB thumbnail per asset.
PROXY_BYTES_PER_SECOND = 4_000_000 / 8
THUMBNAIL_BYTES = 100_000


def create_project(conn: sqlite3.Connection, name: str, work_dir: str | Path) -> str:
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    pid = uuid.uuid4().hex
    conn.execute("INSERT INTO projects (id, name, work_dir) VALUES (?, ?, ?)", (pid, name, str(work_dir)))
    return pid


def get_project(conn: sqlite3.Connection, project_id: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise KeyError(f"no project {project_id}")
    return row


def list_assets(conn: sqlite3.Connection, project_id: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM assets WHERE project_id = ? ORDER BY path", (project_id,)).fetchall()


def storage_estimate(conn: sqlite3.Connection, project_id: str) -> dict:
    """Bytes the project's own files will need. Originals are never copied, so they don't count."""
    row = conn.execute(
        "SELECT COUNT(*) n, COALESCE(SUM(duration_s), 0) dur, COALESCE(SUM(size_bytes), 0) src "
        "FROM assets WHERE project_id = ? AND status = 'ok' AND proxy_of IS NULL", (project_id,)).fetchone()
    proxies = int(row["dur"] * PROXY_BYTES_PER_SECOND + row["n"] * THUMBNAIL_BYTES)
    return {"assets": row["n"], "source_bytes": row["src"], "source_seconds": row["dur"],
            "proxy_bytes_estimate": proxies}


def write_manifest(conn: sqlite3.Connection, project_id: str) -> Path:
    """Write <work_dir>/manifest.json atomically (temp file, then rename)."""
    project = get_project(conn, project_id)
    assets = [{k: r[k] for k in ("id", "path", "size_bytes", "quick_hash", "kind", "duration_s",
                                 "proxy_of", "color_mode", "color_mode_source", "status", "error")}
              for r in list_assets(conn, project_id)]
    manifest = {
        "schema_version": "1.0",
        "generator": f"cineflow {__version__}",
        "written_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project": {"id": project["id"], "name": project["name"], "work_dir": project["work_dir"]},
        "storage": storage_estimate(conn, project_id),
        "assets": assets,
    }
    out = Path(project["work_dir"]) / "manifest.json"
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    tmp.replace(out)
    return out
