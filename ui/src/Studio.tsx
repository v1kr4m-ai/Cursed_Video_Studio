import { useCallback, useEffect, useState } from "react";
import { API, Asset, DONE, ExportItem, Job, Project, Reference, call, pickFile } from "./api";

export const STATE: Record<string, string> = {
  NEW: "Waiting to start", INGESTING: "Reading files", PROXYING: "Making previews",
  RENDERING: "Rendering video", ANALYSING: "Analysing",
  COMPLETED: "Done", FAILED: "Failed", CANCELLED: "Cancelled",
};
const LABEL: Record<string, string> = {
  ingest: "Importing footage", proxy: "Making preview copies", render: "Rendering video", reference: "Analysing reference",
};

export function JobBar({ job }: { job: Job }) {
  const live = !DONE.includes(job.state);
  return (
    <div className="job">
      <div className="row between">
        <span>{LABEL[job.type] ?? job.type}</span>
        <span className="muted">{STATE[job.state] ?? job.state}{live && ` · ${Math.round(job.progress * 100)}%`}</span>
      </div>
      <progress max={1} value={job.progress} className={job.state === "FAILED" ? "bad" : ""} />
      {job.error && <small className="bad-text">{job.error}</small>}
    </div>
  );
}

// Poll one job every 1 s until it finishes, then call onDone.
function useJob(onDone: () => void, onError: (e: string) => void) {
  const [id, setId] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  useEffect(() => {
    if (!id) return;
    const t = setInterval(async () => {
      try {
        const j = await call<Job>(`/jobs/${id}`);
        setJob(j);
        if (DONE.includes(j.state)) { setId(null); onDone(); }
      } catch (e: any) { onError(e.message); setId(null); }
    }, 1000);
    return () => clearInterval(t);
  }, [id]);
  const start = async (path: string, body: unknown) => {
    const { job_id } = await call<{ job_id: string }>(path, "POST", body);
    setJob(await call<Job>(`/jobs/${job_id}`));
    setId(job_id);
  };
  return { job, busy: id !== null, start };
}

const MB = (b: number) => `${(b / 1048576).toFixed(1)} MB`;
const secs = (s: number) => `${Math.round(s)} s`;

type Fmt = "short_9x16" | "master_16x9" | "square_1x1";
const FORMATS: { id: Fmt; name: string; hint: string }[] = [
  { id: "short_9x16", name: "Reel / Short (9:16)", hint: "Vertical, for phones" },
  { id: "master_16x9", name: "Film (16:9)", hint: "Widescreen" },
  { id: "square_1x1", name: "Square (1:1)", hint: "Feed posts" },
];

function ExportList({ project, items }: { project: Project; items: ExportItem[] }) {
  return (
    <>
      <h3>Your videos ({items.length})</h3>
      {items.length === 0 && <p className="muted">No videos made yet.</p>}
      <div className="exports">
        {items.map((x) => {
          const vertical = !!x.render && x.render.height > x.render.width;
          return (
            <div className="export" key={x.name}>
              <video controls preload="metadata" className={vertical ? "vertical" : ""}
                src={`${API}/projects/${project.id}/exports/${x.name}`} aria-label={`Preview of ${x.name}`} />
              <div className="meta">
                <div className="name" title={x.name}>{x.name}</div>
                <div className="muted">
                  {MB(x.size_bytes)}
                  {x.render && ` · ${x.render.width}×${x.render.height} · ${secs(x.render.duration_s)}`}
                </div>
                {x.warnings.map((w, i) => <div key={i} className="warn-text">{w}</div>)}
              </div>
            </div>
          );
        })}
      </div>
    </>
  );
}

export function ExportPanel({ project, clips, onError }: { project: Project; clips: Asset[]; onError: (e: string) => void }) {
  const [fmt, setFmt] = useState<Fmt>("short_9x16");
  const [res, setRes] = useState<"2.7k" | "4k">("2.7k");
  const [length, setLength] = useState("");
  const [shot, setShot] = useState("3");
  const [stab, setStab] = useState(true);
  const [fx, setFx] = useState(true);
  const [music, setMusic] = useState("");
  const [refId, setRefId] = useState("");
  const [useAll, setUseAll] = useState(true);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [refs, setRefs] = useState<Reference[]>([]);
  const [exports, setExports] = useState<ExportItem[]>([]);

  const load = useCallback(() => {
    call<ExportItem[]>(`/projects/${project.id}/exports`).then(setExports).catch((e) => onError(e.message));
  }, [project.id]);
  useEffect(() => {
    load();
    call<Reference[]>(`/projects/${project.id}/references`).then(setRefs).catch((e) => onError(e.message));
  }, [load]);
  const { job, busy, start } = useJob(load, onError);

  const defLen = fmt === "short_9x16" ? 30 : 60;
  const make = async () => {
    try {
      await start(`/projects/${project.id}/render`, {
        preset: fmt, resolution: fmt === "master_16x9" ? res : "2.7k",
        // With a reference and no typed length, let the backend take the reference's length.
        target_s: Number(length) || (refId ? null : defLen),
        shot_s: refId ? null : Number(shot) || 3,
        effects: fx, stabilize: stab,
        music_path: music.trim() || null, reference_id: refId || null,
        asset_ids: useAll || picked.size === 0 ? null : [...picked],
      });
    } catch (e: any) { onError(e.message); }
  };

  return (
    <>
      <section className="panel">
        <h3>Make a video</h3>
        <p className="muted">Basic automatic edit: shots are spread evenly through your clips. Smarter shot choice comes with footage analysis.</p>

        <div className="formats" role="radiogroup" aria-label="Format">
          {FORMATS.map((f) => (
            <button key={f.id} type="button" role="radio" aria-checked={fmt === f.id}
              className={`format ${fmt === f.id ? "on" : ""}`} onClick={() => setFmt(f.id)}>
              <strong>{f.name}</strong><small>{f.hint}</small>
            </button>
          ))}
        </div>
        {fmt === "master_16x9" && (
          <div className="field">
            <div className="row" role="radiogroup" aria-label="Film resolution">
              {(["2.7k", "4k"] as const).map((r) => (
                <button key={r} type="button" role="radio" aria-checked={res === r}
                  className={`ghost seg ${res === r ? "on" : ""}`} onClick={() => setRes(r)}>{r === "2.7k" ? "2.7K" : "4K"}</button>
              ))}
            </div>
            {res === "4k" && <small className="muted">4K is upscaled at normal viewing angles; 2.7K keeps all the real detail.</small>}
          </div>
        )}

        <div className="row">
          <label className="field"><span>Length (seconds)</span>
            <input type="number" min={5} max={600} value={length} placeholder={String(defLen)} onChange={(e) => setLength(e.target.value)} /></label>
          <label className="field"><span>Seconds per shot</span>
            <input type="number" min={1} max={10} step={0.5} value={refId ? "" : shot} disabled={!!refId}
              placeholder={refId ? "Auto" : "3"} onChange={(e) => setShot(e.target.value)} /></label>
        </div>

        <label className="check"><input type="checkbox" checked={stab} onChange={(e) => setStab(e.target.checked)} /> Stabilise and level the horizon</label>
        <label className="check"><input type="checkbox" checked={fx} onChange={(e) => setFx(e.target.checked)} /> 360 effects (tiny planet opening, pans)</label>

        <label className="field"><span>Music file (optional)</span>
          <div className="row">
            <input value={music} onChange={(e) => setMusic(e.target.value)} placeholder="Type or choose an audio file" />
            <button type="button" className="ghost" onClick={async () => {
              const p = await pickFile("Music", "Audio", ["mp3", "wav", "m4a", "aac", "flac"]); if (p) setMusic(p);
            }}>Choose…</button>
          </div>
          <small className="muted">Use only music you own or are licensed to use.</small>
        </label>

        <label className="field"><span>Follow the style of (optional)</span>
          <select value={refId} onChange={(e) => setRefId(e.target.value)}>
            <option value="">No reference</option>
            {refs.map((r) => <option key={r.id} value={r.id}>{r.title}</option>)}
          </select>
        </label>

        <label className="check"><input type="checkbox" checked={useAll} onChange={(e) => setUseAll(e.target.checked)} /> Use all clips</label>
        {!useAll && (
          <div className="picklist">
            {clips.map((a) => (
              <label key={a.id} className={`pick ${picked.has(a.id) ? "on" : ""}`}>
                <img src={`${API}/assets/${a.id}/thumbnail`} alt="" loading="lazy"
                  onError={(e) => { (e.target as HTMLImageElement).style.visibility = "hidden"; }} />
                <span className="check">
                  <input type="checkbox" checked={picked.has(a.id)} onChange={(e) => {
                    const n = new Set(picked); e.target.checked ? n.add(a.id) : n.delete(a.id); setPicked(n);
                  }} /> {a.path.split(/[\\/]/).pop()}
                </span>
              </label>
            ))}
          </div>
        )}

        <button disabled={busy} onClick={make}>Make video</button>
        {job && <JobBar job={job} />}
      </section>
      <ExportList project={project} items={exports} />
    </>
  );
}

export function ReferencePanel({ project, onError }: { project: Project; onError: (e: string) => void }) {
  const [src, setSrc] = useState("");
  const [refs, setRefs] = useState<Reference[]>([]);
  const load = useCallback(() => {
    call<Reference[]>(`/projects/${project.id}/references`).then(setRefs).catch((e) => onError(e.message));
  }, [project.id]);
  useEffect(() => { load(); }, [load]);
  const { job, busy, start } = useJob(load, onError);
  const add = async () => {
    try { await start(`/projects/${project.id}/references`, { source: src.trim() }); setSrc(""); }
    catch (e: any) { onError(e.message); }
  };
  return (
    <>
      <section className="panel">
        <h3>Add a reference</h3>
        <label className="field"><span>Video file or YouTube / Instagram link</span>
          <div className="row">
            <input value={src} onChange={(e) => setSrc(e.target.value)} placeholder="Type a link or choose a file" />
            <button type="button" className="ghost" onClick={async () => {
              const p = await pickFile("Reference video", "Video", ["mp4", "mov", "mkv", "webm", "avi", "m4v"]); if (p) setSrc(p);
            }}>Choose…</button>
          </div>
        </label>
        <p className="muted">Links are downloaded only to measure their style (length, cut rhythm, brightness, colour). Nothing from them is used in your video. Only add videos you have the right to download. Instagram may require a login and can refuse.</p>
        <button disabled={!src.trim() || busy} onClick={add}>Add reference</button>
        {job && <JobBar job={job} />}
      </section>
      <h3>References ({refs.length})</h3>
      {refs.length === 0 && <p className="muted">No references yet.</p>}
      <div className="grid">
        {refs.map((r) => (
          <div className="asset" key={r.id}>
            <div className="meta">
              <div className="name" title={r.title}>{r.title}</div>
              <div className="muted" title={r.source} style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.source}</div>
              <div className="tags">
                <span className="tag">{r.vertical ? "Vertical" : "Horizontal"}</span>
                <span className="tag">{secs(r.duration_s)} long</span>
              </div>
              <div className="muted">
                {r.cuts_per_min.toFixed(1)} cuts per minute · typical shot {r.shot_len_median.toFixed(1)} s<br />
                Brightness {Math.round(r.brightness * 100)}% · colour strength {Math.round(r.saturation * 100)}%<br />
                Loudness {r.loudness_lufs === null ? "no sound" : `${r.loudness_lufs.toFixed(1)} LUFS`}
              </div>
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
