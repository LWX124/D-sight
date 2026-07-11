import { useEffect, useRef, useState } from "react";
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

export default function SocialPanel() {
  const [creds, setCreds] = useState<Credential[]>([]);
  const [subs, setSubs] = useState<Subscription[]>([]);
  const [keyword, setKeyword] = useState("");
  const [results, setResults] = useState<WechatAccount[]>([]);
  const [activeAcc, setActiveAcc] = useState<string | null>(null);
  const [articles, setArticles] = useState<Article[]>([]);
  const [reading, setReading] = useState<Article | null>(null);
  const [qr, setQr] = useState<{ img: string; session: string } | null>(null);
  const [loginMsg, setLoginMsg] = useState("");
  const [err, setErr] = useState("");
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const hasActiveCred = creds.some((c) => c.status === "active");

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
    if (activeAcc) {
      try {
        await refreshAccount(activeAcc);
        setArticles(await listArticles(activeAcc));
      } catch (e) {
        setErr(String(e));
      }
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
      pollRef.current = setInterval(async () => {
        try {
          const r = await pollLoginStatus(login_session);
          if (r.status === "confirmed") {
            if (pollRef.current) {
              clearInterval(pollRef.current);
              pollRef.current = null;
            }
            setQr(null);
            setLoginMsg(`已登录：${r.nickname}`);
            await reloadCredsAndSubs();
          } else if (r.status === "expired") {
            if (pollRef.current) {
              clearInterval(pollRef.current);
              pollRef.current = null;
            }
            setQr(null);
            setLoginMsg("二维码已过期，请重试");
          } else if (r.status === "failed") {
            if (pollRef.current) {
              clearInterval(pollRef.current);
              pollRef.current = null;
            }
            setQr(null);
            setLoginMsg("登录失败（可能被限流或会话失效），请稍后重试");
          }
        } catch (e) {
          if (pollRef.current) {
            clearInterval(pollRef.current);
            pollRef.current = null;
          }
          setLoginMsg("登录状态查询失败，请稍后重试");
          setErr(String(e));
        }
      }, 2000);
    } catch (e) {
      setErr(String(e));
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-4 p-5">
          {/* 登录区 */}
          <section className="rounded-lg border p-4">
            <div className="mb-2 text-sm font-medium">公众号登录</div>
            {!hasActiveCred && (
              <p className="mb-2 text-xs text-muted-foreground">
                需登录你自己的微信公众号才能使用。你的登录将进入平台共享抓取池，
                可能被用于抓取其他用户订阅的公众号——请知情后再登录。
              </p>
            )}
            <div className="flex flex-wrap items-center gap-2">
              <button type="button" onClick={onLogin} className="rounded bg-primary px-3 py-1.5 text-sm text-primary-foreground">
                扫码登录公众号
              </button>
              {creds.map((c) => (
                <span key={c.id} className={`text-xs ${c.status === "active" ? "text-green-600" : "text-red-500"}`}>
                  {c.nickname}（{c.status === "active" ? "有效" : "已过期，请重登"}）
                </span>
              ))}
            </div>
            {loginMsg && <p className="mt-2 text-xs text-muted-foreground">{loginMsg}</p>}
            {qr && <img src={qr.img} alt="登录二维码" className="mt-2 h-40 w-40" />}
          </section>

          {/* 搜索订阅 */}
          <section className="rounded-lg border p-4">
            <div className="mb-2 text-sm font-medium">搜索公众号</div>
            <div className="flex gap-2">
              <input
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
                placeholder="输入公众号名"
                className="flex-1 rounded border px-2 py-1 text-sm"
              />
              <button type="button" onClick={onSearch} className="rounded border px-3 py-1 text-sm">搜索</button>
            </div>
            <ul className="mt-2 space-y-1">
              {results.map((a) => (
                <li key={a.fakeid} className="flex items-center justify-between text-sm">
                  <span>{a.nickname}</span>
                  <button type="button" onClick={() => onSubscribe(a)} className="text-xs text-primary">订阅</button>
                </li>
              ))}
            </ul>
          </section>

          {/* 订阅 + 文章 */}
          <section className="rounded-lg border p-4">
            <div className="mb-2 flex items-center justify-between">
              <div className="text-sm font-medium">我的订阅</div>
              {activeAcc && <button type="button" onClick={onRefresh} className="text-xs text-primary">刷新</button>}
            </div>
            <div className="flex flex-wrap gap-2">
              {subs.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => openAccount(s.account_id)}
                  className={`rounded border px-2 py-1 text-xs ${activeAcc === s.account_id ? "bg-accent" : ""}`}
                >
                  {s.name}
                </button>
              ))}
            </div>
            <ul className="mt-3 space-y-2">
              {articles.map((art) => (
                <li key={art.id}>
                  <button type="button" onClick={() => openArticle(art.id)} className="text-left text-sm hover:underline">
                    {art.title}
                  </button>
                  <div className="text-xs text-muted-foreground">{new Date(art.published_at).toLocaleString()}</div>
                </li>
              ))}
            </ul>
          </section>

          {/* 阅读 */}
          {reading && (
            <section className="rounded-lg border p-4">
              <div className="mb-2 text-sm font-medium">{reading.title}</div>
              <pre className="whitespace-pre-wrap text-sm">{reading.content ?? "加载中…"}</pre>
              <a href={reading.url} target="_blank" rel="noreferrer" className="mt-2 inline-block text-xs text-primary">
                原文链接
              </a>
            </section>
          )}

          {err && <p className="text-xs text-red-500">{err}</p>}
        </div>
      </div>
    </div>
  );
}
