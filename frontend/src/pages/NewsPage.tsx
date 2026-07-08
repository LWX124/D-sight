import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { fetchNews, type NewsItem } from "@/lib/news";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type Channel = "news" | "social";

const POLL_MS = 30_000;

function formatTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function NewsCard({ item }: { item: NewsItem }) {
  return (
    <article
      data-testid="news-item"
      className="rounded-lg border border-border bg-card p-3"
    >
      <div className="mb-1 flex items-baseline justify-between gap-2">
        {item.title ? (
          <h3 className="min-w-0 flex-1 font-medium text-foreground">{item.title}</h3>
        ) : (
          <span className="min-w-0 flex-1" />
        )}
        <time className="shrink-0 text-xs text-muted-foreground">
          {formatTime(item.published_at)}
        </time>
      </div>
      <p className="whitespace-pre-wrap text-sm text-muted-foreground">{item.content}</p>
      {item.url && (
        <a
          href={item.url}
          target="_blank"
          rel="noreferrer"
          className="mt-1 inline-block break-all text-xs text-primary hover:underline"
        >
          {item.url}
        </a>
      )}
    </article>
  );
}

export default function NewsPage() {
  const [channel, setChannel] = useState<Channel>("news");
  const [items, setItems] = useState<NewsItem[]>([]);
  const [hasMore, setHasMore] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);

  // Refs so the scroll handler / poll interval read live values without
  // re-subscribing on every state change.
  const itemsRef = useRef<NewsItem[]>([]);
  itemsRef.current = items;
  const loadingRef = useRef(false);
  const hasMoreRef = useRef(true);
  hasMoreRef.current = hasMore;

  const { data, isLoading, isError } = useQuery({
    queryKey: ["news", channel],
    queryFn: () => fetchNews({ channel }),
    enabled: channel === "news",
  });

  // Seed the manual list from the initial query result (per channel).
  useEffect(() => {
    if (channel === "news" && data) {
      setItems(data);
      setHasMore(data.length > 0);
    }
  }, [data, channel]);

  // 30s incremental poll: fetch items newer than the newest one, prepend deduped.
  useEffect(() => {
    if (channel !== "news") return;
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
        // ignore transient poll errors; next tick retries
      }
    }, POLL_MS);
    return () => clearInterval(id);
  }, [channel]);

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
        if (add.length === 0) setHasMore(false);
        return [...prev, ...add];
      });
    } catch {
      // ignore; user can scroll again to retry
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

  return (
    <div className="flex h-svh flex-col bg-background">
      <header className="flex items-center justify-between border-b border-border px-4 py-2">
        <div className="flex items-center gap-3">
          <Button asChild variant="ghost" size="sm" data-testid="news-back">
            <Link to="/">
              <ArrowLeft className="size-4" />
              返回聊天
            </Link>
          </Button>
          <span className="text-sm font-medium text-foreground">快讯</span>
        </div>
      </header>

      <div className="border-b border-border px-4">
        <div className="mx-auto flex max-w-3xl gap-1">
          {(
            [
              ["news", "快讯"],
              ["social", "社媒"],
            ] as const
          ).map(([c, label]) => (
            <button
              key={c}
              type="button"
              data-testid={`news-tab-${c}`}
              onClick={() => setChannel(c)}
              className={cn(
                "-mb-px border-b-2 px-3 py-2 text-sm",
                channel === c
                  ? "border-primary font-medium text-foreground"
                  : "border-transparent text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto" onScroll={onScroll}>
        <main className="mx-auto max-w-3xl space-y-3 p-4">
          {channel === "social" ? (
            <p className="py-16 text-center text-sm text-muted-foreground">
              社媒信源建设中
            </p>
          ) : (
            <>
              {isLoading && <p className="text-sm text-muted-foreground">加载中…</p>}
              {isError && <p className="text-sm text-destructive">加载快讯失败</p>}
              {!isLoading && !isError && items.length === 0 && (
                <p className="py-16 text-center text-sm text-muted-foreground">
                  暂无快讯
                </p>
              )}
              {items.map((item) => (
                <NewsCard key={item.id} item={item} />
              ))}
              {loadingMore && (
                <p className="py-2 text-center text-xs text-muted-foreground">加载更多…</p>
              )}
              {!hasMore && items.length > 0 && (
                <p className="py-2 text-center text-xs text-muted-foreground">没有更多了</p>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
