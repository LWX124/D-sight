import { useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  CATEGORIES,
  type DashboardRow,
  fetchDashboard,
  refreshSnapshot,
} from "@/lib/fundArb";

type FlashDir = "up" | "down";

export default function FundArbPanel() {
  const [category, setCategory] = useState("");
  const [rows, setRows] = useState<DashboardRow[]>([]);
  const [marketOpen, setMarketOpen] = useState(false);
  const [asOf, setAsOf] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState("");

  // 价格变化闪色
  const prevPriceRef = useRef<Map<string, number>>(new Map());
  const [flashMap, setFlashMap] = useState<Map<string, FlashDir>>(new Map());

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

  // 检测价格变化,生成 flash
  useEffect(() => {
    if (rows.length === 0) return;
    const next = new Map<string, number>();
    const diff = new Map<string, FlashDir>();
    for (const r of rows) {
      if (r.price != null) {
        const prev = prevPriceRef.current.get(r.fund_code);
        if (prev != null && prev !== r.price) {
          diff.set(r.fund_code, r.price > prev ? "up" : "down");
        }
        next.set(r.fund_code, r.price);
      }
    }
    prevPriceRef.current = next;
    if (diff.size === 0) return;
    setFlashMap(diff);
    const t = setTimeout(() => setFlashMap(new Map()), 650);
    return () => clearTimeout(t);
  }, [rows]);

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
      {/* 顶栏:品类 tabs + 状态 */}
      <div className="flex items-center justify-between border-b border-border bg-card/30 px-5 pt-2 backdrop-blur">
        <div role="tablist" className="flex gap-1">
          {CATEGORIES.map((c) => {
            const active = category === c.key;
            return (
              <button
                key={c.key}
                type="button"
                role="tab"
                aria-selected={active}
                onClick={() => setCategory(c.key)}
                className={`relative cursor-pointer px-2.5 pb-2 pt-1 text-xs transition-colors duration-150 ${
                  active
                    ? "font-medium text-foreground"
                    : "text-muted-foreground hover:text-foreground"
                }`}
              >
                {c.label}
                <span
                  className={`absolute inset-x-2 bottom-0 h-px bg-primary transition-opacity duration-150 ${
                    active ? "opacity-100 shadow-[0_0_6px_var(--color-primary)]" : "opacity-0"
                  }`}
                />
              </button>
            );
          })}
        </div>
        <div className="flex items-center gap-3 pb-1">
          <span
            className={`size-1.5 rounded-full ${
              marketOpen
                ? "bg-down text-down animate-pulse-glow"
                : "bg-muted-foreground/50"
            }`}
          />
          <span className="nums text-[10px] uppercase tracking-[0.18em] text-muted-foreground">
            {marketOpen ? "Live" : "Closed"}
          </span>
          {asOf && (
            <span className="nums text-xs text-muted-foreground">
              {new Date(asOf).toLocaleTimeString("zh-CN", { hour12: false })}
            </span>
          )}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            className="h-7 gap-1 px-2 text-xs cursor-pointer hover:text-primary"
            onClick={onRefresh}
            disabled={loading}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
          </Button>
        </div>
      </div>

      {err && (
        <p className="border-b border-destructive/30 bg-destructive/10 px-4 py-1.5 text-xs text-destructive" role="alert">
          {err}
        </p>
      )}

      {/* 表格 */}
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full text-xs">
          <thead className="sticky top-0 z-10 bg-card/80 backdrop-blur">
            <tr className="border-b border-border text-left">
              <th className="nums px-3 py-2 text-[10px] font-medium uppercase tracking-[0.15em] text-muted-foreground">代码</th>
              <th className="px-3 py-2 text-[10px] font-medium uppercase tracking-[0.15em] text-muted-foreground">名称</th>
              <th className="nums px-3 py-2 text-right text-[10px] font-medium uppercase tracking-[0.15em] text-muted-foreground">现价</th>
              <th className="nums px-3 py-2 text-right text-[10px] font-medium uppercase tracking-[0.15em] text-muted-foreground">涨跌%</th>
              <th className="nums px-3 py-2 text-right text-[10px] font-medium uppercase tracking-[0.15em] text-muted-foreground">估值</th>
              <th className="nums px-3 py-2 text-right text-[10px] font-medium uppercase tracking-[0.15em] text-muted-foreground">溢价%</th>
              <th className="nums px-3 py-2 text-right text-[10px] font-medium uppercase tracking-[0.15em] text-muted-foreground">净值</th>
              <th className="nums px-3 py-2 text-[10px] font-medium uppercase tracking-[0.15em] text-muted-foreground">净值日</th>
              <th className="nums px-3 py-2 text-right text-[10px] font-medium uppercase tracking-[0.15em] text-muted-foreground">5日误差</th>
              <th className="px-3 py-2 text-[10px] font-medium uppercase tracking-[0.15em] text-muted-foreground">申购</th>
            </tr>
          </thead>
          <tbody>
            {loading && rows.length === 0 ? (
              // shimmer 骨架
              Array.from({ length: 12 }).map((_, i) => (
                <tr key={`sk-${i}`} className="border-b border-border/50">
                  {Array.from({ length: 10 }).map((__, j) => (
                    <td key={j} className="px-3 py-2">
                      <div className="h-3 w-full animate-shimmer rounded bg-muted/60" style={{ animationDelay: `${i * 40}ms` }} />
                    </td>
                  ))}
                </tr>
              ))
            ) : (
              rows.map((r) => {
                const flash = flashMap.get(r.fund_code);
                return (
                  <tr
                    key={r.fund_code}
                    className={`group border-b border-border/50 transition-colors duration-150 hover:bg-accent/30 ${
                      flash === "up" ? "animate-flash-up" : flash === "down" ? "animate-flash-down" : ""
                    }`}
                  >
                    <td className="nums px-3 py-1.5 text-muted-foreground">{r.fund_code}</td>
                    <td className="max-w-[10rem] truncate px-3 py-1.5">
                      {r.fund_name}
                      {r.low_confidence && <span className="ml-1 text-amber-400">?</span>}
                      {r.approx && <span className="ml-0.5 text-muted-foreground">~</span>}
                    </td>
                    <td className="nums px-3 py-1.5 text-right font-medium">
                      {r.price?.toFixed(3) ?? "—"}
                    </td>
                    <td className={`nums px-3 py-1.5 text-right ${(r.price_pct ?? 0) >= 0 ? "text-up" : "text-down"}`}>
                      {r.price_pct != null ? `${r.price_pct >= 0 ? "+" : ""}${r.price_pct.toFixed(2)}` : "—"}
                    </td>
                    <td className="nums px-3 py-1.5 text-right text-muted-foreground">
                      {r.est_nav?.toFixed(4) ?? "—"}
                    </td>
                    <td className={`nums px-3 py-1.5 text-right font-medium ${(r.premium ?? 0) >= 0 ? "text-up" : "text-down"}`}>
                      {r.premium != null ? `${r.premium >= 0 ? "+" : ""}${r.premium.toFixed(2)}` : "—"}
                    </td>
                    <td className="nums px-3 py-1.5 text-right text-muted-foreground">
                      {r.nav?.toFixed(4) ?? "—"}
                    </td>
                    <td className="nums px-3 py-1.5 text-muted-foreground">{r.nav_date ?? "—"}</td>
                    <td className="nums px-3 py-1.5 text-right text-muted-foreground">
                      {r.err_5d != null ? `${r.err_5d.toFixed(2)}%` : "—"}
                    </td>
                    <td className="px-3 py-1.5 text-muted-foreground">
                      <span className={r.purchase_status === "暂停申购" ? "text-up" : ""}>
                        {r.purchase_status ?? "—"}
                      </span>
                      {r.purchase_limit && (
                        <span className="nums ml-0.5 text-muted-foreground/70">({r.purchase_limit})</span>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
            {!loading && rows.length === 0 && (
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
