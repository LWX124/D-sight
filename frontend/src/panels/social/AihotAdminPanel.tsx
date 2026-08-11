import { useCallback, useEffect, useRef, useState } from "react";
import { Activity, CircleDollarSign, Plus, Trash2, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  type AihotCategory,
  type AihotProviderStats,
  type AihotSource,
  type PublisherSearchResult,
  createAihotSource,
  deleteAihotSource,
  getAihotProviderStats,
  listAihotSources,
  searchPublishers,
  updateAihotSource,
} from "@/lib/social";

const CATEGORIES: Array<{ key: AihotCategory; label: string }> = [
  { key: "macro", label: "宏观" },
  { key: "policy", label: "政策" },
  { key: "industry", label: "行业" },
  { key: "company", label: "公司" },
  { key: "market", label: "市场" },
];

const CATEGORY_LABELS = Object.fromEntries(CATEGORIES.map(({ key, label }) => [key, label]));
const PLATFORM_LABELS: Record<string, string> = {
  wechat: "公众号",
  xiaohongshu: "小红书",
  bilibili: "B站",
};

type SourceKind = "keyword" | "account";
type AccountPlatform = "wechat" | "bilibili";

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function percent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

export default function AihotAdminPanel({ onClose }: { onClose: () => void }) {
  const [sources, setSources] = useState<AihotSource[]>([]);
  const [stats, setStats] = useState<AihotProviderStats | null>(null);
  const [days, setDays] = useState(30);
  const [sourceKind, setSourceKind] = useState<SourceKind>("keyword");
  const [accountPlatform, setAccountPlatform] = useState<AccountPlatform>("wechat");
  const [accountQuery, setAccountQuery] = useState("");
  const [accountResults, setAccountResults] = useState<PublisherSearchResult[]>([]);
  const [sourceKey, setSourceKey] = useState("");
  const [category, setCategory] = useState<AihotCategory>("market");
  const [notes, setNotes] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [searching, setSearching] = useState(false);
  const [changingId, setChangingId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const accountSearchRequest = useRef(0);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextSources, nextStats] = await Promise.all([
        listAihotSources(),
        getAihotProviderStats(days),
      ]);
      setSources(nextSources);
      setStats(nextStats);
    } catch (loadError) {
      setError(messageOf(loadError, "管理员数据加载失败"));
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    void load();
  }, [load]);

  async function addKeywordSource() {
    const keyword = sourceKey.trim();
    if (!keyword) {
      setError("请输入小红书关键词");
      return;
    }
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await createAihotSource({
        platform: "xiaohongshu",
        source_key: keyword,
        category,
        ...(notes.trim() ? { notes: notes.trim() } : {}),
      });
      setSourceKey("");
      setNotes("");
      setNotice("信源已添加，将在后续 AIHot 批次中生效。");
      setSources(await listAihotSources());
    } catch (saveError) {
      setError(messageOf(saveError, "信源添加失败"));
    } finally {
      setSaving(false);
    }
  }

  async function searchAccounts() {
    const query = accountQuery.trim();
    if (!query) return;
    const platform = accountPlatform;
    const requestId = ++accountSearchRequest.current;
    setSearching(true);
    setError("");
    try {
      const results = await searchPublishers(platform, query);
      if (requestId === accountSearchRequest.current) {
        setAccountResults(
          results.filter((account) => account.platform === platform),
        );
      }
    } catch (searchError) {
      if (requestId === accountSearchRequest.current) {
        setAccountResults([]);
        setError(messageOf(searchError, "发布者搜索失败"));
      }
    } finally {
      if (requestId === accountSearchRequest.current) setSearching(false);
    }
  }

  async function addAccountSource(account: PublisherSearchResult) {
    setSaving(true);
    setError("");
    setNotice("");
    try {
      await createAihotSource({
        platform: account.platform as AccountPlatform,
        external_id: account.external_id,
        name: account.name,
        ...(account.avatar ? { avatar: account.avatar } : {}),
        ...(account.description ? { description: account.description } : {}),
        category,
        ...(notes.trim() ? { notes: notes.trim() } : {}),
      });
      setAccountResults((current) => current.filter((candidate) => candidate.external_id !== account.external_id));
      setNotice(`账号信源「${account.name}」已添加。`);
      setSources(await listAihotSources());
    } catch (saveError) {
      setError(messageOf(saveError, "账号信源添加失败"));
    } finally {
      setSaving(false);
    }
  }

  async function toggleSource(source: AihotSource) {
    setChangingId(source.id);
    setError("");
    try {
      await updateAihotSource(source.id, { enabled: !source.enabled });
      setSources((current) => current.map((candidate) => (
        candidate.id === source.id ? { ...candidate, enabled: !source.enabled } : candidate
      )));
    } catch (updateError) {
      setError(messageOf(updateError, "信源状态更新失败"));
    } finally {
      setChangingId(null);
    }
  }

  async function removeSource(source: AihotSource) {
    if (!window.confirm(`移除信源「${source.name ?? source.source_key ?? source.id}」？`)) return;
    setChangingId(source.id);
    setError("");
    try {
      await deleteAihotSource(source.id);
      setSources((current) => current.filter((candidate) => candidate.id !== source.id));
    } catch (deleteError) {
      setError(messageOf(deleteError, "信源移除失败"));
    } finally {
      setChangingId(null);
    }
  }

  const activeSources = sources.filter((source) => source.enabled).length;
  const budgetRatio = stats && stats.budget > 0
    ? Math.min(1, stats.total_estimated_cost / stats.budget)
    : 0;

  return (
    <section className="min-h-0 flex-1 overflow-y-auto p-3 sm:p-5" aria-label="AIHot 管理">
      <div className="mx-auto max-w-6xl space-y-5">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="font-heading text-base font-semibold">信源与 Provider 运行状况</h3>
            <p className="mt-1 text-xs text-muted-foreground">仅管理员可见；热榜读页面不会触发 Provider 调用。</p>
          </div>
          <Button type="button" variant="ghost" size="icon-sm" aria-label="关闭管理" onClick={onClose}>
            <X />
          </Button>
        </div>

        {error && (
          <div role="alert" className="rounded-md border border-destructive/30 bg-destructive/10 px-3 py-2 text-xs text-destructive">
            管理操作失败：{error}
          </div>
        )}
        {notice && <p role="status" className="text-xs text-emerald-600">{notice}</p>}

        <section className="rounded-xl border bg-card p-4" aria-labelledby="new-aihot-source">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <h4 id="new-aihot-source" className="text-sm font-semibold">添加信源</h4>
              <p className="mt-1 text-xs text-muted-foreground">小红书按关键词发现；公众号和 B站按账号搜索添加。</p>
            </div>
            <select
              aria-label="信源类型"
              value={sourceKind}
              onChange={(event) => {
                accountSearchRequest.current += 1;
                setSourceKind(event.target.value as SourceKind);
                setAccountResults([]);
                setSearching(false);
                setError("");
              }}
              className="h-8 rounded-md border bg-background px-2 text-xs"
            >
              <option value="keyword">关键词</option>
              <option value="account">账号</option>
            </select>
          </div>
          <div className="mt-3 grid gap-2 md:grid-cols-2">
            <select
              aria-label="信源分类"
              value={category}
              onChange={(event) => setCategory(event.target.value as AihotCategory)}
              className="h-8 rounded-md border bg-background px-2 text-sm"
            >
              {CATEGORIES.map((option) => <option key={option.key} value={option.key}>{option.label}</option>)}
            </select>
            <Input
              aria-label="信源备注"
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              placeholder="备注（可选）"
              className="h-8"
            />
          </div>

          {sourceKind === "keyword" ? (
            <div className="mt-2 flex flex-col gap-2 sm:flex-row">
              <Input
                aria-label="小红书采集关键词"
                value={sourceKey}
                onChange={(event) => setSourceKey(event.target.value)}
                placeholder="例如：金融政策"
                className="h-8 flex-1"
              />
              <Button type="button" size="sm" disabled={saving || !sourceKey.trim()} onClick={() => void addKeywordSource()}>
                <Plus />{saving ? "添加中…" : "添加关键词"}
              </Button>
            </div>
          ) : (
            <div className="mt-2">
              <div className="flex flex-col gap-2 sm:flex-row">
                <select
                  aria-label="账号平台"
                  value={accountPlatform}
                  onChange={(event) => {
                    accountSearchRequest.current += 1;
                    setAccountPlatform(event.target.value as AccountPlatform);
                    setAccountResults([]);
                    setSearching(false);
                  }}
                  className="h-8 rounded-md border bg-background px-2 text-sm"
                >
                  <option value="wechat">公众号</option>
                  <option value="bilibili">B站</option>
                </select>
                <Input
                  aria-label="搜索账号信源"
                  value={accountQuery}
                  onChange={(event) => setAccountQuery(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") void searchAccounts();
                  }}
                  placeholder="输入账号名称"
                  className="h-8 flex-1"
                />
                <Button type="button" variant="outline" size="sm" disabled={searching || !accountQuery.trim()} onClick={() => void searchAccounts()}>
                  {searching ? "搜索中…" : "搜索账号"}
                </Button>
              </div>
              {accountResults.length > 0 && (
                <ul className="mt-2 grid gap-2 sm:grid-cols-2">
                  {accountResults.map((account) => (
                    <li key={`${account.platform}-${account.external_id}`} className="flex items-center gap-2 rounded-md border bg-background p-2">
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">{account.name}</p>
                        {account.description && <p className="truncate text-xs text-muted-foreground">{account.description}</p>}
                      </div>
                      <Button type="button" size="sm" disabled={saving} onClick={() => void addAccountSource(account)}>
                        <Plus />添加
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </section>

        <section className="rounded-xl border bg-card p-4" aria-labelledby="aihot-sources">
          <div className="flex items-baseline justify-between gap-2">
            <h4 id="aihot-sources" className="text-sm font-semibold">信源列表</h4>
            <span className="nums text-xs text-muted-foreground">启用 {activeSources}/{sources.length}</span>
          </div>
          {loading ? (
            <p className="py-6 text-center text-xs text-muted-foreground">加载管理数据…</p>
          ) : sources.length === 0 ? (
            <p className="py-6 text-center text-xs text-muted-foreground">尚未配置 AIHot 信源</p>
          ) : (
            <ul className="mt-3 divide-y">
              {sources.map((source) => (
                <li key={source.id} className="flex flex-col gap-3 py-3 sm:flex-row sm:items-center">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="truncate text-sm font-medium">{source.name ?? source.source_key ?? "未命名信源"}</span>
                      <span className="rounded bg-muted px-1.5 py-0.5 text-[11px]">{PLATFORM_LABELS[source.platform] ?? source.platform}</span>
                      <span className="rounded border px-1.5 py-0.5 text-[11px] text-muted-foreground">{CATEGORY_LABELS[source.category] ?? source.category}</span>
                    </div>
                    <p className="nums mt-1 truncate text-[11px] text-muted-foreground">
                      {source.publisher_id ? `发布者 ${source.publisher_id}` : `关键词 ${source.source_key}`}
                      {source.notes ? ` · ${source.notes}` : ""}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      variant={source.enabled ? "secondary" : "outline"}
                      size="sm"
                      aria-pressed={source.enabled}
                      disabled={changingId === source.id}
                      onClick={() => void toggleSource(source)}
                    >
                      {source.enabled ? "已启用" : "已停用"}
                    </Button>
                    <Button
                      type="button"
                      variant="destructive"
                      size="icon-sm"
                      aria-label={`移除信源 ${source.name ?? source.source_key ?? source.id}`}
                      disabled={changingId === source.id}
                      onClick={() => void removeSource(source)}
                    >
                      <Trash2 />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="rounded-xl border bg-card p-4" aria-labelledby="provider-health">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h4 id="provider-health" className="flex items-center gap-2 text-sm font-semibold"><Activity className="size-4" />Provider 运行状况</h4>
            <select
              aria-label="Provider 统计周期"
              value={days}
              onChange={(event) => setDays(Number(event.target.value))}
              className="h-8 rounded-md border bg-background px-2 text-xs"
            >
              <option value={7}>最近 7 天</option>
              <option value={30}>最近 30 天</option>
              <option value={90}>最近 90 天</option>
            </select>
          </div>

          {stats && (
            <>
              <div className={`mt-3 rounded-lg border p-3 ${stats.budget_warning ? "border-amber-500/40 bg-amber-500/10" : "bg-muted/30"}`}>
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
                  <span className="flex items-center gap-1.5 font-medium"><CircleDollarSign className="size-4" />估算成本 {stats.total_estimated_cost.toFixed(2)}</span>
                  <span className="nums text-muted-foreground">预算 {stats.budget.toFixed(2)} · {Math.round(budgetRatio * 100)}%</span>
                </div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted">
                  <div className={`h-full rounded-full ${stats.budget_warning ? "bg-amber-500" : "bg-primary"}`} style={{ width: `${budgetRatio * 100}%` }} />
                </div>
                {stats.budget_warning && <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">当前统计周期估算成本已达到月度预算。</p>}
              </div>

              <div className="mt-3 overflow-x-auto">
                <table className="w-full min-w-[680px] text-left text-xs">
                  <thead className="text-muted-foreground">
                    <tr className="border-b">
                      <th className="px-2 py-2 font-medium">Provider / 平台</th>
                      <th className="px-2 py-2 font-medium">操作</th>
                      <th className="px-2 py-2 text-right font-medium">成功 / 调用</th>
                      <th className="px-2 py-2 text-right font-medium">错误率</th>
                      <th className="px-2 py-2 text-right font-medium">平均延迟</th>
                      <th className="px-2 py-2 text-right font-medium">成本</th>
                    </tr>
                  </thead>
                  <tbody>
                    {stats.groups.map((group) => (
                      <tr key={`${group.provider}-${group.platform}-${group.operation}`} className="border-b last:border-0">
                        <td className="px-2 py-2">{group.provider} · {PLATFORM_LABELS[group.platform] ?? group.platform}</td>
                        <td className="px-2 py-2 text-muted-foreground">{group.operation}</td>
                        <td className="nums px-2 py-2 text-right">{group.calls - group.errors} / {group.calls}</td>
                        <td className={`nums px-2 py-2 text-right ${group.error_rate > 0.1 ? "text-destructive" : ""}`}>{percent(group.error_rate)}</td>
                        <td className="nums px-2 py-2 text-right">{group.avg_elapsed_ms === null ? "—" : `${group.avg_elapsed_ms.toFixed(0)} ms`}</td>
                        <td className="nums px-2 py-2 text-right">{group.estimated_cost.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {stats.groups.length === 0 && <p className="py-6 text-center text-xs text-muted-foreground">该周期尚无 Provider 调用记录</p>}
              </div>
            </>
          )}
        </section>
      </div>
    </section>
  );
}
