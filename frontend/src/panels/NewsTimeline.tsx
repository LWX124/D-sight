import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { fetchNews, refreshNews, type NewsItem } from "@/lib/news";

const POLL_MS = 120_000;

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function formatDateHeader(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleDateString("zh-CN", { month: "2-digit", day: "2-digit", weekday: "short" });
}

function groupByDate(items: NewsItem[]): { date: string; items: NewsItem[] }[] {
  const groups: { date: string; items: NewsItem[] }[] = [];
  let currentDate = "";
  for (const item of items) {
    const d = new Date(item.published_at).toDateString();
    if (d !== currentDate) {
      currentDate = d;
      groups.push({ date: item.published_at, items: [item] });
    } else {
      groups[groups.length - 1].items.push(item);
    }
  }
  return groups;
}

function LoadingSkeleton() {
  return (
    <div className="px-5 py-4">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="flex gap-3 animate-pulse mb-1">
          <div className="flex flex-col items-center pt-1.5">
            <div className="h-2 w-2 rounded-full bg-muted-foreground/20" />
            <div className="mt-1 h-14 w-px bg-muted-foreground/10" />
          </div>
          <div className="flex-1 pb-4">
            <div className="h-3 w-12 rounded bg-muted-foreground/15 mb-2" />
            <div className="space-y-1.5 rounded-lg bg-muted/50 p-3">
              <div className="h-3.5 w-4/5 rounded bg-muted-foreground/10" />
              <div className="h-3 w-3/5 rounded bg-muted-foreground/8" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

interface NewsTimelineProps {
  selectedIds: Set<string>;
  onToggle: (item: NewsItem) => void;
  isFull: boolean;
}

export default function NewsTimeline({ selectedIds, onToggle, isFull }: NewsTimelineProps) {
  const [items, setItems] = useState<NewsItem[]>([]);
  const [hasMore, setHasMore] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);

  const itemsRef = useRef<NewsItem[]>([]);
  itemsRef.current = items;
  const loadingRef = useRef(false);
  const hasMoreRef = useRef(true);
  hasMoreRef.current = hasMore;

  const { data, isLoading, isError } = useQuery({
    queryKey: ["news"],
    queryFn: () => fetchNews({ channel: "news" }),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
  });

  useEffect(() => {
    if (data) {
      setItems(data);
      setHasMore(data.length > 0);
    }
  }, [data]);

  useEffect(() => {
    const id = setInterval(async () => {
      const cur = itemsRef.current;
      if (cur.length === 0) return;
      try {
        const fresh = await fetchNews({ channel: "news", after: cur[0].published_at });
        if (fresh.length === 0) return;
        setItems((prev) => {
          const seen = new Set(prev.map((i) => i.id));
          const add = fresh.filter((i) => !seen.has(i.id));
          return add.length === 0 ? prev : [...add, ...prev];
        });
      } catch {
        // ignore transient poll errors
      }
    }, POLL_MS);
    return () => clearInterval(id);
  }, []);

  async function loadMore() {
    const cur = itemsRef.current;
    if (loadingRef.current || !hasMoreRef.current || cur.length === 0) return;
    loadingRef.current = true;
    setLoadingMore(true);
    try {
      const older = await fetchNews({
        channel: "news",
        before: cur[cur.length - 1].published_at,
      });
      if (older.length === 0) {
        setHasMore(false);
        return;
      }
      setItems((prev) => {
        const seen = new Set(prev.map((i) => i.id));
        const add = older.filter((i) => !seen.has(i.id));
        if (add.length === 0) {
          if (older.length < 20) setHasMore(false);
          return prev;
        }
        return [...prev, ...add];
      });
    } catch {
      // ignore
    } finally {
      loadingRef.current = false;
      setLoadingMore(false);
    }
  }

  function onScroll(e: React.UIEvent<HTMLDivElement>) {
    const el = e.currentTarget;
    if (el.scrollHeight - el.scrollTop - el.clientHeight < 200) {
      void loadMore();
    }
  }

  const [refreshing, setRefreshing] = useState(false);

  const handleRefresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const fresh = await refreshNews("news");
      if (fresh.length > 0) {
        setItems((prev) => {
          const seen = new Set(prev.map((i) => i.id));
          const add = fresh.filter((i) => !seen.has(i.id));
          if (add.length === 0) return prev;
          return [...add, ...prev];
        });
      }
    } catch {
      // ignore
    } finally {
      setRefreshing(false);
    }
  }, []);

  const groups = useMemo(() => groupByDate(items), [items]);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-border/60 px-5 py-2.5">
        <div className="flex items-center gap-2">
          <div className="relative flex h-2 w-2 items-center justify-center">
            {items.length > 0 && (
              <>
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
              </>
            )}
            {items.length === 0 && <span className="inline-flex h-2 w-2 rounded-full bg-muted-foreground/30" />}
          </div>
          <span className="text-xs tabular-nums text-muted-foreground">
            {items.length > 0 ? formatTime(items[0].published_at) : "等待数据"}
          </span>
        </div>
        <button
          type="button"
          onClick={handleRefresh}
          disabled={refreshing}
          className="flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs text-muted-foreground transition-all hover:bg-accent hover:text-foreground active:scale-95 disabled:opacity-40"
        >
          <RefreshCw className={`size-3 ${refreshing ? "animate-spin" : ""}`} />
          刷新
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto" onScroll={onScroll}>
        {isLoading && <LoadingSkeleton />}
        {isError && (
          <div className="flex items-center justify-center py-20">
            <p className="text-sm text-destructive/80">加载失败，请重试</p>
          </div>
        )}
        {!isLoading && !isError && items.length === 0 && (
          <div className="flex flex-col items-center justify-center py-24">
            <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-muted">
              <RefreshCw className="size-5 text-muted-foreground/60" />
            </div>
            <p className="mb-1 text-sm text-foreground/70">暂无快讯</p>
            <p className="mb-4 text-xs text-muted-foreground">点击下方按钮拉取最新数据</p>
            <button
              type="button"
              onClick={handleRefresh}
              className="rounded-lg bg-foreground px-4 py-2 text-xs font-medium text-background transition-all hover:bg-foreground/85 active:scale-95"
            >
              立即获取
            </button>
          </div>
        )}

        {items.length > 0 && (
          <div className="px-5 py-3">
            {groups.map((group, gi) => (
              <div key={group.date}>
                {/* Date separator */}
                <div className={`flex items-center gap-3 ${gi > 0 ? "mt-5 mb-3" : "mb-3"}`}>
                  <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground/70">
                    {formatDateHeader(group.date)}
                  </span>
                  <div className="h-px flex-1 bg-border/50" />
                </div>

                {/* Timeline items */}
                <div className="relative ml-1.5 border-l border-border/50 pl-8">
                  {group.items.map((item, idx) => {
                    const isFirst = gi === 0 && idx === 0;
                    const CardWrapper = item.url ? "a" : "div";
                    const cardProps = item.url
                      ? { href: item.url, target: "_blank" as const, rel: "noreferrer" }
                      : {};

                    return (
                      <div key={item.id} className="relative pb-4 last:pb-1" data-testid="news-item">
                        {/* Checkbox */}
                        <label
                          className="absolute -left-[38px] top-[5px] flex items-center"
                          onClick={(e) => e.stopPropagation()}
                        >
                          <input
                            type="checkbox"
                            checked={selectedIds.has(item.id)}
                            disabled={isFull && !selectedIds.has(item.id)}
                            onChange={() => onToggle(item)}
                            title={isFull && !selectedIds.has(item.id) ? "最多选5条" : undefined}
                            className="h-3.5 w-3.5 cursor-pointer accent-primary disabled:cursor-not-allowed disabled:opacity-40"
                          />
                        </label>

                        {/* Dot */}
                        <div className={`absolute -left-[21px] top-[7px] flex h-2 w-2 items-center justify-center ${isFirst ? "" : ""}`}>
                          {isFirst ? (
                            <>
                              <span className="absolute h-2 w-2 animate-ping rounded-full bg-primary/40" />
                              <span className="relative h-2 w-2 rounded-full bg-primary" />
                            </>
                          ) : (
                            <span className="h-1.5 w-1.5 rounded-full bg-muted-foreground/25" />
                          )}
                        </div>

                        {/* Card */}
                        <CardWrapper
                          {...cardProps}
                          className={`group block rounded-lg px-3 py-2.5 transition-all duration-150 ${
                            item.url
                              ? "cursor-pointer hover:bg-accent/60 hover:translate-x-0.5 active:scale-[0.995]"
                              : ""
                          }`}
                        >
                          <div className="mb-1 flex items-center gap-2">
                            <span className="text-[11px] tabular-nums text-muted-foreground/70">
                              {formatTime(item.published_at)}
                            </span>
                            {item.title && (
                              <span className="text-[13px] font-medium text-foreground group-hover:text-foreground">
                                {item.title}
                              </span>
                            )}
                          </div>
                          <p className="whitespace-pre-wrap text-[13px] leading-[1.65] text-muted-foreground group-hover:text-foreground/80">
                            {item.content}
                          </p>
                        </CardWrapper>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}

            {loadingMore && (
              <div className="flex items-center justify-center py-3">
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-muted-foreground/20 border-t-muted-foreground/60" />
              </div>
            )}
            {!hasMore && items.length > 0 && (
              <p className="py-3 text-center text-[11px] text-muted-foreground/50">到底了</p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
