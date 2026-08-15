import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from "react";
import { Bookmark, Plus, RefreshCw, Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  type FeedItem,
  type Bookmark as SocialBookmark,
  type PublisherSearchResult,
  type UnifiedSubscription,
  addBookmark,
  addUnifiedSubscription,
  getFeed,
  getSocialItemDetail,
  listBookmarks,
  listUnifiedSubscriptions,
  refreshPublisher,
  removeBookmark,
  removeUnifiedSubscription,
  searchPublishers,
} from "@/lib/social";
import type { ChatContentAction } from "./ContentDetailDrawer";
import { WechatFallbackEntry, WeiboProfileEntry } from "./SourceOnboarding";

const ContentDetailDrawer = lazy(() => import("./ContentDetailDrawer"));

const PLATFORMS = [
  { key: "wechat", label: "公众号", searchable: true },
  { key: "xiaohongshu", label: "小红书", searchable: true },
  { key: "bilibili", label: "B站", searchable: true },
  { key: "weibo", label: "微博", searchable: false },
] as const;

const PLATFORM_LABELS: Record<string, string> = Object.fromEntries(
  PLATFORMS.map(({ key, label }) => [key, label]),
);

const SYNC_STATE_LABELS: Record<string, string> = {
  ok: "已同步",
  queued: "已排队",
  waiting_capacity: "等待容量",
  resolving_identity: "正在识别账号",
  identity_unresolved: "未找到账号",
  identity_ambiguous: "账号重名待确认",
  rate_limited: "平台冷却中",
  credential_unavailable: "平台凭证暂不可用",
  upstream_error: "上游暂不可用",
};

type UnifiedFeedProps = {
  canManageCredentials?: boolean;
  onSendToChat?: ChatContentAction;
  onDeepAnalysis?: ChatContentAction;
};

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function bookmarkAsFeedItem(bookmark: SocialBookmark): FeedItem {
  return {
    id: bookmark.item_id,
    platform: bookmark.platform,
    external_id: bookmark.item_id,
    content_type: "article",
    title: bookmark.title,
    body_text: bookmark.body_text,
    transcript_text: bookmark.transcript_text,
    digest: bookmark.digest,
    cover_url: bookmark.cover_url,
    url: bookmark.url,
    published_at: bookmark.published_at,
    publisher: bookmark.publisher,
  };
}

export default function UnifiedFeed({
  canManageCredentials = false,
  onSendToChat,
  onDeepAnalysis,
}: UnifiedFeedProps) {
  const [items, setItems] = useState<FeedItem[]>([]);
  const [subs, setSubs] = useState<UnifiedSubscription[]>([]);
  const [bookmarks, setBookmarks] = useState<SocialBookmark[]>([]);
  const [bookmarkedIds, setBookmarkedIds] = useState<Set<string>>(new Set());
  const [view, setView] = useState<"feed" | "bookmarks">("feed");
  const [searchPlatform, setSearchPlatform] = useState("wechat");
  const [searchQuery, setSearchQuery] = useState("");
  const [subscriptionQuery, setSubscriptionQuery] = useState("");
  const [searchResults, setSearchResults] = useState<PublisherSearchResult[]>([]);
  const [selectedPublisher, setSelectedPublisher] = useState<string | null>(null);
  const [selectedItem, setSelectedItem] = useState<FeedItem | null>(null);
  const [nextBefore, setNextBefore] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [loadingBookmarks, setLoadingBookmarks] = useState(false);
  const [searching, setSearching] = useState(false);
  const [refreshingPublisher, setRefreshingPublisher] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  const loadFeed = useCallback(async (publisherId: string | null) => {
    setLoading(true);
    setError("");
    try {
      const response = await getFeed({ publisher_id: publisherId ?? undefined, limit: 50 });
      setItems(response.items);
      setNextBefore(response.next_before);
    } catch (loadError) {
      setError(errorMessage(loadError, "订阅动态加载失败"));
    } finally {
      setLoading(false);
    }
  }, []);

  async function loadMore() {
    if (!nextBefore || loadingMore) return;
    setLoadingMore(true);
    setError("");
    try {
      const response = await getFeed({
        publisher_id: selectedPublisher ?? undefined,
        before: nextBefore,
        limit: 50,
      });
      setItems((current) => {
        const merged = new Map(current.map((item) => [item.id, item]));
        response.items.forEach((item) => merged.set(item.id, item));
        return Array.from(merged.values());
      });
      setNextBefore(response.next_before);
    } catch (loadError) {
      setError(errorMessage(loadError, "更多动态加载失败"));
    } finally {
      setLoadingMore(false);
    }
  }

  const loadSubscriptions = useCallback(async () => {
    try {
      setSubs(await listUnifiedSubscriptions());
    } catch (loadError) {
      setError(errorMessage(loadError, "订阅列表加载失败"));
    }
  }, []);

  const loadBookmarks = useCallback(async () => {
    setLoadingBookmarks(true);
    try {
      const rows = await listBookmarks(200);
      setBookmarks(rows);
      setBookmarkedIds(new Set(rows.map((bookmark) => bookmark.item_id)));
    } catch (loadError) {
      setError(errorMessage(loadError, "收藏状态加载失败"));
    } finally {
      setLoadingBookmarks(false);
    }
  }, []);

  useEffect(() => {
    void loadFeed(selectedPublisher);
  }, [loadFeed, selectedPublisher]);

  useEffect(() => {
    void loadSubscriptions();
    void loadBookmarks();
  }, [loadBookmarks, loadSubscriptions]);

  const visibleSubscriptions = useMemo(() => {
    const query = subscriptionQuery.trim().toLocaleLowerCase();
    if (!query) return subs;
    return subs.filter((subscription) => subscription.name.toLocaleLowerCase().includes(query));
  }, [subs, subscriptionQuery]);
  const selectedPlatformConfig = PLATFORMS.find(({ key }) => key === searchPlatform) ?? PLATFORMS[0];
  const bookmarkItems = useMemo(() => bookmarks.map(bookmarkAsFeedItem), [bookmarks]);
  const displayedItems = view === "bookmarks" ? bookmarkItems : items;

  const reloadAfterLegacyIntegration = useCallback(async () => {
    await Promise.all([loadSubscriptions(), loadFeed(selectedPublisher)]);
  }, [loadFeed, loadSubscriptions, selectedPublisher]);

  async function onSearch() {
    const query = searchQuery.trim();
    if (!query) return;
    setSearching(true);
    setError("");
    try {
      setSearchResults(await searchPublishers(searchPlatform, query));
    } catch (searchError) {
      setError(errorMessage(searchError, "发布者搜索失败"));
    } finally {
      setSearching(false);
    }
  }

  async function onSubscribe(publisher: PublisherSearchResult) {
    setError("");
    try {
      await addUnifiedSubscription({
        platform: publisher.platform,
        external_id: publisher.external_id,
        name: publisher.name,
        avatar: publisher.avatar ?? undefined,
        provider: publisher.provider,
      });
      setSearchResults([]);
      setSearchQuery("");
      await loadSubscriptions();
      await loadFeed(selectedPublisher);
    } catch (subscribeError) {
      setError(errorMessage(subscribeError, "订阅失败"));
    }
  }

  async function onUnsubscribe(subscription: UnifiedSubscription) {
    setError("");
    try {
      await removeUnifiedSubscription(subscription.id);
      setItems((current) => current.filter(
        (item) => item.publisher.id !== subscription.publisher_id,
      ));
      if (selectedPublisher === subscription.publisher_id) {
        setSelectedPublisher(null);
      } else {
        await loadFeed(selectedPublisher);
      }
      await loadSubscriptions();
    } catch (unsubscribeError) {
      setError(errorMessage(unsubscribeError, "取消订阅失败"));
    }
  }

  async function onRefresh(publisherId: string) {
    setError("");
    setRefreshingPublisher(publisherId);
    try {
      const queued = await refreshPublisher(publisherId);
      setNotice(
        queued.state === "waiting_capacity"
          ? "当前补缺容量已满，账号会按排队时间自动晋升"
          : "已加入刷新队列，不会在当前页面直接访问上游",
      );
      await loadSubscriptions();
    } catch (refreshError) {
      setError(errorMessage(refreshError, "刷新失败"));
    } finally {
      setRefreshingPublisher(null);
    }
  }

  async function onToggleBookmark(itemId: string) {
    const wasBookmarked = bookmarkedIds.has(itemId);
    if (wasBookmarked) {
      await removeBookmark(itemId);
      setBookmarks((current) => current.filter((bookmark) => bookmark.item_id !== itemId));
    } else {
      await addBookmark(itemId);
      await loadBookmarks();
    }
    setBookmarkedIds((current) => {
      const next = new Set(current);
      if (wasBookmarked) next.delete(itemId);
      else next.add(itemId);
      return next;
    });
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="border-b px-3 py-3 sm:px-5">
        <div className="mb-3 flex items-center gap-1" aria-label="社媒视图">
          <Button
            type="button"
            variant={view === "feed" ? "secondary" : "ghost"}
            size="sm"
            aria-pressed={view === "feed"}
            onClick={() => setView("feed")}
          >
            订阅动态
          </Button>
          <Button
            type="button"
            variant={view === "bookmarks" ? "secondary" : "ghost"}
            size="sm"
            aria-pressed={view === "bookmarks"}
            onClick={() => setView("bookmarks")}
          >
            <Bookmark />收藏历史 <span className="nums">{bookmarks.length}</span>
          </Button>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <div className="flex items-center gap-2">
            <select
              aria-label="选择平台"
              value={searchPlatform}
              onChange={(event) => {
                setSearchPlatform(event.target.value);
                setSearchResults([]);
                setSearchQuery("");
              }}
              className="h-8 rounded-md border bg-background px-2 text-sm"
            >
              {PLATFORMS.map((platform) => (
                <option key={platform.key} value={platform.key}>{platform.label}</option>
              ))}
            </select>
            <Input
              value={searchQuery}
              onChange={(event) => setSearchQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") void onSearch();
              }}
              placeholder={selectedPlatformConfig.searchable ? "搜索并添加发布者…" : "该平台暂不支持账号搜索"}
              disabled={!selectedPlatformConfig.searchable}
              className="h-8 min-w-0 flex-1 sm:w-72"
            />
          </div>
          <Button type="button" variant="outline" size="sm" disabled={!selectedPlatformConfig.searchable || searching || !searchQuery.trim()} onClick={() => void onSearch()}>
            <Search />{searching ? "搜索中…" : "搜索"}
          </Button>
        </div>

        {searchResults.length > 0 && (
          <ul className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {searchResults.map((publisher) => (
              <li key={`${publisher.platform}-${publisher.external_id}`} className="flex min-w-0 items-center gap-2 rounded-md border bg-card p-2">
                {publisher.avatar ? (
                  <img src={publisher.avatar} alt="" className="size-8 rounded-md object-cover" />
                ) : (
                  <span className="flex size-8 shrink-0 items-center justify-center rounded-md bg-muted text-xs">
                    {publisher.name.slice(0, 1)}
                  </span>
                )}
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-medium">{publisher.name}</p>
                  <p className="truncate text-xs text-muted-foreground">{PLATFORM_LABELS[publisher.platform] ?? publisher.platform}</p>
                </div>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={publisher.platform === "xiaohongshu"}
                  title={publisher.platform === "xiaohongshu" ? "小红书暂无账号作品列表能力，不能伪装成账号订阅" : undefined}
                  onClick={() => void onSubscribe(publisher)}
                >
                  <Plus />{publisher.platform === "xiaohongshu" ? "仅搜索发现" : "订阅"}
                </Button>
              </li>
            ))}
          </ul>
        )}
        {searchPlatform === "xiaohongshu" && (
          <p className="mt-2 text-xs text-muted-foreground">小红书目前仅支持关键词搜索发现，不支持订阅特定账号的全部作品。</p>
        )}
        {searchPlatform === "weibo" && (
          <WeiboProfileEntry onIntegrated={reloadAfterLegacyIntegration} onError={setError} />
        )}
        {canManageCredentials && searchPlatform === "wechat" && (
          <WechatFallbackEntry onIntegrated={reloadAfterLegacyIntegration} onError={setError} />
        )}
      </div>

      {notice && (
        <div role="status" className="border-b border-emerald-500/30 bg-emerald-500/10 px-4 py-2 text-xs text-emerald-700">
          {notice}
        </div>
      )}
      {error && (
        <div role="alert" className="border-b border-destructive/30 bg-destructive/10 px-4 py-2 text-xs text-destructive">
          {error}
        </div>
      )}

      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        <aside className="shrink-0 border-b p-2 md:w-56 md:overflow-y-auto md:border-r md:border-b-0">
          <div className="mb-2 flex items-center justify-between px-1">
            <span className="text-xs font-medium text-muted-foreground">我的订阅</span>
            <span className="nums text-[10px] text-muted-foreground">{subs.length}</span>
          </div>
          <Input
            aria-label="筛选已订阅账号"
            value={subscriptionQuery}
            onChange={(event) => setSubscriptionQuery(event.target.value)}
            placeholder="筛选账号…"
            className="mb-2 h-7 text-xs"
          />
          <div className="flex gap-1 overflow-x-auto pb-1 md:block md:space-y-1 md:overflow-visible">
            <button
              type="button"
              onClick={() => {
                setView("feed");
                setSelectedPublisher(null);
              }}
              className={`shrink-0 rounded-md px-2 py-1.5 text-left text-sm md:w-full ${
                selectedPublisher === null ? "bg-accent font-medium" : "hover:bg-accent/50"
              }`}
            >
              全部
            </button>
            {visibleSubscriptions.map((subscription) => {
              const selected = selectedPublisher === subscription.publisher_id;
              return (
                <div key={subscription.id} className="group flex shrink-0 items-center rounded-md md:w-full">
                  <button
                    type="button"
                    aria-pressed={selected}
                    onClick={() => {
                      setView("feed");
                      setSelectedPublisher(selected ? null : subscription.publisher_id);
                    }}
                    className={`min-w-28 flex-1 rounded-md px-2 py-1.5 text-left text-sm md:min-w-0 ${
                      selected ? "bg-accent font-medium" : "hover:bg-accent/50"
                    }`}
                  >
                    <span className="block truncate">{subscription.name}</span>
                    <span className="text-[10px] text-muted-foreground">
                      {PLATFORM_LABELS[subscription.platform] ?? subscription.platform}
                    </span>
                    <span className="block truncate text-[10px] text-muted-foreground" title={subscription.last_sync_error ?? undefined}>
                      {SYNC_STATE_LABELS[subscription.sync_state] ?? subscription.sync_state}
                      {subscription.sync_provider ? ` · ${subscription.sync_provider}` : ""}
                    </span>
                  </button>
                  <button
                    type="button"
                    aria-label={`取消订阅 ${subscription.name}`}
                    onClick={() => void onUnsubscribe(subscription)}
                    className="p-1 text-muted-foreground hover:text-destructive"
                  >
                    <X className="size-3" />
                  </button>
                </div>
              );
            })}
          </div>
        </aside>

        <main className="min-h-0 flex-1 overflow-y-auto p-3 sm:p-5">
          {view === "bookmarks" && (
            <div className="mb-3 rounded-md bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
              收藏正文会长期保留；可打开详情、取消收藏、发送到对话或发起深度分析。
            </div>
          )}
          {view === "feed" && selectedPublisher && (
            <div className="mb-3 flex items-center justify-between rounded-md bg-muted/50 px-3 py-2 text-xs">
              <span>仅显示当前账号，点击左侧账号可取消筛选</span>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                disabled={refreshingPublisher === selectedPublisher}
                onClick={() => void onRefresh(selectedPublisher)}
              >
                <RefreshCw className={refreshingPublisher === selectedPublisher ? "animate-spin" : ""} />
                刷新账号
              </Button>
            </div>
          )}

          {(view === "feed" ? loading : loadingBookmarks) ? (
            <p className="py-12 text-center text-sm text-muted-foreground">加载中…</p>
          ) : displayedItems.length === 0 ? (
            <p className="py-12 text-center text-sm text-muted-foreground">
              {view === "bookmarks"
                ? "还没有收藏内容"
                : subs.length === 0 ? "还没有订阅，先在上方搜索发布者" : "暂无订阅动态"}
            </p>
          ) : (
            <div className="space-y-3">
              {displayedItems.map((item) => (
                <FeedCard
                  key={item.id}
                  item={item}
                  bookmarked={bookmarkedIds.has(item.id)}
                  onOpen={() => setSelectedItem(item)}
                  onToggleBookmark={async () => {
                    try {
                      await onToggleBookmark(item.id);
                    } catch (bookmarkError) {
                      setError(errorMessage(bookmarkError, "收藏操作失败"));
                    }
                  }}
                />
              ))}
              {view === "feed" && nextBefore && (
                <div className="flex justify-center pt-2">
                  <Button
                    type="button"
                    variant="outline"
                    disabled={loadingMore}
                    onClick={() => void loadMore()}
                  >
                    {loadingMore ? "加载中…" : "加载更多"}
                  </Button>
                </div>
              )}
            </div>
          )}
        </main>
      </div>

      <Suspense fallback={null}>
        <ContentDetailDrawer
          item={selectedItem}
          loadDetail={getSocialItemDetail}
          bookmarked={selectedItem ? bookmarkedIds.has(selectedItem.id) : false}
          onClose={() => setSelectedItem(null)}
          onToggleBookmark={onToggleBookmark}
          onSendToChat={onSendToChat}
          onDeepAnalysis={onDeepAnalysis}
        />
      </Suspense>
    </div>
  );
}

function FeedCard({
  item,
  bookmarked,
  onOpen,
  onToggleBookmark,
}: {
  item: FeedItem;
  bookmarked: boolean;
  onOpen: () => void;
  onToggleBookmark: () => Promise<void>;
}) {
  return (
    <article className="rounded-lg border bg-card p-3 transition-colors hover:bg-accent/30">
      <button type="button" className="flex w-full items-start gap-3 text-left" onClick={onOpen}>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded bg-muted px-1.5 py-0.5 text-xs">{PLATFORM_LABELS[item.platform] ?? item.platform}</span>
            <span className="truncate text-xs text-muted-foreground">{item.publisher.name}</span>
          </div>
          <h3 className="mt-1 line-clamp-2 text-sm font-medium leading-snug">{item.title ?? "无标题"}</h3>
          {item.digest && <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">{item.digest}</p>}
          {item.published_at && (
            <p className="nums mt-2 text-[11px] text-muted-foreground">
              {new Date(item.published_at).toLocaleString("zh-CN")}
            </p>
          )}
        </div>
        {item.cover_url && <img src={item.cover_url} alt="" className="size-16 shrink-0 rounded-md border object-cover sm:size-20" />}
      </button>
      <div className="mt-2 flex items-center justify-end">
        <Button type="button" variant="ghost" size="sm" onClick={() => void onToggleBookmark()}>
          <Bookmark className={bookmarked ? "fill-current" : ""} />
          {bookmarked ? "已收藏" : "收藏"}
        </Button>
      </div>
    </article>
  );
}
