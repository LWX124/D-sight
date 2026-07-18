import { useEffect, useRef, useState } from "react";
import { RefreshCw, Search, Send, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  type Article,
  type Credential,
  type Subscription,
  type WechatAccount,
  getArticle,
  listArticles,
  listCredentials,
  listSubscriptions,
  pollLoginStatus,
  refreshAccount,
  searchAccounts,
  startLoginQrcode,
  subscribe,
} from "@/lib/social";

const SOURCE_TABS = [{ key: "wechat", label: "微信公众号" }] as const;
type SourceKey = (typeof SOURCE_TABS)[number]["key"];

export default function SocialPanel() {
  const [activeTab, setActiveTab] = useState<SourceKey>("wechat");

  return (
    <div className="flex h-full flex-col">
      <div role="tablist" className="flex gap-1 border-b px-5 pt-2">
        {SOURCE_TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={activeTab === t.key}
            onClick={() => setActiveTab(t.key)}
            className={`rounded-t border-b-2 px-3 py-1.5 text-sm transition-colors ${
              activeTab === t.key
                ? "border-primary font-medium text-foreground"
                : "border-transparent text-muted-foreground hover:text-foreground"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {activeTab === "wechat" && <WechatTab />}
    </div>
  );
}

function WechatTab() {
  const [creds, setCreds] = useState<Credential[]>([]);
  const [subs, setSubs] = useState<Subscription[]>([]);
  const [keyword, setKeyword] = useState("");
  const [results, setResults] = useState<WechatAccount[]>([]);
  const [activeAcc, setActiveAcc] = useState<string | null>(null);
  const [articles, setArticles] = useState<Article[]>([]);
  const [reading, setReading] = useState<Article | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [qr, setQr] = useState<{ img: string; session: string } | null>(null);
  const [loginMsg, setLoginMsg] = useState("");
  const [err, setErr] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const hasActiveCred = creds.some((c) => c.status === "active");
  const activeSub = subs.find((s) => s.account_id === activeAcc) ?? null;

  async function reloadCredsAndSubs() {
    setCreds(await listCredentials());
    setSubs(await listSubscriptions());
  }
  useEffect(() => {
    reloadCredsAndSubs().catch((e) => setErr(String(e)));
  }, []);

  useEffect(() => {
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  async function onSearch() {
    setErr("");
    try {
      setResults(await searchAccounts(keyword));
    } catch (e) {
      setErr(String(e));
    }
  }

  async function onSubscribe(a: WechatAccount) {
    try {
      await subscribe({ fakeid: a.fakeid, name: a.nickname, avatar: a.avatar });
      setSubs(await listSubscriptions());
      setResults([]);
      setKeyword("");
    } catch (e) {
      setErr(String(e));
    }
  }

  async function openAccount(accountId: string) {
    try {
      setActiveAcc(accountId);
      setReading(null);
      setArticles(await listArticles(accountId));
    } catch (e) {
      setErr(String(e));
    }
  }

  async function openArticle(id: string) {
    try {
      setReading(await getArticle(id)); // 懒抓正文
    } catch (e) {
      setErr(String(e));
    }
  }

  async function onRefresh() {
    if (!activeAcc || refreshing) return;
    setRefreshing(true);
    try {
      await refreshAccount(activeAcc);
      setArticles(await listArticles(activeAcc));
    } catch (e) {
      setErr(String(e));
    } finally {
      setRefreshing(false);
    }
  }

  async function onLogin() {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    try {
      setLoginMsg("请用微信扫码并在手机上确认");
      const { qrcode, login_session } = await startLoginQrcode();
      setQr({ img: qrcode, session: login_session });
      const stopPolling = () => {
        if (pollRef.current) {
          clearInterval(pollRef.current);
          pollRef.current = null;
        }
      };
      const FINAL_MSG: Record<string, string> = {
        confirmed: "", // 单独处理（带昵称）
        expired: "二维码已过期，请重试",
        failed: "登录失败（可能被限流或会话失效），请稍后重试",
        no_account: "该微信账号没有可登录的公众号（需为公众号的管理员/运营者）",
        no_email: "该公众号账号未绑定邮箱，无法扫码登录",
      };
      pollRef.current = setInterval(async () => {
        try {
          const r = await pollLoginStatus(login_session);
          if (r.status === "scanned") {
            setLoginMsg("已扫码，请在手机上点击确认");
          } else if (r.status === "confirmed") {
            stopPolling();
            setQr(null);
            setLoginMsg(`已登录：${r.nickname}`);
            await reloadCredsAndSubs();
          } else if (r.status in FINAL_MSG) {
            stopPolling();
            setQr(null);
            setLoginMsg(FINAL_MSG[r.status]);
          }
        } catch (e) {
          stopPolling();
          setLoginMsg("登录状态查询失败，请稍后重试");
          setErr(String(e));
        }
      }, 2000);
    } catch (e) {
      setErr(String(e));
    }
  }

  return (
    <div className="flex min-h-0 flex-1">
      {/* 左栏：订阅列表 + 登录区 */}
      <aside className="flex w-64 shrink-0 flex-col border-r">
        <div className="border-b p-3">
          <div className="mb-2 text-sm font-medium">我的订阅</div>
          <div className="flex gap-1.5">
            <Input
              value={keyword}
              onChange={(e) => setKeyword(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") onSearch();
              }}
              placeholder="搜索公众号"
              className="h-8 text-sm"
            />
            <Button type="button" variant="outline" size="icon" className="h-8 w-8 shrink-0" onClick={onSearch} aria-label="搜索">
              <Search className="h-4 w-4" />
            </Button>
          </div>
          {results.length > 0 && (
            <ul className="mt-2 space-y-1 rounded-md border p-1.5">
              {results.map((a) => (
                <li key={a.fakeid} className="flex items-center justify-between gap-2 rounded px-1.5 py-1 text-sm">
                  <span className="truncate">{a.nickname}</span>
                  <button
                    type="button"
                    onClick={() => onSubscribe(a)}
                    className="shrink-0 text-xs text-primary hover:underline"
                  >
                    订阅
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <nav className="min-h-0 flex-1 overflow-y-auto p-2">
          {subs.length === 0 ? (
            <p className="px-2 py-6 text-center text-xs text-muted-foreground">
              还没有订阅，先在上方搜索公众号
            </p>
          ) : (
            <ul className="space-y-0.5">
              {subs.map((s) => (
                <li key={s.id}>
                  <button
                    type="button"
                    onClick={() => openAccount(s.account_id)}
                    className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors ${
                      activeAcc === s.account_id
                        ? "bg-accent font-medium text-accent-foreground"
                        : "text-foreground/80 hover:bg-accent/50"
                    }`}
                  >
                    {s.avatar ? (
                      <img
                        src={s.avatar}
                        alt=""
                        referrerPolicy="no-referrer"
                        className="h-6 w-6 shrink-0 rounded-md object-cover"
                      />
                    ) : (
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-muted text-xs text-muted-foreground">
                        {s.name.slice(0, 1)}
                      </span>
                    )}
                    <span className="truncate">{s.name}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </nav>

        {/* 登录区：有有效凭证时收起为状态行 */}
        <div className="border-t p-3">
          <div className="mb-1.5 text-xs font-medium text-muted-foreground">公众号登录</div>
          {creds.map((c) => (
            <div key={c.id} className="flex items-center gap-1.5 text-xs">
              <span
                className={`h-1.5 w-1.5 rounded-full ${c.status === "active" ? "bg-green-500" : "bg-red-500"}`}
              />
              <span className="truncate">{c.nickname}</span>
              <span className="shrink-0 text-muted-foreground">
                {c.status === "active" ? "有效" : "已过期，请重登"}
              </span>
            </div>
          ))}
          {!hasActiveCred && (
            <>
              <p className="mb-2 mt-1 text-xs leading-5 text-muted-foreground">
                需登录你自己的微信公众号才能使用。你的登录将进入平台共享抓取池，
                可能被用于抓取其他用户订阅的公众号——请知情后再登录。
              </p>
              <Button type="button" size="sm" className="w-full" onClick={onLogin}>
                扫码登录公众号
              </Button>
            </>
          )}
          {loginMsg && <p className="mt-2 text-xs text-muted-foreground">{loginMsg}</p>}
          {qr && <img src={qr.img} alt="登录二维码" className="mt-2 h-40 w-40 rounded-md border" />}
        </div>
      </aside>

      {/* 右侧：文章列表 + 分屏正文 + 底部聊天框 */}
      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex min-h-0 flex-1">
          {/* 文章列表 */}
          <section
            className={`flex min-h-0 flex-col ${reading ? "w-80 shrink-0 border-r" : "min-w-0 flex-1"}`}
          >
            <div className="flex h-11 shrink-0 items-center justify-between border-b px-4">
              <div className="truncate text-sm font-medium">{activeSub ? activeSub.name : "文章"}</div>
              {activeAcc && (
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 gap-1.5 px-2 text-xs"
                  onClick={onRefresh}
                  disabled={refreshing}
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? "animate-spin" : ""}`} />
                  刷新
                </Button>
              )}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-3">
              {!activeAcc ? (
                <p className="py-10 text-center text-sm text-muted-foreground">在左侧选择一个订阅查看文章</p>
              ) : articles.length === 0 ? (
                <p className="py-10 text-center text-sm text-muted-foreground">暂无文章，点右上角"刷新"抓取</p>
              ) : (
                <ul className={`grid gap-2.5 ${reading ? "grid-cols-1" : "grid-cols-1 lg:grid-cols-2"}`}>
                  {articles.map((art) => (
                    <li key={art.id}>
                      <button
                        type="button"
                        onClick={() => openArticle(art.id)}
                        className={`flex w-full gap-3 rounded-lg border p-3 text-left transition-colors hover:bg-accent/50 ${
                          reading?.id === art.id ? "border-primary/50 bg-accent/50" : ""
                        }`}
                      >
                        <div className="min-w-0 flex-1">
                          <div className="line-clamp-2 text-sm font-medium leading-snug">{art.title}</div>
                          {art.digest && (
                            <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted-foreground">{art.digest}</p>
                          )}
                          <div className="mt-1.5 text-xs tabular-nums text-muted-foreground">
                            {new Date(art.published_at).toLocaleString()}
                          </div>
                        </div>
                        {art.cover_url && (
                          <img
                            src={art.cover_url}
                            alt=""
                            referrerPolicy="no-referrer"
                            className="h-14 w-14 shrink-0 rounded-md border object-cover"
                          />
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>

          {/* 分屏正文 */}
          {reading && (
            <section className="flex min-h-0 min-w-0 flex-1 flex-col">
              <div className="flex h-11 shrink-0 items-center justify-between gap-2 border-b px-4">
                <div className="truncate text-sm font-medium">{reading.title}</div>
                <div className="flex shrink-0 items-center gap-1">
                  <a
                    href={reading.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-xs text-primary hover:underline"
                  >
                    原文链接
                  </a>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7"
                    onClick={() => setReading(null)}
                    aria-label="关闭正文"
                  >
                    <X className="h-4 w-4" />
                  </Button>
                </div>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto px-6 py-5">
                <h2 className="text-lg font-semibold leading-snug">{reading.title}</h2>
                <div className="mt-1 text-xs tabular-nums text-muted-foreground">
                  {new Date(reading.published_at).toLocaleString()}
                </div>
                <pre className="mt-4 max-w-[65ch] whitespace-pre-wrap font-sans text-sm leading-7">
                  {reading.content ?? "加载中…"}
                </pre>
              </div>
            </section>
          )}
        </div>

        {err && (
          <p className="border-t px-4 py-1.5 text-xs text-red-500" role="alert">
            {err}
          </p>
        )}

        {/* 底部聊天框（占位，暂未接入） */}
        <div className="shrink-0 border-t p-3">
          <div className="flex items-center gap-2">
            <Input placeholder="向 AI 提问当前文章（即将上线）" disabled className="h-9 text-sm" />
            <Button type="button" size="icon" className="h-9 w-9 shrink-0" disabled aria-label="发送">
              <Send className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}
