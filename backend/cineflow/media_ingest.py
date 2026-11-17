"""Folder ingest: discover, fingerprint, probe, record.

Read-only on source media. Each file is recorded in its own transaction, so an interrupted
ingest resumes by running it again: files already recorded with the same size are skipped.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path

from pydantic import BaseModel

from .dji_meta import ColorMode, color_mode
from .metadata_service import VIDEO_EXTENSIONS, AssetKind, ProbeError, probe

log = logging.getLogger(__name__)

HASH_CHUNK = 16 * 1024 * 1024


class IngestReport(BaseModel):
    found: int = 0
    added: int = 0
    skipped_existing: int = 0
    duplicates: int = 0
    corrupt: int = 0
    linked_proxies: int = 0


def discover(folder: str | Path) -> Iterator[Path]:
    """Video files under `folder`, recursively, sorted for a stable order."""
    folder = Path(folder)
    if not folder.is_dir():
        raise NotADirectoryError(folder)
    yield from sorted(p for p in folder.rglob("*")
                      if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS and not p.name.startswith("."))


def quick_hash(path: str | Path) -> str:
    """sha256 of size + first and last 16 MB.

    ponytail: partial hash; two files differing only in the middle would collide. Good enough
    for duplicate detection of camera files; switch to a full hash in a background job if a
    stronger integrity check is ever needed.
    """
    path = Path(path)
    size = path.stat().st_size
    h = hashlib.sha256(str(size).encode())
    with path.open("rb") as f:
        h.update(f.read(HASH_CHUNK))
        if size > HASH_CHUNK:
            f.seek(max(HASH_CHUNK, size - HASH_CHUNK))
            h.update(f.read(HASH_CHUNK))
    return h.hexdigest()


def ingest_folder(conn: sqlite3.Connection, project_id: str, folder: str | Path,
                  on_progress: Callable[[int, int, Path], None] | None = None) -> IngestReport:
    files = list(discover(folder))
    rep = IngestReport(found=len(files))
    for i, path in enumerate(files):
        if on_progress:
            on_progress(i, len(files), path)
        size = path.stat().st_size
        existing = conn.execute("SELECT id, size_bytes, status, color_mode_source, probe_json FROM assets "
                                "WHERE project_id = ? AND path = ?", (project_id, str(path))).fetchone()
        if existing and existing["size_bytes"] == size:
            # Backfill colour mode for assets recorded before detection existed.
            if existing["status"] == "ok" and existing["color_mode_source"] is None \
                    and '"data_handlers":[]' not in existing["probe_json"].replace(" ", ""):
                cm = color_mode(path)
                if cm.mode is not ColorMode.UNKNOWN:
                    conn.execute("UPDATE assets SET color_mode = ?, color_mode_source = ? WHERE id = ?",
                                 (cm.mode.value, cm.source, existing["id"]))
            rep.skipped_existing += 1
            continue

        qh = quick_hash(path)
        status, error, kind, duration, probe_json = "ok", None, "unknown", 0.0, "{}"
        cmode, csource = None, None
        try:
            info = probe(path)
            kind, duration, probe_json = info.kind.value, info.duration_s, info.model_dump_json()
            if info.data_handlers:  # only DJI-style files carry the metadata track
                cm = color_mode(path)
                if cm.mode is not ColorMode.UNKNOWN:
                    cmode, csource = cm.mode.value, cm.source
        except ProbeError as e:
            status, error = "corrupt", str(e)[:2000]
            rep.corrupt += 1

        if status == "ok":
            dup = conn.execute("SELECT path FROM assets WHERE project_id = ? AND quick_hash = ? AND status = 'ok' AND path != ?",
                               (project_id, qh, str(path))).fetchone()
            if dup:
                status, error = "duplicate", f"same content as {dup['path']}"
                rep.duplicates += 1

        conn.execute(
            "INSERT INTO assets (id, project_id, path, size_bytes, quick_hash, kind, duration_s, probe_json, status, error, "
            "color_mode, color_mode_source) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (project_id, path) DO UPDATE SET size_bytes=excluded.size_bytes, quick_hash=excluded.quick_hash, "
            "kind=excluded.kind, duration_s=excluded.duration_s, probe_json=excluded.probe_json, "
            "status=excluded.status, error=excluded.error, "
            # a user's confirmation is never overwritten by detection
            "color_mode=CASE WHEN assets.color_mode_source='user' THEN assets.color_mode ELSE excluded.color_mode END, "
            "color_mode_source=CASE WHEN assets.color_mode_source='user' THEN 'user' ELSE excluded.color_mode_source END",
            (uuid.uuid4().hex, project_id, str(path), size, qh, kind, duration, probe_json, status, error,
             cmode, csource))
        rep.added += 1
        log.info("ingested %s: %s %s", path, kind, status)

    rep.linked_proxies = link_proxies(conn, project_id)
    if on_progress:
        on_progress(len(files), len(files), Path(folder))
    return rep


def relink(conn: sqlite3.Connection, project_id: str, folder: str | Path) -> dict:
    """Find offline assets in `folder` by content fingerprint and point them at the new paths.
    Handles a card that came back under another drive letter, or footage copied elsewhere."""
    # Several assets can share a fingerprint (byte-identical copies), so keep a list per hash
    # and match one file to one asset, preferring the same file name.
    offline: dict[str, list] = {}
    for r in conn.execute("SELECT id, path, quick_hash, size_bytes FROM assets WHERE project_id = ?", (project_id,)):
        if not Path(r["path"]).is_file():
            offline.setdefault(r["quick_hash"], []).append(r)
    sizes = {r["size_bytes"] for rs in offline.values() for r in rs}
    found = 0
    for p in discover(folder):
        if not any(offline.values()):
            break
        if p.stat().st_size not in sizes:  # cheap filter before hashing
            continue
        rs = offline.get(quick_hash(p))
        if rs:
            r = next((x for x in rs if Path(x["path"]).name.lower() == p.name.lower()), rs[0])
            rs.remove(r)
            conn.execute("UPDATE assets SET path = ? WHERE id = ?", (str(p), r["id"]))
            found += 1
    return {"relinked": found, "still_offline": sum(len(rs) for rs in offline.values())}


def link_proxies(conn: sqlite3.Connection, project_id: str) -> int:
    """Point each DJI .LRF at the .OSV with the same name in the same folder."""
    rows = conn.execute("SELECT id, path FROM assets WHERE project_id = ? AND kind = ? AND proxy_of IS NULL",
                        (project_id, AssetKind.DUAL_FISHEYE_PROXY.value)).fetchall()
    main = {str(Path(m["path"]).with_suffix("")).lower(): m["id"] for m in conn.execute(
        "SELECT id, path FROM assets WHERE project_id = ? AND kind = ? AND status = 'ok'",
        (project_id, AssetKind.DUAL_FISHEYE.value))}
    n = 0
    for r in rows:
        match = main.get(str(Path(r["path"]).with_suffix("")).lower())
        if match:
            conn.execute("UPDATE assets SET proxy_of = ? WHERE id = ?", (match, r["id"]))
            n += 1
    return n
