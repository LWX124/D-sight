import { useState, useCallback } from "react";
import type { NewsItem } from "@/lib/news";

const STOCK_PATTERN = /[0-9]{6}|股票|期货|ETF|基金|A股|港股/;
const MAX_SELECTION = 5;
const CONTEXT_MAX_CHARS = 5000;

export function hasStockMention(items: NewsItem[]): boolean {
  return items.some((i) => STOCK_PATTERN.test(i.content + (i.title ?? "")));
}

export function formatNewsContext(items: NewsItem[]): string {
  const lines = items.map((i) => {
    const d = new Date(i.published_at).toLocaleString("zh-CN", {
      month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false,
    });
    return `[${d}] ${i.title ? i.title + ": " : ""}${i.content}`;
  });
  const text = lines.join("\n\n");
  if (text.length <= CONTEXT_MAX_CHARS) return text;
  return text.slice(0, CONTEXT_MAX_CHARS) + "\n\n（内容已截取）";
}

export function useNewsSelection() {
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [selectedItems, setSelectedItems] = useState<NewsItem[]>([]);

  const toggle = useCallback((item: NewsItem) => {
    setSelectedIds((prev) => {
      if (prev.has(item.id)) {
        setSelectedItems((items) => items.filter((i) => i.id !== item.id));
        const next = new Set(prev);
        next.delete(item.id);
        return next;
      }
      if (prev.size >= MAX_SELECTION) return prev;
      setSelectedItems((items) => [...items, item]);
      const next = new Set(prev);
      next.add(item.id);
      return next;
    });
  }, []);

  const clear = useCallback(() => {
    setSelectedIds(new Set());
    setSelectedItems([]);
  }, []);

  return {
    selectedIds,
    selectedItems,
    toggle,
    clear,
    isFull: selectedIds.size >= MAX_SELECTION,
  };
}
