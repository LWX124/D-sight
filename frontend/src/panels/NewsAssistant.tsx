import { useEffect, useRef, useState } from "react";
import { Zap, Search, BarChart2, ChevronLeft, Trash2 } from "lucide-react";
import { RuntimeProvider } from "@/chat/RuntimeProvider";
import { Thread } from "@/chat/Thread";
import { clearNewsThread, fetchNews, fetchNewsThreadId, type NewsItem } from "@/lib/news";
import { hasStockMention, formatNewsContext } from "@/hooks/useNewsSelection";
import { useAssistantRuntime } from "@assistant-ui/react";

interface NewsAssistantProps {
  selectedItems: NewsItem[];
}

export default function NewsAssistant({ selectedItems }: NewsAssistantProps) {
  const [threadId, setThreadId] = useState<string | null>(null);

  useEffect(() => {
    fetchNewsThreadId().then(setThreadId).catch(console.error);
  }, []);

  // 清除对话：删旧线程换新 id，key 变化重建 runtime → 历史清空。
  const handleClear = async () => {
    if (!threadId || !confirm("清除当前对话记录？此操作不可撤销。")) return;
    try {
      setThreadId(await clearNewsThread(threadId));
    } catch (e) {
      console.error(e);
    }
  };

  if (!threadId) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        正在加载…
      </div>
    );
  }

  return (
    <RuntimeProvider key={threadId} threadId={threadId}>
      <NewsAssistantInner selectedItems={selectedItems} onClear={handleClear} />
    </RuntimeProvider>
  );
}

type ViewMode = "chat" | "timeline";

function NewsAssistantInner({
  selectedItems,
  onClear,
}: NewsAssistantProps & { onClear: () => void }) {
  const runtime = useAssistantRuntime();
  const [viewMode, setViewMode] = useState<ViewMode>("chat");
  const [keyword, setKeyword] = useState("");
  const [loading, setLoading] = useState(false);
  const [showDeepAnalysis, setShowDeepAnalysis] = useState(false);
  const hasStock = hasStockMention(selectedItems);

  // 发送带 context 的消息
  const sendWithContext = (context: string, prompt: string) => {
    const text = context
      ? `以下是相关新闻：\n\n${context}\n\n---\n${prompt}`
      : prompt;
    runtime.thread.composer.setInput(text);
    runtime.thread.composer.send();
    setShowDeepAnalysis(false);
  };

  // 功能1: 最近1小时总结
  const handleRecentHour = async () => {
    setLoading(true);
    try {
      const after = new Date(Date.now() - 3600_000).toISOString();
      const items = await fetchNews({ after, limit: 50 });
      if (items.length === 0) {
        runtime.thread.composer.setInput("（最近1小时暂无快讯）");
        runtime.thread.composer.send();
        return;
      }
      sendWithContext(formatNewsContext(items), "请总结以上最近1小时新闻要点。");
    } finally {
      setLoading(false);
    }
  };

  // 功能2: 关键词搜索
  const handleKeywordSearch = async () => {
    if (!keyword.trim()) return;
    setLoading(true);
    try {
      const items = await fetchNews({ keyword: keyword.trim(), limit: 20 });
      if (items.length === 0) {
        runtime.thread.composer.setInput(`（未找到含"${keyword}"的新闻，可尝试其他关键词）`);
        runtime.thread.composer.send();
        return;
      }
      sendWithContext(formatNewsContext(items), `请总结以下关于"${keyword}"的新闻。`);
    } finally {
      setLoading(false);
    }
  };

  // 功能3: 多选总结
  const handleSummarize = () => {
    sendWithContext(formatNewsContext(selectedItems), "请总结以下新闻并给出你的看法。");
  };

  // 功能3: 金融影响
  const handleFinancialImpact = () => {
    sendWithContext(formatNewsContext(selectedItems), "请分析以下新闻对金融、股票市场的潜在影响。");
  };

  // 功能5: 股票分析（轻量）
  const handleStockAnalysis = () => {
    sendWithContext(
      formatNewsContext(selectedItems),
      "请分析以下新闻中涉及标的（股票、期货、ETF 等）的投资影响，包括短期价格催化剂和潜在风险。",
    );
    setShowDeepAnalysis(true);
  };

  // 功能5: 深度分析
  const handleDeepAnalysis = () => {
    sendWithContext(
      formatNewsContext(selectedItems),
      "请使用 ai-berkshire skill 对新闻中涉及的股票标的进行价值分析，包括基本面评估和投资建议。",
    );
    setShowDeepAnalysis(false);
  };

  return (
    <div className="flex h-full flex-col">
      {/* ActionZone */}
      <div className="shrink-0 border-b border-border/60 px-3 py-2 space-y-2">
        {/* Row 1: 快捷按钮 + 搜索 */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleRecentHour}
            disabled={loading}
            className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-accent disabled:opacity-50 whitespace-nowrap"
          >
            <Zap className="size-3" />
            最近1小时
          </button>
          <div className="flex flex-1 items-center gap-1">
            <input
              type="text"
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleKeywordSearch()}
              placeholder="关键词搜索…"
              className="flex-1 min-w-0 rounded-md border border-border bg-transparent px-2 py-1 text-xs outline-none focus:ring-1 focus:ring-primary/50"
            />
            <button
              type="button"
              onClick={handleKeywordSearch}
              disabled={loading || !keyword.trim()}
              className="rounded-md border border-border p-1 hover:bg-accent disabled:opacity-50"
            >
              <Search className="size-3" />
            </button>
          </div>
          <button
            type="button"
            onClick={onClear}
            title="清除对话"
            aria-label="清除对话"
            data-testid="news-clear-chat"
            className="rounded-md border border-border p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <Trash2 className="size-3" />
          </button>
        </div>

        {/* Row 2: 选中操作（仅在有选中时显示） */}
        {selectedItems.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[11px] text-muted-foreground whitespace-nowrap">
              已选 {selectedItems.length}/5 条
            </span>
            <button type="button" onClick={handleSummarize}
              className="rounded-md border border-border px-2 py-0.5 text-xs hover:bg-accent">
              总结
            </button>
            <button type="button" onClick={handleFinancialImpact}
              className="rounded-md border border-border px-2 py-0.5 text-xs hover:bg-accent">
              金融影响
            </button>
            <button type="button" onClick={() => setViewMode("timeline")}
              className="rounded-md border border-border px-2 py-0.5 text-xs hover:bg-accent">
              时间线
            </button>
            {hasStock && (
              <button type="button" onClick={handleStockAnalysis}
                className="flex items-center gap-0.5 rounded-md border border-amber-500/50 bg-amber-500/10 px-2 py-0.5 text-xs text-amber-600 hover:bg-amber-500/20">
                <BarChart2 className="size-3" />
                股票分析
              </button>
            )}
            {showDeepAnalysis && (
              <button type="button" onClick={handleDeepAnalysis}
                className="rounded-md border border-primary/50 bg-primary/10 px-2 py-0.5 text-xs text-primary hover:bg-primary/20">
                深度分析
              </button>
            )}
          </div>
        )}
      </div>

      {/* Content: ChatStream 或 TimelineView */}
      <div className="flex-1 min-h-0 overflow-hidden">
        {viewMode === "timeline" ? (
          <TimelineView items={selectedItems} onBack={() => setViewMode("chat")} />
        ) : (
          <Thread />
        )}
      </div>
    </div>
  );
}

function TimelineView({ items, onBack }: { items: NewsItem[]; onBack: () => void }) {
  const sorted = [...items].sort(
    (a, b) => new Date(a.published_at).getTime() - new Date(b.published_at).getTime(),
  );
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-border/60 px-3 py-2">
        <span className="text-xs font-medium">新闻时间线（{sorted.length} 条）</span>
        <button type="button" onClick={onBack}
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground">
          <ChevronLeft className="size-3" />
          返回
        </button>
      </div>
      <div className="flex-1 overflow-y-auto px-3 py-3">
        <div className="relative ml-1 border-l border-border/50 pl-4 space-y-3">
          {sorted.map((item) => (
            <div key={item.id} className="relative">
              <div className="absolute -left-[17px] top-[6px] h-2 w-2 rounded-full bg-primary/60" />
              <div className="text-[11px] tabular-nums text-muted-foreground mb-0.5">
                {new Date(item.published_at).toLocaleString("zh-CN", {
                  month: "2-digit", day: "2-digit",
                  hour: "2-digit", minute: "2-digit", hour12: false,
                })}
              </div>
              {item.title && (
                <div className="text-[13px] font-medium mb-0.5">{item.title}</div>
              )}
              <p className="text-[13px] leading-[1.6] text-muted-foreground">{item.content}</p>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
