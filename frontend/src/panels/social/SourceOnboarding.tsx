import { useEffect, useState } from "react";
import { Check, Link2, QrCode, Search } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  type Credential,
  type WechatAccount,
  type WeiboAccount,
  getWeiboCredential,
  listCredentials,
  pollLoginStatus,
  previewWeiboAccount,
  searchAccounts,
  startLoginQrcode,
  subscribe,
  subscribeWeibo,
} from "@/lib/social";

type SourceEntryProps = {
  onIntegrated: () => void | Promise<void>;
  onError: (message: string) => void;
};

function messageOf(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export function WeiboProfileEntry({ onIntegrated, onError }: SourceEntryProps) {
  const [profileUrl, setProfileUrl] = useState("");
  const [preview, setPreview] = useState<WeiboAccount | null>(null);
  const [credentialReady, setCredentialReady] = useState<boolean | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    let active = true;
    void getWeiboCredential()
      .then((credential) => {
        if (active) setCredentialReady(credential.status === "active");
      })
      .catch(() => {
        if (active) setCredentialReady(false);
      });
    return () => {
      active = false;
    };
  }, []);

  async function loadPreview() {
    const value = profileUrl.trim();
    if (!value) return;
    setBusy(true);
    setMessage("");
    try {
      setPreview(await previewWeiboAccount(value));
    } catch (error) {
      setPreview(null);
      onError(messageOf(error, "微博账号预览失败"));
    } finally {
      setBusy(false);
    }
  }

  async function confirm() {
    if (!preview) return;
    setBusy(true);
    setMessage("");
    try {
      const legacy = await subscribeWeibo(preview.account_id);
      setMessage(
        legacy.initial_sync_status === "cooldown"
          ? "微博订阅已接入；当前风控冷却，动态将在恢复后同步。"
          : `微博订阅已接入，首次获取 ${legacy.added} 条动态。`,
      );
      setPreview(null);
      setProfileUrl("");
      await onIntegrated();
    } catch (error) {
      onError(messageOf(error, "微博订阅失败"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-3 rounded-lg border bg-muted/20 p-3" aria-label="添加微博账号">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Link2 className="size-4" />通过主页链接添加微博账号
      </div>
      <p className="mt-1 text-xs text-muted-foreground">
        {credentialReady === false
          ? "系统微博登录态尚未就绪，请联系管理员配置后再试。"
          : "粘贴包含数字 UID 的微博主页链接，预览确认后接入统一订阅。"}
      </p>
      <div className="mt-2 flex flex-col gap-2 sm:flex-row">
        <Input
          aria-label="微博主页链接"
          value={profileUrl}
          onChange={(event) => setProfileUrl(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void loadPreview();
          }}
          placeholder="https://weibo.com/u/1234567890"
          className="h-8 flex-1"
        />
        <Button
          type="button"
          variant="outline"
          size="sm"
          disabled={busy || !profileUrl.trim()}
          onClick={() => void loadPreview()}
        >
          预览账号
        </Button>
      </div>
      {preview && (
        <div className="mt-3 flex flex-col gap-2 rounded-md border bg-background p-3 sm:flex-row sm:items-center">
          {preview.avatar ? (
            <img src={preview.avatar} alt="" className="size-10 rounded-full object-cover" />
          ) : (
            <span className="flex size-10 items-center justify-center rounded-full bg-muted text-sm">
              {preview.name.slice(0, 1)}
            </span>
          )}
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium">{preview.name}</p>
            <p className="text-xs text-muted-foreground">UID {preview.uid}</p>
            {preview.description && <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{preview.description}</p>}
          </div>
          <Button type="button" size="sm" disabled={busy} onClick={() => void confirm()}>
            <Check />确认订阅
          </Button>
        </div>
      )}
      {message && <p role="status" className="mt-2 text-xs text-emerald-600">{message}</p>}
    </section>
  );
}

const TERMINAL_LOGIN_STATES = new Set(["confirmed", "expired", "no_account", "no_email", "failed"]);

function loginStatusText(status: string): string {
  if (status === "waiting") return "等待扫码";
  if (status === "scanned") return "已扫码，请在手机上确认";
  if (status === "confirmed") return "登录成功";
  if (status === "no_account") return "该微信没有可登录的公众号";
  if (status === "no_email") return "该公众号尚未绑定邮箱";
  if (status === "expired") return "二维码已过期，请重新生成";
  return "登录失败，请重试";
}

export function WechatFallbackEntry({ onIntegrated, onError }: SourceEntryProps) {
  const [credentials, setCredentials] = useState<Credential[]>([]);
  const [loginSession, setLoginSession] = useState<string | null>(null);
  const [qrcode, setQrcode] = useState<string | null>(null);
  const [loginStatus, setLoginStatus] = useState<string>("");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<WechatAccount[]>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function reloadCredentials() {
    setCredentials(await listCredentials());
  }

  useEffect(() => {
    void reloadCredentials().catch((error: unknown) => {
      onError(messageOf(error, "公众号凭证状态加载失败"));
    });
  }, [onError]);

  useEffect(() => {
    if (!loginSession) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const result = await pollLoginStatus(loginSession);
        if (!active) return;
        setLoginStatus(result.status);
        if (result.status === "confirmed") {
          setLoginSession(null);
          setQrcode(null);
          await reloadCredentials();
          setMessage(`公众号登录成功${result.nickname ? `：${result.nickname}` : ""}`);
          return;
        }
        if (!TERMINAL_LOGIN_STATES.has(result.status)) {
          timer = setTimeout(() => void poll(), 1500);
        }
      } catch (error) {
        if (active) onError(messageOf(error, "扫码状态检查失败"));
      }
    };
    void poll();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [loginSession, onError]);

  async function startLogin() {
    setBusy(true);
    setMessage("");
    try {
      const result = await startLoginQrcode();
      setLoginSession(result.login_session);
      setQrcode(result.qrcode);
      setLoginStatus("waiting");
    } catch (error) {
      onError(messageOf(error, "公众号二维码生成失败"));
    } finally {
      setBusy(false);
    }
  }

  async function searchLegacyAccounts() {
    const keyword = query.trim();
    if (!keyword) return;
    setBusy(true);
    try {
      setResults(await searchAccounts(keyword));
    } catch (error) {
      onError(messageOf(error, "公众号备用搜索失败"));
    } finally {
      setBusy(false);
    }
  }

  async function integrate(account: WechatAccount) {
    setBusy(true);
    setMessage("");
    try {
      await subscribe({ fakeid: account.fakeid, name: account.nickname, avatar: account.avatar });
      setResults((current) => current.filter((candidate) => candidate.fakeid !== account.fakeid));
      setMessage(`已通过扫码备用链路接入「${account.nickname}」`);
      await onIntegrated();
    } catch (error) {
      onError(messageOf(error, "公众号订阅失败"));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-3 rounded-lg border bg-muted/20 p-3" aria-label="公众号扫码备用入口">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="flex items-center gap-2 text-sm font-medium"><QrCode className="size-4" />公众号扫码备用入口</div>
          <p className="mt-1 text-xs text-muted-foreground">RedFox 搜索不可用时，用公众号后台扫码登录后搜索账号。</p>
        </div>
        <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void startLogin()}>
          生成登录二维码
        </Button>
      </div>

      {credentials.length > 0 && (
        <p className="mt-2 text-xs text-emerald-600">
          可用凭证：{credentials.filter((credential) => credential.status === "active").map((credential) => credential.nickname).join("、") || "暂无有效凭证"}
        </p>
      )}
      {qrcode && (
        <div className="mt-3 flex items-center gap-3 rounded-md border bg-background p-3">
          <img src={qrcode} alt="公众号登录二维码" className="size-28 rounded-md border object-contain" />
          <p role="status" className="text-xs text-muted-foreground">{loginStatusText(loginStatus)}</p>
        </div>
      )}

      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <Input
          aria-label="备用搜索公众号"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void searchLegacyAccounts();
          }}
          placeholder="输入公众号名称"
          className="h-8 flex-1"
        />
        <Button type="button" variant="outline" size="sm" disabled={busy || !query.trim()} onClick={() => void searchLegacyAccounts()}>
          <Search />备用搜索
        </Button>
      </div>
      {results.length > 0 && (
        <ul className="mt-3 grid gap-2 sm:grid-cols-2">
          {results.map((account) => (
            <li key={account.fakeid} className="flex items-center gap-2 rounded-md border bg-background p-2">
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium">{account.nickname}</p>
                {account.signature && <p className="truncate text-xs text-muted-foreground">{account.signature}</p>}
              </div>
              <Button type="button" variant="ghost" size="sm" disabled={busy} onClick={() => void integrate(account)}>
                接入
              </Button>
            </li>
          ))}
        </ul>
      )}
      {message && <p role="status" className="mt-2 text-xs text-emerald-600">{message}</p>}
    </section>
  );
}
