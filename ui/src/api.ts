export const API: string = import.meta.env.VITE_API_URL ?? "http://127.0.0.1:47615";

export type Project = { id: string; name: string; work_dir: string; created_at: string };
export type Asset = {
  id: string; path: string; kind: string; duration_s: number; proxy_of: string | null;
  color_mode: string | null; color_mode_source: string | null; status: string; error: string | null; online?: boolean;
  probe: { video: { width: number; height: number; fps: string }[] };
};
export type Job = {
  id: string; type: string; state: string; progress: number; error: string | null;
  outputs: { proxy_job?: string };
};
export const DONE = ["COMPLETED", "FAILED", "CANCELLED"];

// Errors are shown exactly as the backend sent them.
export async function call<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  let r: Response;
  try {
    r = await fetch(API + path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    });
  } catch (e) {
    throw new Error(`Cannot reach the CineFlow backend at ${API}.\n${e}`);
  }
  const text = await r.text();
  if (!r.ok) {
    let msg = text;
    try {
      const d = JSON.parse(text).detail;
      msg = typeof d === "string" ? d : JSON.stringify(d, null, 2);
    } catch { /* keep raw text */ }
    throw new Error(`${r.status} ${r.statusText}\n${msg}`);
  }
  return JSON.parse(text) as T;
}

// Native folder picker inside Tauri; null in a plain browser (the caller's text box still works).
export async function pickFolder(title: string): Promise<string | null> {
  if (!("__TAURI_INTERNALS__" in window)) return null;
  const { open } = await import("@tauri-apps/plugin-dialog");
  const p = await open({ directory: true, multiple: false, title });
  return typeof p === "string" ? p : null;
}

// Native file picker inside Tauri; null in a plain browser (the caller's text box still works).
export async function pickFile(title: string, name: string, extensions: string[]): Promise<string | null> {
  if (!("__TAURI_INTERNALS__" in window)) return null;
  const { open } = await import("@tauri-apps/plugin-dialog");
  const p = await open({ multiple: false, title, filters: [{ name, extensions }] });
  return typeof p === "string" ? p : null;
}

export type ExportItem = {
  name: string; size_bytes: number; warnings: string[]; brief: string | null;
  render: { width: number; height: number; duration_s: number } | null;
};
export type Reference = {
  id: string; source: string; title: string; duration_s: number; width: number; height: number; vertical: boolean;
  cuts_per_min: number; shot_len_median: number; brightness: number; saturation: number; loudness_lufs: number | null;
};
