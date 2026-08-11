import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Bookmark, RefreshCw, Search, Settings2, TrendingDown, TrendingUp } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  type AihotCategory,
  type AihotItem,
  type AihotResponse,
  type AihotWindow,
  addBookmark,
  getAihot,
  getAihotItemDetail,
  refreshAihot,
  removeBookmark,
} from "@/lib/social";
import type { ChatContentAction } from "./ContentDetailDrawer";

const ContentDetailDrawer = lazy(() => import("./ContentDetailDrawer"));
const AihotAdminPanel = lazy(() => import("./AihotAdminPanel"));

const WINDOWS: { key: AihotWindow; label: string }[] = [
  { key: "24h", label: "24小时" },
  { key: "3d", label: "3天" },
  { key: "7d", label: "7天" },
];

const CATEGORIES: { key: AihotCategory | ""; label: string }[] = [
  { key: "", label: "全部" },
  { key: "macro", label: "宏观" },
  { key: "policy", label: "政策" },
  { key: "industry", label: "行业" },
  { key: "company", label: "公司" },
  { key: "market", label: "市场" },
];

const CATEGORY_LABELS: Record<string, string> = Object.fromEntries(
  CATEGORIES.filter(({ key }) => key).map(({ key, label }) => [key, label]),
);

const PLATFORM_LABELS: Record<string, string> = {
  wechat: "公众号",
  xiaohongshu: "小红书",
  bilibili: "B站",
  weibo: "微博",
};

type AihotPanelProps = {
  canRefresh?: boolean;
  onSendToChat?: ChatContentAction;
  onDeepAnalysis?: ChatContentAction;
};

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export default function AihotPanel({ canRefresh = false, onSendToChat, onDeepAnalysis }: AihotPanelProps) {
  const [data, setData] = useState<AihotResponse | null>(null);
  const [window, setWindow] = useState<AihotWindow>("24h");
  const [category, setCategory] = useState<AihotCategory | "">("");
  const [searchDraft, setSearchDraft] = useState("");
  const [query, setQuery] = useState("");
  const [selectedItem, setSelectedItem] = useState<AihotItem | null>(null);
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshNotice, setRefreshNotice] = useState("");
  const [error, setError] = useState("");
  const [showAdmin, setShowAdmin] = useState(false);
  const adminVisible = canRefresh && showAdmin;

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await getAihot({
        window,
        category: category || undefined,
        q: query || undefined,
        limit: 50,
      }));
    } catch (loadError) {
      setError(errorMessage(loadError, "AIHot 加载失败"));
    } finally {
      setLoading(false);
    }
  }, [category, query, window]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onRefresh() {
    setError("");
    setRefreshNotice("");
    setRefreshing(true);
    try {
      const result = await refreshAihot();
      await load();
      if (result.status === "accepted") {
        setRefreshNotice("刷新任务已受理，采集完成前继续展示最近一次成功快照。");
      }
    } catch (refreshError) {
      setError(errorMessage(refreshError, "刷新 AIHot 失败"));
    } finally {
      setRefreshing(false);
    }
  }

  async function onToggleBookmark(itemId: string) {
    const item = data?.items.find((candidate) => candidate.id === itemId);
    const wasBookmarked = Boolean(item?.bookmarked);
    if (wasBookmarked) await removeBookmark(itemId);
    else await addBookmark(itemId);
    setData((current) => current ? {
      ...current,
      items: current.items.map((candidate) => (
        candidate.id === itemId ? { ...candidate, bookmarked: !wasBookmarked } : candidate
      )),
    } : current);
    setSelectedItem((current) => current?.id === itemId
      ? { ...current, bookmarked: !wasBookmarked }
      : current);
  }

  const status = getStatusMessage(data);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="shrink-0 border-b px-3 py-3 sm:px-5">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <div>
            <div className="flex items-baseline gap-2">
              <h2 className="font-heading text-base font-semibold">AIHot</h2>
              <span className="text-xs text-muted-foreground">金融热榜</span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              跨平台金融内容热度与趋势，不按平台分榜
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <div className="flex rounded-md border bg-muted/30 p-0.5">
              {WINDOWS.map((option) => (
                <button
                  key={option.key}
                  type="button"
                  aria-pressed={window === option.key}
                  onClick={() => setWindow(option.key)}
                  className={`rounded px-2.5 py-1 text-xs ${
                    window === option.key ? "bg-background font-medium text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
            {canRefresh && (
              <>
                <Button
                  type="button"
                  variant={adminVisible ? "secondary" : "outline"}
                  size="sm"
                  aria-pressed={showAdmin}
                  onClick={() => setShowAdmin((current) => !current)}
                >
                  <Settings2 />管理信源
                </Button>
                {!adminVisible && (
                  <Button type="button" variant="outline" size="sm" disabled={refreshing} onClick={() => void onRefresh()}>
                    <RefreshCw className={refreshing ? "animate-spin" : ""} />
                    {refreshing ? "刷新中…" : "刷新"}
                  </Button>
                )}
              </>
            )}
          </div>
        </div>

        {!adminVisible && <div className="mt-3 flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex gap-1 overflow-x-auto pb-1 lg:pb-0">
            {CATEGORIES.map((option) => (
              <button
                key={option.key || "all"}
                type="button"
                aria-pressed={category === option.key}
                onClick={() => setCategory(option.key)}
                className={`shrink-0 rounded-full border px-3 py-1 text-xs ${
                  category === option.key
                    ? "border-primary/40 bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-accent hover:text-foreground"
                }`}
              >
                {option.label}
              </button>
            ))}
          </div>
          <form
            className="flex w-full gap-2 lg:max-w-sm"
            onSubmit={(event) => {
              event.preventDefault();
              setQuery(searchDraft.trim());
            }}
          >
            <Input
              aria-label="搜索 AIHot"
              value={searchDraft}
              onChange={(event) => setSearchDraft(event.target.value)}
              placeholder="搜索标题、作者、股票或资产…"
              className="h-8 min-w-0 flex-1"
            />
            <Button type="submit" variant="outline" size="sm"><Search />搜索</Button>
          </form>
        </div>}
      </header>

      {(status || refreshNotice || error) && (
        <div
          role={error ? "alert" : "status"}
          className={`shrink-0 border-b px-4 py-2 text-xs ${
            error ? "border-destructive/30 bg-destructive/10 text-destructive" : status?.className
          }`}
        >
          {error || refreshNotice || status?.message}
        </div>
      )}

      {adminVisible ? (
        <Suspense fallback={<p role="status" className="py-12 text-center text-sm text-muted-foreground">加载管理面板…</p>}>
          <AihotAdminPanel onClose={() => setShowAdmin(false)} />
        </Suspense>
      ) : <main className="min-h-0 flex-1 overflow-y-auto p-3 sm:p-5">
        {loading && !data ? (
          <p className="py-12 text-center text-sm text-muted-foreground">加载中…</p>
        ) : !data || data.items.length === 0 ? (
          <div className="py-12 text-center">
            <p className="text-sm text-muted-foreground">{query ? "没有匹配的金融内容" : "暂无热榜数据"}</p>
            {query && (
              <Button type="button" variant="ghost" size="sm" className="mt-2" onClick={() => {
                setSearchDraft("");
                setQuery("");
              }}>
                清除搜索
              </Button>
            )}
          </div>
        ) : (
          <div className={`grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3 ${loading ? "opacity-60" : ""}`}>
            {data.items.map((item) => (
              <HotCard
                key={item.id}
                item={item}
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
          </div>
        )}
      </main>}

      <Suspense fallback={null}>
        <ContentDetailDrawer
          item={selectedItem}
          loadDetail={getAihotItemDetail}
          bookmarked={Boolean(selectedItem?.bookmarked)}
          onClose={() => setSelectedItem(null)}
          onToggleBookmark={onToggleBookmark}
          onSendToChat={onSendToChat}
          onDeepAnalysis={onDeepAnalysis}
        />
      </Suspense>
    </div>
  );
}

function HotCard({
  item,
  onOpen,
  onToggleBookmark,
}: {
  item: AihotItem;
  onOpen: () => void;
  onToggleBookmark: () => Promise<void>;
}) {
  return (
    <article className="group flex min-h-64 flex-col rounded-xl border bg-card p-4 shadow-sm transition hover:-translate-y-0.5 hover:border-primary/30 hover:shadow-md">
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="nums text-xl font-semibold text-primary">#{item.rank}</span>
          <RankTrend delta={item.rank_delta} />
        </div>
        <Button
          type="button"
          variant="ghost"
          size="icon-sm"
          aria-label={item.bookmarked ? "取消收藏" : "收藏"}
          onClick={() => void onToggleBookmark()}
        >
          <Bookmark className={item.bookmarked ? "fill-current text-primary" : "text-muted-foreground"} />
        </Button>
      </div>

      <button type="button" className="mt-3 flex flex-1 flex-col text-left" onClick={onOpen}>
        {item.cover_url && <img src={item.cover_url} alt="" className="mb-3 h-32 w-full rounded-lg border object-cover" />}
        <h3 className="line-clamp-2 text-[15px] font-semibold leading-6">{item.title ?? "无标题"}</h3>
        <p className="mt-2 line-clamp-3 text-xs leading-5 text-muted-foreground">
          {item.digest || "AI 摘要生成中，点击查看现有内容。"}
        </p>

        <div className="mt-auto pt-4">
          <div className="flex flex-wrap gap-1.5">
            <span className="rounded bg-muted px-1.5 py-0.5 text-[11px]">{PLATFORM_LABELS[item.platform] ?? item.platform}</span>
            {item.category && <span className="rounded bg-muted px-1.5 py-0.5 text-[11px]">{CATEGORY_LABELS[item.category] ?? item.category}</span>}
            {item.assets.slice(0, 2).map((asset) => (
              <span key={asset} className="rounded border px-1.5 py-0.5 text-[11px] text-muted-foreground">{asset}</span>
            ))}
          </div>
          <div className="mt-3 flex items-end justify-between gap-2 text-[11px] text-muted-foreground">
            <span className="min-w-0 truncate">{item.publisher.name}</span>
            {item.core_metric && (
              <span className="nums shrink-0 font-medium text-foreground">
                {item.core_metric.label} {item.core_metric.formatted_value ?? item.core_metric.value.toLocaleString("zh-CN")}
              </span>
            )}
          </div>
          {item.published_at && (
            <p className="nums mt-1 text-[10px] text-muted-foreground">
              {new Date(item.published_at).toLocaleString("zh-CN")}
            </p>
          )}
        </div>
      </button>
    </article>
  );
}

function RankTrend({ delta }: { delta: number | null }) {
  if (delta === null) {
    return <span className="rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">NEW</span>;
  }
  if (delta > 0) {
    return <span className="flex items-center text-xs text-up"><TrendingUp className="size-3.5" />{delta}</span>;
  }
  if (delta < 0) {
    return <span className="flex items-center text-xs text-down"><TrendingDown className="size-3.5" />{Math.abs(delta)}</span>;
  }
  return <span className="text-[10px] text-muted-foreground">持平</span>;
}

function getStatusMessage(data: AihotResponse | null): { message: string; className: string } | null {
  if (!data) return null;
  if (data.status === "stale_72h") {
    return { message: "数据超过 72 小时未成功更新，当前展示最近一次可用快照。", className: "bg-destructive/10 text-destructive" };
  }
  if (data.status === "stale_24h") {
    return { message: "数据超过 24 小时未成功更新，当前展示缓存快照。", className: "bg-amber-500/10 text-amber-700 dark:text-amber-300" };
  }
  if (data.status === "refreshing") {
    return { message: "热榜正在刷新，当前结果来自最近一次成功快照。", className: "bg-primary/5 text-primary" };
  }
  if (data.run?.finished_at) {
    return {
      message: `更新于 ${new Date(data.run.finished_at).toLocaleString("zh-CN")} · ${data.run.items_fetched} 条候选内容`,
      className: "bg-muted/40 text-muted-foreground",
    };
  }
  return null;
}
