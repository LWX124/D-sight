import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  CATEGORIES,
  type DashboardRow,
  fetchDashboard,
  refreshSnapshot,
} from "@/lib/fundArb";

export default function FundArbPanel() {
  const [category, setCategory] = useState("");
  const [rows, setRows] = useState<DashboardRow[]>([]);
  const [marketOpen, setMarketOpen] = useState(false);
  const [asOf, setAsOf] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  async function load(cat: string) {
    setErr("");
    setLoading(true);
    try {
      const d = await fetchDashboard(cat);
      setRows(d.rows);
      setMarketOpen(d.market_open);
      setAsOf(d.as_of);
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load(category);
  }, [category]);

  useEffect(() => {
    if (!marketOpen) return;
    const timer = setInterval(() => load(category), 20_000);
    return () => clearInterval(timer);
  }, [category, marketOpen]);

  async function onRefresh() {
    try {
      await refreshSnapshot();
      await load(category);
    } catch (e) {
      setErr(String(e));
    }
  }

  return (
    <div className="flex h-full flex-col">
      {/* 顶栏：品类 tabs + 状态 */}
      <div className="flex items-center justify-between border-b px-5 pt-2 pb-2">
        <div role="tablist" className="flex gap-1">
          {CATEGORIES.map((c) => (
            <button
              key={c.key}
              type="button"
              role="tab"
              aria-selected={category === c.key}
              onClick={() => setCategory(c.key)}
              className={`rounded px-2.5 py-1 text-xs transition-colors ${
                category === c.key
                  ? "bg-primary/10 font-medium text-primary"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {c.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${marketOpen ? "bg-green-500" : "bg-gray-400"}`} />
          <span className="text-xs text-muted-foreground">
            {marketOpen ? "交易中" : "已收盘"}
          </span>
          {asOf && (
            <span className="text-xs tabular-nums text-muted-foreground">
              {new Date(asOf).toLocaleTimeString()}
            </span>
          )}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 gap-1 px-2 text-xs"
            onClick={onRefresh}
            disabled={loading}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </div>

      {err && (
        <p className="border-b px-4 py-1.5 text-xs text-red-500" role="alert">{err}</p>
      )}

      {/* 表格 */}
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-background">
            <tr className="border-b text-left text-muted-foreground">
              <th className="px-3 py-2 font-medium">代码</th>
              <th className="px-3 py-2 font-medium">名称</th>
              <th className="px-3 py-2 font-medium text-right">现价</th>
              <th className="px-3 py-2 font-medium text-right">涨跌%</th>
              <th className="px-3 py-2 font-medium text-right">估值</th>
              <th className="px-3 py-2 font-medium text-right">溢价%</th>
              <th className="px-3 py-2 font-medium text-right">净值</th>
              <th className="px-3 py-2 font-medium">净值日</th>
              <th className="px-3 py-2 font-medium text-right">5日误差</th>
              <th className="px-3 py-2 font-medium">申购</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.fund_code} className="border-b hover:bg-accent/30">
                <td className="px-3 py-1.5 tabular-nums">{r.fund_code}</td>
                <td className="px-3 py-1.5 max-w-[10rem] truncate">
                  {r.fund_name}
                  {r.low_confidence && <span className="ml-1 text-amber-500">?</span>}
                  {r.approx && <span className="ml-0.5 text-muted-foreground">~</span>}
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums">{r.price?.toFixed(3) ?? "—"}</td>
                <td className={`px-3 py-1.5 text-right tabular-nums ${(r.price_pct ?? 0) >= 0 ? "text-red-500" : "text-green-600"}`}>
                  {r.price_pct != null ? `${r.price_pct >= 0 ? "+" : ""}${r.price_pct.toFixed(2)}` : "—"}
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums">{r.est_nav?.toFixed(4) ?? "—"}</td>
                <td className={`px-3 py-1.5 text-right tabular-nums font-medium ${(r.premium ?? 0) >= 0 ? "text-red-500" : "text-green-600"}`}>
                  {r.premium != null ? `${r.premium >= 0 ? "+" : ""}${r.premium.toFixed(2)}` : "—"}
                </td>
                <td className="px-3 py-1.5 text-right tabular-nums">{r.nav?.toFixed(4) ?? "—"}</td>
                <td className="px-3 py-1.5 tabular-nums text-muted-foreground">{r.nav_date ?? "—"}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{r.err_5d != null ? `${r.err_5d.toFixed(2)}%` : "—"}</td>
                <td className="px-3 py-1.5">
                  <span className={`${r.purchase_status === "暂停申购" ? "text-red-500" : ""}`}>
                    {r.purchase_status ?? "—"}
                  </span>
                  {r.purchase_limit && <span className="ml-0.5 text-muted-foreground">({r.purchase_limit})</span>}
                </td>
              </tr>
            ))}
            {rows.length === 0 && !loading && (
              <tr>
                <td colSpan={10} className="px-3 py-10 text-center text-muted-foreground">
                  暂无数据
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
