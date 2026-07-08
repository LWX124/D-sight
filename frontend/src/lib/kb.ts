import { apiFetch } from "./api";

export type Kb = { id: string; name: string; is_shared: boolean; doc_count: number };
export type KbDoc = { id: string; filename: string; status: string; chunk_count: number; error: string | null };

export async function fetchKbs(): Promise<Kb[]> {
  const r = await apiFetch("/api/kb");
  if (!r.ok) throw new Error("failed");
  return r.json();
}
export async function createKb(name: string): Promise<Kb> {
  const r = await apiFetch("/api/kb", { method: "POST", body: JSON.stringify({ name }), headers: { "Content-Type": "application/json" } });
  if (!r.ok) throw new Error("failed");
  return r.json();
}
export async function uploadDoc(kbId: string, file: File): Promise<void> {
  const fd = new FormData();
  fd.append("file", file);
  const r = await apiFetch(`/api/kb/${kbId}/documents`, { method: "POST", body: fd });
  if (!r.ok) throw new Error("upload failed");
}
export async function fetchDocs(kbId: string): Promise<KbDoc[]> {
  const r = await apiFetch(`/api/kb/${kbId}/documents`);
  if (!r.ok) throw new Error("failed");
  return r.json();
}
export async function shareKb(kbId: string): Promise<{ share_slug: string }> {
  const r = await apiFetch(`/api/kb/${kbId}/share`, { method: "POST" });
  if (!r.ok) throw new Error("failed");
  return r.json();
}
export async function subscribeKb(slug: string): Promise<{ kb_id: string; name: string }> {
  const r = await apiFetch(`/api/kb/subscribe/${slug}`, { method: "POST" });
  if (!r.ok) throw new Error("failed");
  return r.json();
}
export async function fetchSubscribed(): Promise<{ id: string; name: string }[]> {
  const r = await apiFetch("/api/kb/subscribed");
  if (!r.ok) throw new Error("failed");
  return r.json();
}
