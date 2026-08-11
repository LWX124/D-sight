import { apiFetch } from "./api";

export type WechatAccount = { fakeid: string; nickname: string; avatar: string | null; signature: string | null };
export type Subscription = { id: string; account_id: string; fakeid: string; name: string; avatar: string | null; enabled: boolean };
export type Article = {
  id: string; account_id: string; title: string; digest: string | null;
  cover_url: string | null; url: string; content: string | null; published_at: string;
};
export type Credential = { id: string; nickname: string; avatar: string | null; status: string; expires_at: string };
export type WechatLoginStatus = {
  status: "waiting" | "scanned" | "confirmed" | "expired" | "no_account" | "no_email" | "failed";
  nickname: string | null;
};

export type WeiboCredentialStatus = {
  configured: boolean;
  status: "active" | "expired" | "blocked" | null;
  weibo_uid: string | null;
  nickname: string | null;
  avatar: string | null;
  last_verified_at: string | null;
  blocked_until: string | null;
  last_error: string | null;
  can_manage: boolean;
};
export type WeiboAccount = {
  account_id: string;
  uid: string;
  name: string;
  avatar: string | null;
  description: string | null;
  profile_url: string;
};
export type WeiboSubscription = WeiboAccount & {
  id: string;
  enabled: boolean;
  last_synced_at: string | null;
  last_sync_status: string;
  last_sync_error: string | null;
};
export type WeiboMedia = {
  type: "image" | "video";
  url: string;
  poster_url?: string | null;
};
export type WeiboPost = {
  id: string;
  account_id: string;
  account_name: string;
  external_id: string;
  content: string;
  url: string;
  media: WeiboMedia[];
  published_at: string;
  captured_at: string;
};

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) {
    const body = await r.text();
    // FastAPI 的错误体是 {"detail": "..."}，直接抛原文会把 JSON 壳子显示给用户
    let msg = body;
    try {
      const d = JSON.parse(body)?.detail;
      if (typeof d === "string") msg = d;
    } catch {
      /* 非 JSON 错误体，原文照抛 */
    }
    throw new Error(msg || `请求失败（HTTP ${r.status}）`);
  }
  return r.json() as Promise<T>;
}

export async function searchAccounts(keyword: string): Promise<WechatAccount[]> {
  return json(await apiFetch(`/api/social/wechat/search?keyword=${encodeURIComponent(keyword)}`));
}

export async function subscribe(a: { fakeid: string; name: string; avatar: string | null }): Promise<Subscription> {
  return json(await apiFetch(`/api/social/wechat/subscriptions`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(a),
  }));
}

export async function listSubscriptions(): Promise<Subscription[]> {
  return json(await apiFetch(`/api/social/wechat/subscriptions`));
}

export async function unsubscribe(id: string): Promise<void> {
  await apiFetch(`/api/social/wechat/subscriptions/${id}`, { method: "DELETE" });
}

export async function listArticles(accountId: string, limit = 20): Promise<Article[]> {
  return json(await apiFetch(`/api/social/wechat/articles?account_id=${accountId}&limit=${limit}`));
}

export async function getArticle(id: string): Promise<Article> {
  return json(await apiFetch(`/api/social/wechat/articles/${id}`));
}

export async function refreshAccount(accountId: string): Promise<{ added: number }> {
  return json(await apiFetch(`/api/social/wechat/refresh?account_id=${accountId}`, { method: "POST" }));
}

export async function startLoginQrcode(): Promise<{ login_session: string; qrcode: string }> {
  return json(await apiFetch(`/api/social/wechat/login/qrcode`, { method: "POST" }));
}

export async function pollLoginStatus(session: string): Promise<WechatLoginStatus> {
  return json(await apiFetch(`/api/social/wechat/login/status?s=${encodeURIComponent(session)}`));
}

export async function listCredentials(): Promise<Credential[]> {
  return json(await apiFetch(`/api/social/wechat/credentials`));
}

export async function getWeiboCredential(): Promise<WeiboCredentialStatus> {
  return json(await apiFetch("/api/social/weibo/credential"));
}

export async function saveWeiboCredential(cookies: string): Promise<WeiboCredentialStatus> {
  return json(await apiFetch("/api/social/weibo/credential", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cookies }),
  }));
}

export async function deleteWeiboCredential(): Promise<void> {
  await json(await apiFetch("/api/social/weibo/credential", { method: "DELETE" }));
}

export async function previewWeiboAccount(profileUrl: string): Promise<WeiboAccount> {
  return json(await apiFetch("/api/social/weibo/accounts/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile_url: profileUrl }),
  }));
}

export async function subscribeWeibo(accountId: string): Promise<{
  subscription: WeiboSubscription;
  initial_sync_status: string;
  added: number;
}> {
  return json(await apiFetch("/api/social/weibo/subscriptions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ account_id: accountId }),
  }));
}

export async function listWeiboSubscriptions(): Promise<WeiboSubscription[]> {
  return json(await apiFetch("/api/social/weibo/subscriptions"));
}

export async function unsubscribeWeibo(subscriptionId: string): Promise<void> {
  await json(await apiFetch(`/api/social/weibo/subscriptions/${subscriptionId}`, {
    method: "DELETE",
  }));
}

export async function listWeiboPosts(accountId: string, limit = 20): Promise<WeiboPost[]> {
  return json(await apiFetch(
    `/api/social/weibo/posts?account_id=${encodeURIComponent(accountId)}&limit=${limit}`,
  ));
}

export async function refreshWeiboAccount(accountId: string): Promise<{ added: number }> {
  return json(await apiFetch(
    `/api/social/weibo/refresh?account_id=${encodeURIComponent(accountId)}`,
    { method: "POST" },
  ));
}

// ---- Phase 2: 统一订阅动态 API ----

export type PublisherBrief = { id: string; name: string; avatar: string | null; platform: string };
export type SocialMedia = {
  type: "image" | "video";
  url: string;
  poster_url?: string | null;
};
export type FeedItem = {
  id: string; platform: string; external_id: string; content_type: string;
  title: string | null; digest: string | null; cover_url: string | null;
  url: string | null; published_at: string | null; publisher: PublisherBrief;
  body_text?: string | null; transcript_text?: string | null;
  media?: SocialMedia[]; duration_seconds?: number | null;
  platform_metadata?: Record<string, unknown>;
};
export type UnifiedSubscription = {
  id: string; publisher_id: string; platform: string; external_id: string;
  name: string; avatar: string | null; enabled: boolean;
};
export type PublisherSearchResult = {
  platform: string; external_id: string; name: string;
  avatar: string | null; description: string | null; provider: string;
};

export type FeedResponse = {
  items: FeedItem[];
  next_before: string | null;
};

export type SocialItemDetail = FeedItem & {
  body_text: string | null;
  transcript_text: string | null;
};

export async function getFeed(params: {
  publisher_id?: string; before?: string; limit?: number;
} = {}): Promise<FeedResponse> {
  const qs = new URLSearchParams();
  if (params.publisher_id) qs.set("publisher_id", params.publisher_id);
  if (params.before) qs.set("before", params.before);
  if (params.limit) qs.set("limit", String(params.limit));
  return json(await apiFetch(`/api/social/feed?${qs}`));
}

export async function refreshPublisher(publisherId: string): Promise<{ ok: boolean; message?: string }> {
  return json(await apiFetch(`/api/social/publishers/${encodeURIComponent(publisherId)}/refresh`, {
    method: "POST",
  }));
}

export async function listUnifiedSubscriptions(): Promise<UnifiedSubscription[]> {
  return json(await apiFetch("/api/social/subscriptions"));
}

export async function addUnifiedSubscription(data: {
  publisher_id?: string; platform?: string; external_id?: string; name?: string; avatar?: string;
}): Promise<UnifiedSubscription> {
  return json(await apiFetch("/api/social/subscriptions", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
  }));
}

export async function removeUnifiedSubscription(subId: string): Promise<void> {
  await json(await apiFetch(`/api/social/subscriptions/${encodeURIComponent(subId)}`, { method: "DELETE" }));
}

export async function searchPublishers(platform: string, q: string): Promise<PublisherSearchResult[]> {
  return json(await apiFetch(`/api/social/publishers/search?platform=${encodeURIComponent(platform)}&q=${encodeURIComponent(q)}`));
}

export async function getSocialItemDetail(itemId: string): Promise<SocialItemDetail> {
  return json(await apiFetch(`/api/social/items/${encodeURIComponent(itemId)}`));
}

// ---- Phase 4: 收藏 API ----

export type Bookmark = {
  id: string; item_id: string; platform: string; title: string | null;
  digest: string | null; cover_url: string | null; url: string | null;
  published_at: string | null; publisher: PublisherBrief; notes: string | null;
  created_at: string; body_text?: string | null; transcript_text?: string | null;
};

export async function addBookmark(itemId: string, notes?: string): Promise<{ id: string }> {
  return json(await apiFetch("/api/social/bookmarks", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item_id: itemId, ...(notes ? { notes } : {}) }),
  }));
}

export async function removeBookmark(itemId: string): Promise<void> {
  await json(await apiFetch(`/api/social/bookmarks/${encodeURIComponent(itemId)}`, { method: "DELETE" }));
}

export async function listBookmarks(limit = 50): Promise<Bookmark[]> {
  return json(await apiFetch(`/api/social/bookmarks?limit=${limit}`));
}

// ---- AIHot 金融热榜 API ----

export type AihotWindow = "24h" | "3d" | "7d";
export type AihotCategory = "macro" | "policy" | "industry" | "company" | "market";

export type CoreMetric = {
  label: string;
  value: number;
  formatted_value?: string | null;
};

export type AihotItem = {
  id: string;
  rank: number;
  previous_rank: number | null;
  rank_delta: number | null;
  trend: "new" | "up" | "down" | "flat";
  window: AihotWindow;
  category: AihotCategory | null;
  assets: string[];
  platform: string;
  content_type: string;
  title: string | null;
  digest: string | null;
  cover_url: string | null;
  url: string | null;
  published_at: string | null;
  core_metric: CoreMetric | null;
  publisher: PublisherBrief;
  bookmarked: boolean;
};

export type AihotRun = {
  id: string;
  status: string;
  finished_at: string | null;
  items_fetched: number;
  formula_version?: string;
  age_hours?: number | null;
};

export type AihotResponse = {
  items: AihotItem[];
  run: AihotRun | null;
  status: "ok" | "refreshing" | "stale_24h" | "stale_72h" | "no_data" | string;
};

export type AihotSource = {
  id: string;
  publisher_id: string | null;
  platform: string;
  external_id: string | null;
  name: string | null;
  avatar: string | null;
  category: AihotCategory;
  source_key: string | null;
  enabled: boolean;
  notes: string | null;
};

export type AihotSourceCreate = {
  platform?: "wechat" | "xiaohongshu" | "bilibili";
  external_id?: string;
  name?: string;
  avatar?: string;
  description?: string;
  category: AihotCategory;
  source_key?: string;
  notes?: string;
};

export type AihotProviderStatGroup = {
  provider: string;
  platform: string;
  operation: string;
  calls: number;
  errors: number;
  error_rate: number;
  avg_elapsed_ms: number | null;
  estimated_cost: number;
};

export type AihotProviderStats = {
  days: number;
  total_estimated_cost: number;
  budget: number;
  budget_warning: boolean;
  groups: AihotProviderStatGroup[];
};

export type RankingHistoryPoint = {
  window: AihotWindow;
  rank: number;
  previous_rank: number | null;
  rank_delta: number | null;
  platform_score: number;
  freshness_score: number;
  momentum_score: number;
  computed_at: string;
  formula_version: string;
};

export type AihotEnrichment = {
  status: string;
  summary: string | null;
  category: AihotCategory | null;
  assets: string[];
  is_financial: boolean | null;
  relevance_confidence: number | null;
  model: string;
  version: string;
};

export type AihotMetricSnapshot = {
  captured_at: string;
  view: number | null;
  like: number | null;
  comment: number | null;
  share: number | null;
  collect: number | null;
  provider_rank: number | null;
};

export type AihotItemDetail = {
  id: string;
  platform: string;
  content_type: string;
  title: string | null;
  digest: string | null;
  body_text: string | null;
  transcript_text: string | null;
  cover_url: string | null;
  url: string | null;
  published_at: string | null;
  bookmarked: boolean;
  publisher: PublisherBrief;
  enrichment: AihotEnrichment | null;
  metrics: AihotMetricSnapshot[];
  rank_history: RankingHistoryPoint[];
  media: Array<{
    type: string;
    url: string;
    thumbnail_url: string | null;
    duration_seconds: number | null;
  }>;
};

export async function getAihot(params: {
  window?: AihotWindow;
  category?: AihotCategory;
  q?: string;
  limit?: number;
} = {}): Promise<AihotResponse> {
  const qs = new URLSearchParams();
  qs.set("window", params.window ?? "24h");
  if (params.category) qs.set("category", params.category);
  if (params.q) qs.set("q", params.q);
  qs.set("limit", String(params.limit ?? 50));
  return json(await apiFetch(`/api/aihot?${qs}`));
}

export async function getAihotItemDetail(itemId: string): Promise<AihotItemDetail> {
  return json(await apiFetch(`/api/aihot/${encodeURIComponent(itemId)}`));
}

export async function refreshAihot(): Promise<{ ok?: boolean; status?: string; message?: string }> {
  return json(await apiFetch("/api/aihot/refresh", { method: "POST" }));
}

export async function listAihotSources(): Promise<AihotSource[]> {
  return json(await apiFetch("/api/aihot/sources"));
}

export async function createAihotSource(data: AihotSourceCreate): Promise<{ id: string; ok: boolean }> {
  return json(await apiFetch("/api/aihot/sources", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  }));
}

export async function updateAihotSource(
  sourceId: string,
  data: { category?: AihotCategory; source_key?: string; enabled?: boolean; notes?: string },
): Promise<{ ok: boolean }> {
  return json(await apiFetch(`/api/aihot/sources/${encodeURIComponent(sourceId)}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  }));
}

export async function deleteAihotSource(sourceId: string): Promise<{ ok: boolean }> {
  return json(await apiFetch(`/api/aihot/sources/${encodeURIComponent(sourceId)}`, {
    method: "DELETE",
  }));
}

export async function getAihotProviderStats(days = 30): Promise<AihotProviderStats> {
  return json(await apiFetch(`/api/aihot/provider-stats?days=${days}`));
}
