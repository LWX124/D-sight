import { apiFetch } from "./api";

export type Kb = { id: string; name: string; is_shared: boolean; doc_count: number };

export type KbDoc = {
  id: string;
  title: string;
  filename: string | null;      // 仅上传文档有值
  status: string;
  chunk_count: number;
  error: string | null;
  source_type: string;          // upload | wechat_article | news_item
  source_url: string | null;
  published_at: string | null;  // 原始发布时间，索引按它倒序
};

export type KbDocDetail = KbDoc & { text: string | null };

export type KbSource = {
  id: string;
  source_type: string;
  source_ref_id: string;
  display_name: string;
  status: string;               // pending | syncing | ready | failed | limited
  enabled: boolean;
  error: string | null;
  last_synced_at: string | null;
};

export type AddItemsResult = {
  added: number;
  duplicate: number;
  failed: { source_ref_id: string; error: string }[];
};

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(await r.text());
  return r.json() as Promise<T>;
}

async function ok(r: Response): Promise<void> {
  if (!r.ok) throw new Error(await r.text());
}

export async function fetchKbs(): Promise<Kb[]> {
  return json(await apiFetch("/api/kb"));
}

export async function createKb(name: string): Promise<Kb> {
  return json(await apiFetch("/api/kb", {
    method: "POST",
    body: JSON.stringify({ name }),
    headers: { "Content-Type": "application/json" },
  }));
}

export async function deleteKb(kbId: string): Promise<void> {
  return ok(await apiFetch(`/api/kb/${kbId}`, { method: "DELETE" }));
}

export async function uploadDoc(kbId: string, file: File): Promise<void> {
  const fd = new FormData();
  fd.append("file", file);
  return ok(await apiFetch(`/api/kb/${kbId}/documents`, { method: "POST", body: fd }));
}

export async function fetchDocs(
  kbId: string,
  opts: { limit?: number; offset?: number } = {},
): Promise<KbDoc[]> {
  const p = new URLSearchParams();
  p.set("limit", String(opts.limit ?? 50));
  p.set("offset", String(opts.offset ?? 0));
  return json(await apiFetch(`/api/kb/${kbId}/documents?${p.toString()}`));
}

export async function fetchDoc(kbId: string, docId: string): Promise<KbDocDetail> {
  return json(await apiFetch(`/api/kb/${kbId}/documents/${docId}`));
}

export async function deleteDoc(kbId: string, docId: string): Promise<void> {
  return ok(await apiFetch(`/api/kb/${kbId}/documents/${docId}`, { method: "DELETE" }));
}

export async function addKbItems(
  kbId: string,
  items: { source_type: string; source_ref_id: string }[],
): Promise<AddItemsResult> {
  return json(await apiFetch(`/api/kb/${kbId}/items`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  }));
}

export async function addKbSource(
  kbId: string,
  body: { source_type: string; source_ref_id: string; display_name: string },
): Promise<KbSource> {
  return json(await apiFetch(`/api/kb/${kbId}/sources`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  }));
}

export async function fetchKbSources(kbId: string): Promise<KbSource[]> {
  return json(await apiFetch(`/api/kb/${kbId}/sources`));
}

export async function deleteKbSource(
  kbId: string,
  sourceId: string,
  purge = false,
): Promise<void> {
  return ok(await apiFetch(`/api/kb/${kbId}/sources/${sourceId}?purge=${purge}`, {
    method: "DELETE",
  }));
}

export async function fetchKbThreadId(kbId: string): Promise<string> {
  const data = await json<{ thread_id: string }>(await apiFetch(`/api/kb/${kbId}/thread`));
  return data.thread_id;
}

// 清除对话：软删当前会话，再取一个新的（GET /thread 会自动重建）。与 news 同做法。
export async function clearKbThread(kbId: string, threadId: string): Promise<string> {
  await ok(await apiFetch(`/api/threads/${threadId}`, { method: "DELETE" }));
  return fetchKbThreadId(kbId);
}

export async function shareKb(kbId: string): Promise<{ share_slug: string }> {
  return json(await apiFetch(`/api/kb/${kbId}/share`, { method: "POST" }));
}

export async function subscribeKb(slug: string): Promise<{ kb_id: string; name: string }> {
  return json(await apiFetch(`/api/kb/subscribe/${slug}`, { method: "POST" }));
}

export async function fetchSubscribed(): Promise<{ id: string; name: string }[]> {
  return json(await apiFetch("/api/kb/subscribed"));
}
