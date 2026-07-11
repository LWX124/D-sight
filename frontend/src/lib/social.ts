import { apiFetch } from "./api";

export type WechatAccount = { fakeid: string; nickname: string; avatar: string | null; signature: string | null };
export type Subscription = { id: string; account_id: string; fakeid: string; name: string; avatar: string | null; enabled: boolean };
export type Article = {
  id: string; account_id: string; title: string; digest: string | null;
  cover_url: string | null; url: string; content: string | null; published_at: string;
};
export type Credential = { id: string; nickname: string; avatar: string | null; status: string; expires_at: string };

async function json<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(await r.text());
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

export async function pollLoginStatus(session: string): Promise<{ status: string; nickname: string | null }> {
  return json(await apiFetch(`/api/social/wechat/login/status?s=${encodeURIComponent(session)}`));
}

export async function listCredentials(): Promise<Credential[]> {
  return json(await apiFetch(`/api/social/wechat/credentials`));
}
