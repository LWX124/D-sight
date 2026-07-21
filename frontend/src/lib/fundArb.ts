import { apiFetch } from "./api";

export type DashboardRow = {
  fund_code: string;
  fund_name: string;
  category: string;
  price: number | null;
  price_pct: number | null;
  amount: number | null;
  est_nav: number | null;
  premium: number | null;
  nav: number | null;
  nav_date: string | null;
  err_5d: number | null;
  low_confidence: boolean;
  approx: boolean;
  purchase_status: string | null;
  redemption_status: string | null;
  purchase_limit: string | null;
  source: string;
};

export type DashboardOut = {
  rows: DashboardRow[];
  as_of: string | null;
  market_open: boolean;
};

export type HistoryPoint = {
  date: string;
  price: number | null;
  nav: number | null;
  premium: number | null;
  valuation_error: number | null;
};

export type HistoryOut = {
  points: HistoryPoint[];
};

export const CATEGORIES = [
  { key: "", label: "全部" },
  { key: "gold_oil", label: "黄金原油" },
  { key: "qdii_us_eu", label: "QDII欧美" },
  { key: "qdii_japan", label: "QDII日本" },
  { key: "qdii_asia", label: "QDII亚洲" },
  { key: "domestic_lof", label: "国内LOF" },
  { key: "silver", label: "白银" },
  { key: "cash_bond", label: "现金管理" },
] as const;

export async function fetchDashboard(category = ""): Promise<DashboardOut> {
  const p = new URLSearchParams();
  if (category) p.set("category", category);
  const r = await apiFetch(`/api/fund-arb/dashboard?${p.toString()}`);
  if (!r.ok) throw new Error("加载基金套利看板失败");
  return r.json();
}

export async function fetchHistory(code: string, days = 60): Promise<HistoryOut> {
  const r = await apiFetch(`/api/fund-arb/funds/${code}/history?days=${days}`);
  if (!r.ok) throw new Error("加载历史数据失败");
  return r.json();
}

export async function refreshSnapshot(): Promise<void> {
  const r = await apiFetch("/api/fund-arb/refresh", { method: "POST" });
  if (!r.ok && r.status !== 403) throw new Error("刷新快照失败");
}
