import { useCallback, useEffect, useRef, useState } from "react";
import { API, Asset, DONE, Job, Project, call, pickFolder } from "./api";

const KIND: Record<string, string> = {
  dual_fisheye: "360 video", equirectangular: "360 video",
  dual_fisheye_proxy: "Preview copy (360)", flat: "Flat video",
};
const COLOR: Record<string, string> = { dlog_m: "D-Log M", normal: "Normal" };
const STATE: Record<string, string> = {
  NEW: "Waiting to start", INGESTING: "Reading files", PROXYING: "Making previews",
  COMPLETED: "Done", FAILED: "Failed", CANCELLED: "Cancelled",
};

function fps(r: string) {
  const [n, d] = r.split("/").map(Number);
  const v = d ? n / d : n;
  return Number.isFinite(v) ? `${+v.toFixed(2)} fps` : r;
}
function dur(s: number) {
  const t = Math.round(s);
  return `${Math.floor(t / 60)}:${String(t % 60).padStart(2, "0")}`;
}

function ErrorBox({ text, onClose }: { text: string; onClose: () => void }) {
  return (
    <div className="error" role="alert">
      <pre>{text}</pre>
      <button className="ghost" onClick={onClose}>Dismiss</button>
    </div>
  );
}

function FolderField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="field">
      <span>{label}</span>
      <div className="row">
        <input value={value} onChange={(e) => onChange(e.target.value)} placeholder="Type or choose a folder" />
        <button type="button" className="ghost" onClick={async () => { const p = await pickFolder(label); if (p) onChange(p); }}>
          Choose…
        </button>
      </div>
    </label>
  );
}

function Projects({ onOpen, onError }: { onOpen: (p: Project) => void; onError: (e: string) => void }) {
  const [list, setList] = useState<Project[] | null>(null);
  const [name, setName] = useState("");
  const [dir, setDir] = useState("");
  useEffect(() => {
    call<Project[]>("/projects").then(setList).catch((e) => { setList([]); onError(e.message); });
  }, []);
  const create = async () => {
    try {
      const { id } = await call<{ id: string }>("/projects", "POST", { name: name.trim(), work_dir: dir.trim() });
      onOpen(await call<Project>(`/projects/${id}`));
    } catch (e: any) { onError(e.message); }
  };
  return (
    <main>
      <h2>Your projects</h2>
      {list === null && <p className="muted">Loading…</p>}
      {list?.length === 0 && <p className="muted">No projects yet. Create your first one below.</p>}
      <div className="cards">
        {list?.map((p) => (
          <button key={p.id} className="card" onClick={() => onOpen(p)}>
            <strong>{p.name}</strong>
            <small>{p.work_dir}</small>
          </button>
        ))}
      </div>
      <section className="panel">
        <h3>New project</h3>
        <label className="field"><span>Project name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Coastal flight" /></label>
        <FolderField label="Working folder (previews and project files go here)" value={dir} onChange={setDir} />
        <button disabled={!name.trim() || !dir.trim()} onClick={create}>Create project</button>
      </section>
    </main>
  );
}

function JobBar({ job }: { job: Job }) {
  const label = job.type === "ingest" ? "Importing footage" : "Making preview copies";
  const live = !DONE.includes(job.state);
  return (
    <div className="job">
      <div className="row between">
        <span>{label}</span>
        <span className="muted">{STATE[job.state] ?? job.state}{live && ` · ${Math.round(job.progress * 100)}%`}</span>
      </div>
      <progress max={1} value={job.progress} className={job.state === "FAILED" ? "bad" : ""} />
      {job.error && <small className="bad-text">{job.error}</small>}
    </div>
  );
}

function AssetCard({ a, v, onColor }: { a: Asset; v: number; onColor: (id: string, m: string) => void }) {
  const [noThumb, setNoThumb] = useState(false);
  useEffect(() => setNoThumb(false), [v]);
  const s = a.probe?.video?.[0];
  const isProxy = a.kind === "dual_fisheye_proxy";
  return (
    <div className={`asset ${a.status !== "ok" ? "dim" : ""}`}>
      <div className="thumb">
        {noThumb
          ? <span className="muted">No thumbnail yet</span>
          : <img src={`${API}/assets/${a.id}/thumbnail?v=${v}`} alt="" loading="lazy" onError={() => setNoThumb(true)} />}
      </div>
      <div className="meta">
        <div className="name" title={a.path}>{a.path.split(/[\\/]/).pop()}</div>
        <div className="tags">
          <span className="tag">{KIND[a.kind] ?? a.kind}</span>
          {a.status === "ok"
            ? <span className="tag ok">OK</span>
            : <span className={`tag ${a.status === "corrupt" ? "bad" : "warn"}`}>{a.status === "corrupt" ? "Damaged file" : "Duplicate"}</span>}
        </div>
        <div className="muted">{dur(a.duration_s)}{s && ` · ${s.width}×${s.height} · ${fps(s.fps)}`}</div>
        {a.status !== "ok" && a.error && <div className="bad-text">{a.error}</div>}
        {isProxy
          ? <div className="muted">Colour mode: {a.color_mode ? COLOR[a.color_mode] ?? a.color_mode : "Unknown"}</div>
          : (
            <label className="color">
              <span className="muted">Colour mode{a.color_mode_source === "user" ? " (set by you)" : ""}</span>
              <select value={a.color_mode ?? ""} onChange={(e) => onColor(a.id, e.target.value)}>
                {!a.color_mode && <option value="" disabled>Unknown</option>}
                <option value="dlog_m">D-Log M</option>
                <option value="normal">Normal</option>
              </select>
            </label>
          )}
      </div>
    </div>
  );
}

function ProjectView({ project, onBack, onError }: { project: Project; onBack: () => void; onError: (e: string) => void }) {
  const [assets, setAssets] = useState<Asset[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [polling, setPolling] = useState(false);
  const [folder, setFolder] = useState("");
  const [thumbV, setThumbV] = useState(0);
  const ids = useRef<string[]>([]);

  const loadAssets = useCallback(
    () => call<Asset[]>(`/projects/${project.id}/assets`).then(setAssets).catch((e) => onError(e.message)),
    [project.id]);
  useEffect(() => { loadAssets(); }, [loadAssets]);

  // Poll every 1 s. The ingest job queues a proxy job; its id appears in the ingest job's outputs.
  useEffect(() => {
    if (!polling) return;
    const t = setInterval(async () => {
      try {
        const next: Job[] = [];
        for (const id of [...ids.current]) {
          const j = await call<Job>(`/jobs/${id}`);
          next.push(j);
          const p = j.outputs?.proxy_job;
          if (p && !ids.current.includes(p)) ids.current.push(p);
        }
        setJobs(next);
        setThumbV((v) => v + 1);
        await loadAssets();
        if (next.length === ids.current.length && next.every((j) => DONE.includes(j.state))) setPolling(false);
      } catch (e: any) { onError(e.message); setPolling(false); }
    }, 1000);
    return () => clearInterval(t);
  }, [polling, loadAssets]);

  const start = async () => {
    try {
      const { job_id } = await call<{ job_id: string }>(`/projects/${project.id}/ingest`, "POST", { folder: folder.trim() });
      ids.current = [job_id];
      setJobs([await call<Job>(`/jobs/${job_id}`)]);
      setPolling(true);
    } catch (e: any) { onError(e.message); }
  };

  // DJI .LRF files are the camera's own low-res copies, used internally for previews.
  const clips = assets.filter((a) => a.kind !== "dual_fisheye_proxy");

  const setColor = async (id: string, color_mode: string) => {
    try { await call(`/assets/${id}`, "PATCH", { color_mode }); await loadAssets(); }
    catch (e: any) { onError(e.message); }
  };

  return (
    <main>
      <button className="ghost back" onClick={onBack}>← All projects</button>
      <h2>{project.name}</h2>
      <p className="muted">{project.work_dir}</p>

      <section className="panel">
        <h3>Import footage</h3>
        <FolderField label="Footage folder" value={folder} onChange={setFolder} />
        <button disabled={!folder.trim() || polling} onClick={start}>Start import</button>
        {jobs.map((j) => <JobBar key={j.id} job={j} />)}
      </section>

      <h3>Footage ({clips.length})</h3>
      {clips.length === 0 && <p className="muted">Nothing imported yet.</p>}
      <div className="grid">
        {clips.map((a) => <AssetCard key={a.id} a={a} v={thumbV} onColor={setColor} />)}
      </div>
    </main>
  );
}

export default function App() {
  const [project, setProject] = useState<Project | null>(null);
  const [error, setError] = useState<string | null>(null);
  return (
    <>
      <header><h1>CineFlow <span>AI</span></h1></header>
      {error && <ErrorBox text={error} onClose={() => setError(null)} />}
      {project
        ? <ProjectView key={project.id} project={project} onBack={() => setProject(null)} onError={setError} />
        : <Projects onOpen={setProject} onError={setError} />}
    </>
  );
}
