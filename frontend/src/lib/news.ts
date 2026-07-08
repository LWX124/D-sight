import { apiFetch } from "./api";

export type NewsItem = {
  id: string;
  channel: string;
  title: string | null;
  content: string;
  url: string | null;
  published_at: string;
};

export async function fetchNews(opts: {
  channel?: string;
  before?: string;
  after?: string;
  limit?: number;
} = {}): Promise<NewsItem[]> {
  const p = new URLSearchParams();
  p.set("channel", opts.channel ?? "news");
  if (opts.before) p.set("before", opts.before);
  if (opts.after) p.set("after", opts.after);
  if (opts.limit) p.set("limit", String(opts.limit));
  const r = await apiFetch(`/api/news?${p.toString()}`);
  if (!r.ok) throw new Error("failed to load news");
  return r.json();
}

export async function refreshNews(channel = "news"): Promise<NewsItem[]> {
  const r = await apiFetch(`/api/news/refresh?channel=${channel}`, {
    method: "POST",
  });
  if (!r.ok) throw new Error("failed to refresh news");
  return r.json();
}
