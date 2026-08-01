import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { logout } from "@/lib/auth";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { RuntimeProvider } from "@/chat/RuntimeProvider";
import { DraftThreadComposer, Thread } from "@/chat/Thread";
import { ThreadListSidebar, threadsKey, type Panel, type Thread as ThreadT } from "@/chat/ThreadListSidebar";
import { KbMountSelector } from "@/chat/KbMountSelector";
import { creditsKey, fetchCredits } from "@/lib/credits";
import NewsPanel from "@/panels/NewsPanel";
import SocialPanel from "@/panels/SocialPanel";
import KbPanel from "@/panels/KbPanel";
import SkillsPanel from "@/panels/SkillsPanel";
import FundArbPanel from "@/panels/FundArbPanel";

async function listThreads(): Promise<ThreadT[]> {
  const r = await apiFetch("/api/threads/");
  if (!r.ok) throw new Error("加载会话失败");
  return r.json();
}

const PANEL_TITLES: Record<Panel, string> = {
  chat: "对话",
  news: "7x24h",
  social: "社媒信息",
  kb: "知识库",
  skills: "技能市场",
  fund_arb: "基金套利",
};

export default function ChatPage() {
  const { threadId } = useParams<{ threadId?: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [activePanel, setActivePanel] = useState<Panel>("chat");
  const [creditNotice, setCreditNotice] = useState(false);
  const [isCreatingThread, setIsCreatingThread] = useState(false);
  const [createError, setCreateError] = useState<string | null>(null);
  const createLockRef = useRef(false);
  const pendingMessageRef = useRef<string | null>(null);

  const isDraft = threadId === "new" || threadId === undefined;
  const isValidThreadId = Boolean(threadId && threadId !== "new" && /^[0-9a-f-]{36}$/i.test(threadId));
  const activeThreadId = isValidThreadId && threadId ? threadId : null;

  useQuery({ queryKey: threadsKey, queryFn: listThreads });
  const { data: credits } = useQuery({ queryKey: creditsKey, queryFn: fetchCredits });
  useEffect(() => {
    if (threadId && threadId !== "new" && !isValidThreadId) {
      navigate("/chat/new", { replace: true });
    }
  }, [isValidThreadId, navigate, threadId]);

  useQuery({
    queryKey: ["thread", threadId],
    queryFn: async () => {
      if (!isValidThreadId) return null;
      const r = await apiFetch(`/api/threads/${threadId}`);
      if (!r.ok) {
        if (r.status === 404) {
          navigate("/chat/new", { replace: true });
          return null;
        }
        throw new Error("加载会话失败");
      }
      return r.json();
    },
    enabled: isValidThreadId,
  });

  async function onLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  function onThreadSelect(id: string) {
    pendingMessageRef.current = null;
    if (id) navigate(`/chat/${id}`);
    else navigate("/chat/new");
  }

  async function onFirstSend(message: string) {
    if (createLockRef.current) return;
    createLockRef.current = true;
    setIsCreatingThread(true);
    setCreateError(null);

    try {
      const r = await apiFetch("/api/threads/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      if (!r.ok) throw new Error("创建会话失败");

      const thread = (await r.json()) as ThreadT;
      pendingMessageRef.current = message;
      await qc.invalidateQueries({ queryKey: threadsKey });
      navigate(`/chat/${thread.id}`, { replace: true });
    } catch (error) {
      setCreateError(error instanceof Error ? error.message : "创建会话失败");
    } finally {
      createLockRef.current = false;
      setIsCreatingThread(false);
    }
  }

  return (
    <div className="flex h-svh bg-background">
      <ThreadListSidebar
        activeThreadId={activeThreadId}
        activePanel={activePanel}
        onSelect={onThreadSelect}
        onPanelChange={setActivePanel}
      />
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 items-center justify-between border-b border-border bg-card/40 px-5 backdrop-blur">
          <div className="flex items-center gap-2.5">
            <span className="size-1 rounded-full bg-primary shadow-[0_0_6px_var(--color-primary)]" />
            <span className="nums text-[11px] font-medium uppercase tracking-[0.22em] text-foreground">
              {PANEL_TITLES[activePanel]}
            </span>
          </div>
          <div className="flex items-center gap-3">
            {activePanel === "chat" && <KbMountSelector />}
            {credits && (
              <span
                data-testid="credit-badge"
                className="nums rounded-md border border-primary/30 bg-primary/5 px-2 py-0.5 text-[11px] text-primary"
              >
                {credits.balance}/{credits.monthly_quota}
              </span>
            )}
            <Button variant="ghost" size="sm" onClick={onLogout} className="cursor-pointer">
              退出
            </Button>
          </div>
        </header>
        {creditNotice && (
          <div
            data-testid="credit-notice"
            className="border-b border-destructive/30 bg-destructive/10 px-4 py-2 text-xs text-destructive"
          >
            积分不足，请联系管理员或等待月初重置
          </div>
        )}
        <div className="min-h-0 flex-1 animate-fade-up" key={activePanel}>
          {activePanel === "chat" && (
            <>
              {!isDraft && isValidThreadId ? (
                <RuntimeProvider
                  key={threadId}
                  threadId={threadId}
                  onSendResponse={(status) => setCreditNotice(status === 402)}
                  onFinish={() => {
                    pendingMessageRef.current = null;
                    qc.invalidateQueries({ queryKey: creditsKey });
                  }}
                  initialMessage={pendingMessageRef.current}
                >
                  <Thread />
                </RuntimeProvider>
              ) : isDraft ? (
                <DraftThreadComposer
                  isCreating={isCreatingThread}
                  error={createError}
                  onSend={(message) => void onFirstSend(message)}
                />
              ) : (
                <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                  正在加载会话…
                </div>
              )}
            </>
          )}
          {activePanel === "news" && <NewsPanel />}
          {activePanel === "social" && <SocialPanel />}
          {activePanel === "kb" && <KbPanel />}
          {activePanel === "skills" && <SkillsPanel />}
          {activePanel === "fund_arb" && <FundArbPanel />}
        </div>
      </main>
    </div>
  );
}
