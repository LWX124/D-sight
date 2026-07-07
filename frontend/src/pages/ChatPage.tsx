import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { logout } from "@/lib/auth";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { RuntimeProvider } from "@/chat/RuntimeProvider";
import { Thread } from "@/chat/Thread";
import { ThreadListSidebar, threadsKey, type Thread as ThreadT } from "@/chat/ThreadListSidebar";

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

export default function ChatPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [activeThreadId, setActiveThreadId] = useState<string | null>(null);
  const autoCreating = useRef(false);

  const { data: threads } = useQuery({ queryKey: threadsKey, queryFn: listThreads });

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

  // 无选中会话时：有会话则选第一条；无会话则自动建一个（ref 去重，避免并发重复创建）。
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
        onSelect={(id) => setActiveThreadId(id || null)}
      />
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center justify-between border-b border-border px-4 py-2">
          <span className="text-sm font-medium text-foreground">D-sight</span>
          <Button variant="outline" size="sm" onClick={onLogout}>
            退出登录
          </Button>
        </header>
        <div className="min-h-0 flex-1">
          {activeThreadId ? (
            <RuntimeProvider key={activeThreadId} threadId={activeThreadId}>
              <Thread />
            </RuntimeProvider>
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
              正在准备会话…
            </div>
          )}
        </div>
      </main>
    </div>
  );
}
