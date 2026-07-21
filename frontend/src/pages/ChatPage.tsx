import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { logout } from "@/lib/auth";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { RuntimeProvider } from "@/chat/RuntimeProvider";
import { Thread } from "@/chat/Thread";
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

async function createThread(): Promise<ThreadT> {
  const r = await apiFetch("/api/threads/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!r.ok) throw new Error("新建会话失败");
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
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const [activePanel, setActivePanel] = useState<Panel>("chat");
  const [creditNotice, setCreditNotice] = useState(false);
  const autoCreating = useRef(false);

  const { data: threads } = useQuery({ queryKey: threadsKey, queryFn: listThreads });
  const { data: credits } = useQuery({ queryKey: creditsKey, queryFn: fetchCredits });

  const autoCreate = useMutation({
    mutationFn: createThread,
    onSuccess: (t) => {
      qc.invalidateQueries({ queryKey: threadsKey });
      setActiveThreadId(t.id);
      autoCreating.current = false;
    },
    onError: () => {
      autoCreating.current = false;
    },
  });

  useEffect(() => {
    if (!threads) return;
    const stillExists = activeThreadId && threads.some((t) => t.id === activeThreadId);
    if (stillExists) return;
    if (threads.length > 0) {
      setActiveThreadId(threads[0].id);
    } else if (!autoCreating.current) {
      autoCreating.current = true;
      autoCreate.mutate();
    }
  }, [threads, activeThreadId, autoCreate]);

  async function onLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="flex h-svh bg-background">
      <ThreadListSidebar
        activeThreadId={activeThreadId}
        activePanel={activePanel}
        onSelect={(id) => setActiveThreadId(id || null)}
        onPanelChange={setActivePanel}
      />
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 items-center justify-between border-b border-border px-5">
          <span className="text-sm font-medium text-foreground">
            {PANEL_TITLES[activePanel]}
          </span>
          <div className="flex items-center gap-3">
            {activePanel === "chat" && <KbMountSelector />}
            {credits && (
              <span
                data-testid="credit-badge"
                className="text-xs text-muted-foreground tabular-nums"
              >
                {credits.balance}/{credits.monthly_quota}
              </span>
            )}
            <Button variant="ghost" size="sm" onClick={onLogout}>
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
        <div className="min-h-0 flex-1">
          {activePanel === "chat" && (
            <>
              {activeThreadId ? (
                <RuntimeProvider
                  key={activeThreadId}
                  threadId={activeThreadId}
                  onSendResponse={(status) => setCreditNotice(status === 402)}
                  onFinish={() => {
                    qc.invalidateQueries({ queryKey: creditsKey });
                  }}
                >
                  <Thread />
                </RuntimeProvider>
              ) : (
                <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                  正在准备会话…
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
