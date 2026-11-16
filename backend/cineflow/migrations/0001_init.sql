-- Core tables. Original media is referenced by path, never copied or modified.

CREATE TABLE projects (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    work_dir      TEXT NOT NULL,          -- where proxies, renders and manifests go
    created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE assets (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    path          TEXT NOT NULL,
    size_bytes    INTEGER NOT NULL,
    quick_hash    TEXT NOT NULL,          -- size + first/last 16 MB; full hash of 10 GB files is too slow
    kind          TEXT NOT NULL,          -- metadata_service.AssetKind
    duration_s    REAL NOT NULL,
    probe_json    TEXT NOT NULL,          -- MediaInfo as JSON
    proxy_of      TEXT REFERENCES assets(id),  -- an LRF points at its OSV
    color_mode    TEXT,                   -- NULL until detected/confirmed (R-02)
    color_mode_source TEXT,               -- 'user' | 'detector'
    status        TEXT NOT NULL DEFAULT 'ok',  -- ok | duplicate | corrupt
    error         TEXT,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (project_id, path)
);
CREATE INDEX assets_hash ON assets(quick_hash);

CREATE TABLE jobs (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    type          TEXT NOT NULL,
    state         TEXT NOT NULL DEFAULT 'NEW',
    progress      REAL NOT NULL DEFAULT 0,  -- 0..1, only from real measured work
    inputs_json   TEXT NOT NULL DEFAULT '{}',
    outputs_json  TEXT NOT NULL DEFAULT '{}',
    error         TEXT,
    retries       INTEGER NOT NULL DEFAULT 0,
    pipeline_version TEXT NOT NULL,
    started_at    TEXT,
    updated_at    TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX jobs_state ON jobs(state);

CREATE TABLE job_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id        TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    from_state    TEXT,
    to_state      TEXT NOT NULL,
    message       TEXT,
    at            TEXT NOT NULL DEFAULT (datetime('now'))
);
