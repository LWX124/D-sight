// frontend/src/hooks/useNewsSelection.test.ts
import { renderHook, act } from "@testing-library/react";
import { describe, test, expect } from "vitest";
import { useNewsSelection, hasStockMention, formatNewsContext } from "./useNewsSelection";
import type { NewsItem } from "@/lib/news";

const item = (id: string, content = "", title: string | null = null): NewsItem => ({
  id, channel: "news", title, content, url: null, published_at: "2026-07-08T10:00:00Z",
});

describe("useNewsSelection", () => {
  test("toggle adds item", () => {
    const { result } = renderHook(() => useNewsSelection());
    act(() => result.current.toggle(item("1", "test")));
    expect(result.current.selectedIds.has("1")).toBe(true);
    expect(result.current.selectedItems).toHaveLength(1);
  });

  test("toggle removes item on second call", () => {
    const { result } = renderHook(() => useNewsSelection());
    act(() => result.current.toggle(item("1")));
    act(() => result.current.toggle(item("1")));
    expect(result.current.selectedIds.has("1")).toBe(false);
    expect(result.current.selectedItems).toHaveLength(0);
  });

  test("caps at 5 items", () => {
    const { result } = renderHook(() => useNewsSelection());
    for (let i = 1; i <= 6; i++) act(() => result.current.toggle(item(String(i))));
    expect(result.current.selectedIds.size).toBe(5);
    expect(result.current.isFull).toBe(true);
  });

  test("clear resets all", () => {
    const { result } = renderHook(() => useNewsSelection());
    act(() => result.current.toggle(item("1")));
    act(() => result.current.clear());
    expect(result.current.selectedIds.size).toBe(0);
  });
});

describe("hasStockMention", () => {
  test("detects 6-digit code", () => {
    expect(hasStockMention([item("1", "000001大涨")])).toBe(true);
  });
  test("detects keyword 股票", () => {
    expect(hasStockMention([item("1", "股票市场")])).toBe(true);
  });
  test("detects ETF", () => {
    expect(hasStockMention([item("1", "", "ETF基金")])).toBe(true);
  });
  test("returns false when no match", () => {
    expect(hasStockMention([item("1", "今日天气晴")])).toBe(false);
  });
});

describe("formatNewsContext", () => {
  test("formats items with time and content", () => {
    const result = formatNewsContext([item("1", "内容A", "标题A")]);
    expect(result).toContain("标题A");
    expect(result).toContain("内容A");
  });

  test("truncates at 5000 chars", () => {
    const result = formatNewsContext([item("1", "a".repeat(6000))]);
    expect(result.length).toBeLessThan(5200);
    expect(result).toContain("内容已截取");
  });
});
