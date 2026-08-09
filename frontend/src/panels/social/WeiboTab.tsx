import { useEffect, useState } from "react";
import { ExternalLink, RefreshCw, Trash2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  type WeiboAccount,
  type WeiboCredentialStatus,
  type WeiboPost,
  type WeiboSubscription,
  deleteWeiboCredential,
  getWeiboCredential,
  listWeiboPosts,
  listWeiboSubscriptions,
  previewWeiboAccount,
  refreshWeiboAccount,
  saveWeiboCredential,
  subscribeWeibo,
  unsubscribeWeibo,
} from "@/lib/social";

function statusMessage(credential: WeiboCredentialStatus | null): string {
  if (!credential?.configured) return "尚未配置专用微博账号 Cookie";
  if (credential.status === "active") return `登录有效${credential.nickname ? `：${credential.nickname}` : ""}`;
  if (credential.status === "blocked") {
    const until = credential.blocked_until
      ? `，预计 ${new Date(credential.blocked_until).toLocaleString()} 后恢复`
      : "";
    return `微博触发风控，自动同步已暂停${until}`;
  }
  return "微博登录已过期，请管理员重新配置 Cookie";
}

function syncStatusMessage(subscription: WeiboSubscription): string {
  if (subscription.last_sync_status === "error") {
    return subscription.last_sync_error
      ? `最近同步失败：${subscription.last_sync_error}`
      : "最近同步失败，请稍后重试";
  }
  if (subscription.last_sync_status === "ok" && subscription.last_synced_at) {
    return `最近同步：${new Date(subscription.last_synced_at).toLocaleString()}`;
  }
  return "等待首次同步";
}

export default function WeiboTab() {
  const [credential, setCredential] = useState<WeiboCredentialStatus | null>(null);
  const [cookies, setCookies] = useState("");
  const [profileUrl, setProfileUrl] = useState("");
  const [preview, setPreview] = useState<WeiboAccount | null>(null);
  const [subscriptions, setSubscriptions] = useState<WeiboSubscription[]>([]);
  const [activeAccountId, setActiveAccountId] = useState<string | null>(null);
  const [posts, setPosts] = useState<WeiboPost[]>([]);
  const [reading, setReading] = useState<WeiboPost | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const activeSubscription = subscriptions.find((item) => item.account_id === activeAccountId);

  async function reload() {
    const [credentialStatus, rows] = await Promise.all([
      getWeiboCredential(),
      listWeiboSubscriptions(),
    ]);
    setCredential(credentialStatus);
    setSubscriptions(rows);
  }

  useEffect(() => {
    reload().catch((cause) => setError(String(cause)));
  }, []);

  async function saveCredential() {
    if (!cookies.trim()) return;
    setBusy(true);
    setError("");
    try {
      setCredential(await saveWeiboCredential(cookies));
      setCookies("");
      setMessage("微博 Cookie 已验证并加密保存");
    } catch (cause) {
      setError(String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function removeCredential() {
    setBusy(true);
    try {
      await deleteWeiboCredential();
      setCredential(await getWeiboCredential());
      setMessage("微博凭证已停用，历史快照仍会保留");
    } catch (cause) {
      setError(String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function previewAccount() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      setPreview(await previewWeiboAccount(profileUrl));
    } catch (cause) {
      setError(String(cause));
      setPreview(null);
    } finally {
      setBusy(false);
    }
  }

  async function confirmSubscription() {
    if (!preview) return;
    setBusy(true);
    try {
      const result = await subscribeWeibo(preview.account_id);
      setSubscriptions(await listWeiboSubscriptions());
      setPreview(null);
      setProfileUrl("");
      setMessage(result.initial_sync_status === "cooldown"
        ? "订阅成功；当前处于风控冷却，首次同步将在冷却结束后自动进行"
        : `订阅成功，首次获取 ${result.added} 条原创微博`);
      await openAccount(result.subscription.account_id);
    } catch (cause) {
      setError(String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function openAccount(accountId: string) {
    setActiveAccountId(accountId);
    setReading(null);
    try {
      setPosts(await listWeiboPosts(accountId));
    } catch (cause) {
      setError(String(cause));
    }
  }

  async function refreshAccount() {
    if (!activeAccountId) return;
    setBusy(true);
    setError("");
    try {
      const result = await refreshWeiboAccount(activeAccountId);
      setPosts(await listWeiboPosts(activeAccountId));
      setSubscriptions(await listWeiboSubscriptions());
      setMessage(`刷新完成，新增 ${result.added} 条`);
    } catch (cause) {
      setError(String(cause));
    } finally {
      setBusy(false);
    }
  }

  async function removeSubscription(item: WeiboSubscription) {
    try {
      await unsubscribeWeibo(item.id);
      const rows = await listWeiboSubscriptions();
      setSubscriptions(rows);
      if (activeAccountId === item.account_id) {
        setActiveAccountId(null);
        setPosts([]);
        setReading(null);
      }
    } catch (cause) {
      setError(String(cause));
    }
  }

  return (
    <div className="flex min-h-0 flex-1">
      <aside className="flex w-72 shrink-0 flex-col border-r">
        <div className="border-b p-3">
          <div className="mb-2 text-sm font-medium">添加微博账号</div>
          <Input
            value={profileUrl}
            onChange={(event) => setProfileUrl(event.target.value)}
            placeholder="粘贴微博主页链接"
            className="h-8 text-sm"
          />
          <Button
            type="button"
            size="sm"
            variant="outline"
            className="mt-2 w-full"
            disabled={busy || !profileUrl.trim() || subscriptions.length >= 20}
            onClick={previewAccount}
          >
            预览账号
          </Button>
          {subscriptions.length >= 20 && (
            <p className="mt-2 text-xs text-amber-600">当前实例已达到 20 个账号上限</p>
          )}
          {preview && (
            <div className="mt-3 rounded-md border p-2" data-testid="weibo-preview">
              <div className="flex items-center gap-2">
                {preview.avatar && <img src={preview.avatar} alt="" className="h-9 w-9 rounded-full" />}
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{preview.name}</div>
                  <div className="text-xs text-muted-foreground">UID {preview.uid}</div>
                </div>
              </div>
              {preview.description && <p className="mt-2 text-xs text-muted-foreground">{preview.description}</p>}
              <Button type="button" size="sm" className="mt-2 w-full" disabled={busy} onClick={confirmSubscription}>
                确认订阅
              </Button>
            </div>
          )}
        </div>

        <nav className="min-h-0 flex-1 overflow-y-auto p-2" aria-label="微博订阅">
          {subscriptions.length === 0 ? (
            <p className="px-2 py-6 text-center text-xs text-muted-foreground">还没有订阅微博账号</p>
          ) : (
            <ul className="space-y-1">
              {subscriptions.map((item) => (
                <li key={item.id} className="group flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => openAccount(item.account_id)}
                    className={`flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm ${
                      activeAccountId === item.account_id ? "bg-accent font-medium" : "hover:bg-accent/50"
                    }`}
                  >
                    {item.avatar ? (
                      <img src={item.avatar} alt="" className="h-6 w-6 rounded-full object-cover" />
                    ) : (
                      <span className="flex h-6 w-6 items-center justify-center rounded-full bg-muted text-xs">{item.name[0]}</span>
                    )}
                    <span className="truncate">{item.name}</span>
                  </button>
                  <button type="button" aria-label={`取消订阅 ${item.name}`} onClick={() => removeSubscription(item)}>
                    <Trash2 className="h-3.5 w-3.5 text-muted-foreground" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </nav>

        <div className="border-t p-3">
          <div className="mb-1 text-xs font-medium text-muted-foreground">专用微博账号</div>
          <p className={`text-xs ${credential?.status === "active" ? "text-green-600" : "text-amber-600"}`}>
            {statusMessage(credential)}
          </p>
          {credential?.last_error && <p className="mt-1 text-xs text-red-500">{credential.last_error}</p>}
          {credential?.can_manage ? (
            <div className="mt-2 space-y-2">
              <Input
                type="password"
                value={cookies}
                onChange={(event) => setCookies(event.target.value)}
                placeholder="粘贴 D-sight 专用账号 Cookie"
                aria-label="微博 Cookie"
                className="text-xs"
              />
              <div className="flex gap-2">
                <Button type="button" size="sm" className="flex-1" disabled={busy || !cookies.trim()} onClick={saveCredential}>
                  验证并保存
                </Button>
                {credential.configured && (
                  <Button type="button" size="sm" variant="outline" disabled={busy} onClick={removeCredential}>
                    停用
                  </Button>
                )}
              </div>
            </div>
          ) : (
            <p className="mt-2 text-xs text-muted-foreground">请联系管理员配置或更新微博 Cookie</p>
          )}
        </div>
      </aside>

      <section className={`flex min-h-0 flex-col ${reading ? "w-96 shrink-0 border-r" : "min-w-0 flex-1"}`}>
        <div className="flex min-h-11 items-center justify-between border-b px-4 py-2">
          <div className="min-w-0">
            <div className="truncate text-sm font-medium">{activeSubscription?.name ?? "原创微博"}</div>
            {activeSubscription && (
              <div className={`truncate text-xs ${activeSubscription.last_sync_status === "error" ? "text-red-500" : "text-muted-foreground"}`}>
                {syncStatusMessage(activeSubscription)}
              </div>
            )}
          </div>
          {activeAccountId && (
            <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={refreshAccount}>
              <RefreshCw className={`mr-1 h-3.5 w-3.5 ${busy ? "animate-spin" : ""}`} />刷新
            </Button>
          )}
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-3">
          {!activeAccountId ? (
            <p className="py-12 text-center text-sm text-muted-foreground">在左侧选择一个微博账号</p>
          ) : posts.length === 0 ? (
            <p className="py-12 text-center text-sm text-muted-foreground">暂无原创微博快照</p>
          ) : (
            <ul className="space-y-2">
              {posts.map((post) => (
                <li key={post.id}>
                  <button type="button" className="w-full rounded-lg border p-3 text-left hover:bg-accent/50" onClick={() => setReading(post)}>
                    <p className="line-clamp-4 whitespace-pre-wrap text-sm leading-6">{post.content}</p>
                    {post.media.some((media) => media.type === "image") && (
                      <div className="mt-2 flex gap-1 overflow-hidden">
                        {post.media.filter((media) => media.type === "image").slice(0, 3).map((media) => (
                          <img key={media.url} src={media.url} alt="微博图片" className="h-16 w-16 rounded object-cover" referrerPolicy="no-referrer" />
                        ))}
                      </div>
                    )}
                    <time className="mt-2 block text-xs text-muted-foreground">{new Date(post.published_at).toLocaleString()}</time>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
        {(message || error) && (
          <p role={error ? "alert" : "status"} className={`border-t px-3 py-2 text-xs ${error ? "text-red-500" : "text-muted-foreground"}`}>
            {error || message}
          </p>
        )}
      </section>

      {reading && (
        <section className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="flex h-11 items-center justify-between border-b px-4">
            <span className="text-sm font-medium">{reading.account_name}</span>
            <div className="flex items-center gap-2">
              <a href={reading.url} target="_blank" rel="noreferrer" className="flex items-center gap-1 text-xs text-primary">
                原文链接 <ExternalLink className="h-3 w-3" />
              </a>
              <Button type="button" variant="ghost" size="icon" className="h-7 w-7" aria-label="关闭微博详情" onClick={() => setReading(null)}>
                <X className="h-4 w-4" />
              </Button>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
            <time className="text-xs text-muted-foreground">{new Date(reading.published_at).toLocaleString()}</time>
            <p className="mt-3 whitespace-pre-wrap text-sm leading-7">{reading.content}</p>
            <div className="mt-4 grid grid-cols-2 gap-2">
              {reading.media.map((media) => media.type === "image" ? (
                <a key={media.url} href={media.url} target="_blank" rel="noreferrer">
                  <img src={media.url} alt="微博图片" className="w-full rounded-md border" referrerPolicy="no-referrer" />
                </a>
              ) : (
                <a key={media.url} href={media.url} target="_blank" rel="noreferrer" className="rounded-md border p-3 text-sm text-primary">
                  查看视频链接
                </a>
              ))}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}
