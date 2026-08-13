import { useEffect, useState } from "react";
import { Bookmark, Bot, ExternalLink, LoaderCircle, Search, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import type {
  AihotItem,
  AihotItemDetail,
  FeedItem,
  SocialItemDetail,
} from "@/lib/social";

type ContentPreview = FeedItem | AihotItem;
type ContentDetail = SocialItemDetail | AihotItemDetail;

export type ChatContentAction = (message: string) => void | Promise<void>;

type ContentDetailDrawerProps = {
  item: ContentPreview | null;
  loadDetail: (itemId: string) => Promise<ContentDetail>;
  bookmarked: boolean;
  onClose: () => void;
  onToggleBookmark: (itemId: string) => Promise<void>;
  onSendToChat?: ChatContentAction;
  onDeepAnalysis?: ChatContentAction;
};

function getBody(item: ContentPreview | ContentDetail): string | null {
  if ("body_text" in item && item.body_text) return item.body_text;
  if ("transcript_text" in item && item.transcript_text) return item.transcript_text;
  return item.digest;
}

function getAssets(item: ContentPreview | ContentDetail): string[] {
  if ("assets" in item) return item.assets;
  if ("enrichment" in item) return item.enrichment?.assets ?? [];
  return [];
}

function getParagraphs(body: string): string[] {
  return body
    .trim()
    .split(/\n[\t ]*\n+/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);
}

function isAihotDetail(item: ContentPreview | ContentDetail): item is AihotItemDetail {
  return "rank_history" in item && Array.isArray(item.rank_history);
}

function buildChatMessage(item: ContentPreview | ContentDetail, deep: boolean): string {
  const body = getBody(item);
  const source = [item.publisher.name, item.platform, item.published_at]
    .filter(Boolean)
    .join(" · ");
  const context = [
    `标题：${item.title ?? "无标题"}`,
    `来源：${source}`,
    body ? `内容：${body}` : "内容：正文暂不可用，请仅根据标题和摘要回答。",
    item.url ? `原文：${item.url}` : null,
  ].filter(Boolean).join("\n");
  const request = deep
    ? "请对以上金融内容做深度分析，区分事实与推断，并说明潜在市场影响、关键变量和风险。"
    : "请基于以上内容继续讨论，先概括核心信息，再回答我的后续问题。";
  return `${context}\n\n---\n${request}`;
}

export default function ContentDetailDrawer({
  item,
  loadDetail,
  bookmarked,
  onClose,
  onToggleBookmark,
  onSendToChat,
  onDeepAnalysis,
}: ContentDetailDrawerProps) {
  const [detail, setDetail] = useState<ContentDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [actionError, setActionError] = useState("");
  const [bookmarking, setBookmarking] = useState(false);
  const [sending, setSending] = useState<"chat" | "deep" | null>(null);

  useEffect(() => {
    if (!item) return;
    let active = true;
    setDetail(null);
    setDetailError("");
    setLoading(true);
    void loadDetail(item.id)
      .then((value) => {
        if (active) setDetail(value);
      })
      .catch((error: unknown) => {
        if (active) {
          setDetailError(error instanceof Error ? error.message : "详情加载失败");
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [item, loadDetail]);

  useEffect(() => {
    if (!item) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [item, onClose]);

  if (!item) return null;
  const itemId = item.id;
  const content = detail ?? item;
  const body = getBody(content);
  const assets = getAssets(content);
  const history = isAihotDetail(content) ? content.rank_history : [];
  const currentRanking = history[0];
  const currentRank = "rank" in content ? content.rank : currentRanking?.rank;
  const rankingReason = currentRanking
    ? `平台分位 ${currentRanking.platform_score.toFixed(1)} · 时效 ${currentRanking.freshness_score.toFixed(1)} · 趋势 ${currentRanking.momentum_score.toFixed(1)}`
    : null;
  const aiSummary = isAihotDetail(content) ? content.enrichment?.summary : null;
  const latestMetrics = isAihotDetail(content) ? content.metrics[0] : null;

  async function toggleBookmark() {
    setActionError("");
    setBookmarking(true);
    try {
      await onToggleBookmark(itemId);
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "收藏操作失败");
    } finally {
      setBookmarking(false);
    }
  }

  async function send(kind: "chat" | "deep") {
    const action = kind === "deep" ? onDeepAnalysis : onSendToChat;
    if (!action) return;
    setActionError("");
    setSending(kind);
    try {
      await action(buildChatMessage(content, kind === "deep"));
      onClose();
    } catch (error) {
      setActionError(error instanceof Error ? error.message : "发送失败");
    } finally {
      setSending(null);
    }
  }

  return (
    <div className="fixed inset-0 z-50" role="presentation">
      <button
        type="button"
        aria-label="关闭详情"
        className="absolute inset-0 bg-background/60 backdrop-blur-[1px]"
        onClick={onClose}
      />
      <section
        role="dialog"
        aria-modal="true"
        aria-labelledby="content-detail-title"
        className="absolute inset-y-0 right-0 flex w-full max-w-xl flex-col border-l bg-card shadow-2xl"
      >
        <header className="flex shrink-0 items-center justify-between border-b px-4 py-3">
          <div className="min-w-0">
            <p className="text-[11px] uppercase tracking-[0.16em] text-muted-foreground">内容详情</p>
            <p className="mt-0.5 truncate text-xs text-muted-foreground">
              {content.publisher.name} · {content.platform}
            </p>
          </div>
          <Button type="button" variant="ghost" size="icon" aria-label="关闭" onClick={onClose}>
            <X className="size-4" />
          </Button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-5 sm:px-7">
          {loading && (
            <div className="mb-4 flex items-center gap-2 text-xs text-muted-foreground">
              <LoaderCircle className="size-3.5 animate-spin" /> 正在加载全文…
            </div>
          )}
          {detailError && (
            <div className="mb-4 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-xs text-amber-700 dark:text-amber-300">
              详情暂不可用（{detailError}），以下展示已有摘要。
            </div>
          )}

          <h2 id="content-detail-title" className="text-xl font-semibold leading-snug">
            {content.title ?? "无标题"}
          </h2>
          <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <span className="rounded bg-muted px-2 py-1">{content.platform}</span>
            <span>{content.publisher.name}</span>
            {content.published_at && <span>{new Date(content.published_at).toLocaleString("zh-CN")}</span>}
          </div>

          {assets.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-1.5">
              {assets.map((asset) => (
                <span key={asset} className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground">
                  {asset}
                </span>
              ))}
            </div>
          )}

          {currentRank !== undefined && (
            <section className="mt-5 rounded-lg border bg-muted/30 p-3">
              <div className="flex items-center gap-3 text-sm">
                <strong className="nums">当前排名 #{currentRank}</strong>
                {rankingReason && <span className="text-xs text-muted-foreground">{rankingReason}</span>}
              </div>
              {history.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-2 text-xs text-muted-foreground">
                  {history.map((point) => (
                    <span key={`${point.computed_at}-${point.rank}`} className="rounded bg-background px-2 py-1">
                      {new Date(point.computed_at).toLocaleDateString("zh-CN")} #{point.rank}
                    </span>
                  ))}
                </div>
              )}
            </section>
          )}

          {aiSummary && (
            <section className="mt-5 rounded-lg border border-primary/20 bg-primary/5 p-3">
              <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-primary">AI 摘要</p>
              <p className="mt-1 text-sm leading-6">{aiSummary}</p>
            </section>
          )}

          {latestMetrics && (
            <div className="mt-4 flex flex-wrap gap-2 text-xs text-muted-foreground">
              {(["view", "like", "comment", "share", "collect"] as const).map((key) => (
                latestMetrics[key] === null ? null : (
                  <span key={key} className="rounded bg-muted px-2 py-1">
                    {key} {latestMetrics[key]?.toLocaleString("zh-CN")}
                  </span>
                )
              ))}
            </div>
          )}

          {body ? (
            <article aria-label="正文" className="mt-6 space-y-4 text-sm leading-7 text-foreground/90">
              {getParagraphs(body).map((paragraph, index) => (
                <p key={`${index}-${paragraph.slice(0, 24)}`} className="whitespace-pre-line">
                  {paragraph}
                </p>
              ))}
            </article>
          ) : (
            <p className="mt-6 text-sm leading-7 text-foreground/90">
              正文尚未抓取，可通过原文入口查看完整内容。
            </p>
          )}
        </div>

        <footer className="shrink-0 border-t bg-card px-4 py-3">
          {actionError && <p className="mb-2 text-xs text-destructive">{actionError}</p>}
          <div className="flex flex-wrap gap-2">
            <Button type="button" variant="outline" size="sm" disabled={bookmarking} onClick={() => void toggleBookmark()}>
              <Bookmark className={bookmarked ? "fill-current" : ""} />
              {bookmarked ? "取消收藏" : "收藏"}
            </Button>
            {content.url ? (
              <Button type="button" variant="outline" size="sm" asChild>
                <a href={content.url} target="_blank" rel="noreferrer">
                  <ExternalLink />原文
                </a>
              </Button>
            ) : (
              <Button type="button" variant="outline" size="sm" disabled title="该内容没有原文链接">
                <ExternalLink />原文不可用
              </Button>
            )}
            <Button
              type="button"
              size="sm"
              disabled={!onSendToChat || sending !== null}
              title={onSendToChat ? undefined : "当前页面未接入对话能力"}
              onClick={() => void send("chat")}
            >
              <Bot />{sending === "chat" ? "发送中…" : "发送到对话"}
            </Button>
            <Button
              type="button"
              variant="secondary"
              size="sm"
              disabled={!onDeepAnalysis || sending !== null}
              title={onDeepAnalysis ? undefined : "当前页面未接入深度分析能力"}
              onClick={() => void send("deep")}
            >
              <Search />{sending === "deep" ? "发送中…" : "深度分析"}
            </Button>
          </div>
        </footer>
      </section>
    </div>
  );
}
