import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Library, MessageSquare, Newspaper, Pencil, Plus, Store, Trash2 } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { cn } from "@/lib/utils";

export type Thread = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

export type Panel = "chat" | "news" | "social" | "kb" | "skills";

export const threadsKey = ["threads"] as const;

async function listThreads(): Promise<Thread[]> {
  const r = await apiFetch("/api/threads/");
  if (!r.ok) throw new Error("加载会话失败");
  return r.json();
}

async function createThread(): Promise<Thread> {
  const r = await apiFetch("/api/threads/", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({}),
  });
  if (!r.ok) throw new Error("新建会话失败");
  return r.json();
}

async function renameThread(id: string, title: string): Promise<Thread> {
  const r = await apiFetch(`/api/threads/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
  if (!r.ok) throw new Error("重命名失败");
  return r.json();
}

async function deleteThread(id: string): Promise<void> {
  const r = await apiFetch(`/api/threads/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error("删除失败");
}

const NAV_ITEMS: { panel: Panel; icon: typeof MessageSquare; label: string; testId: string }[] = [
  { panel: "chat", icon: MessageSquare, label: "对话", testId: "nav-chat" },
  { panel: "news", icon: Newspaper, label: "7x24h", testId: "nav-news" },
  { panel: "social", icon: Newspaper, label: "社媒信息", testId: "nav-social" },
  { panel: "kb", icon: Library, label: "知识库", testId: "nav-kb" },
  { panel: "skills", icon: Store, label: "技能市场", testId: "nav-skills" },
];

export function ThreadListSidebar({
  activeThreadId,
  activePanel,
  onSelect,
  onPanelChange,
}: {
  activeThreadId: string | null;
  activePanel: Panel;
  onSelect: (id: string) => void;
  onPanelChange: (panel: Panel) => void;
}) {
  const qc = useQueryClient();
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");

  const { data: threads = [], isLoading } = useQuery({
    queryKey: threadsKey,
    queryFn: listThreads,
  });

  const create = useMutation({
    mutationFn: createThread,
    onSuccess: (t) => {
      qc.invalidateQueries({ queryKey: threadsKey });
      onSelect(t.id);
      onPanelChange("chat");
    },
  });

  const rename = useMutation({
    mutationFn: ({ id, title }: { id: string; title: string }) => renameThread(id, title),
    onSuccess: () => qc.invalidateQueries({ queryKey: threadsKey }),
  });

  const remove = useMutation({
    mutationFn: deleteThread,
    onSuccess: (_data, id) => {
      qc.invalidateQueries({ queryKey: threadsKey });
      if (id === activeThreadId) onSelect("");
    },
  });

  function commitRename(id: string) {
    const title = draft.trim();
    setEditingId(null);
    if (title) rename.mutate({ id, title });
  }

  return (
    <aside className="flex h-svh w-60 shrink-0 flex-col border-r border-border bg-sidebar">
      {/* Logo / Brand */}
      <div className="flex items-center gap-2 px-4 py-4">
        <div className="flex size-7 items-center justify-center rounded-lg bg-primary text-primary-foreground">
          <span className="text-xs font-semibold">D</span>
        </div>
        <span className="text-sm font-semibold tracking-tight text-foreground">D-sight</span>
      </div>

      {/* Navigation */}
      <nav className="space-y-0.5 px-2">
        {NAV_ITEMS.map(({ panel, icon: Icon, label, testId }) => (
          <button
            key={panel}
            type="button"
            data-testid={testId}
            onClick={() => onPanelChange(panel)}
            className={cn(
              "flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-[13px] font-medium transition-colors",
              activePanel === panel
                ? "bg-sidebar-accent text-sidebar-accent-foreground"
                : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground",
            )}
          >
            <Icon className="size-4" />
            {label}
          </button>
        ))}
      </nav>

      {/* Divider + Thread list */}
      <div className="mx-3 my-3 border-t border-sidebar-border" />

      <div className="flex items-center justify-between px-3 pb-1.5">
        <span className="text-[11px] font-medium uppercase tracking-wider text-sidebar-foreground/50">
          会话
        </span>
        <button
          type="button"
          onClick={() => create.mutate()}
          disabled={create.isPending}
          className="rounded-md p-0.5 text-sidebar-foreground/50 transition-colors hover:bg-sidebar-accent hover:text-sidebar-foreground"
        >
          <Plus className="size-3.5" />
        </button>
      </div>

      <div className="flex-1 space-y-0.5 overflow-y-auto px-2 pb-3">
        {isLoading && <p className="px-2 py-1 text-xs text-muted-foreground">加载中…</p>}
        {!isLoading && threads.length === 0 && (
          <p className="px-2 py-1 text-xs text-muted-foreground">暂无会话</p>
        )}
        {threads.map((t) => {
          const active = t.id === activeThreadId && activePanel === "chat";
          return (
            <div
              key={t.id}
              className={cn(
                "group flex items-center gap-1 rounded-lg px-2.5 py-1.5 text-[13px]",
                active
                  ? "bg-sidebar-accent text-sidebar-accent-foreground"
                  : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50",
              )}
            >
              {editingId === t.id ? (
                <input
                  autoFocus
                  className="min-w-0 flex-1 rounded border border-input bg-background px-1 py-0.5 text-xs outline-none"
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onBlur={() => commitRename(t.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") commitRename(t.id);
                    if (e.key === "Escape") setEditingId(null);
                  }}
                />
              ) : (
                <button
                  type="button"
                  className="min-w-0 flex-1 truncate text-left"
                  title={t.title}
                  onClick={() => {
                    onSelect(t.id);
                    onPanelChange("chat");
                  }}
                  onDoubleClick={() => {
                    setEditingId(t.id);
                    setDraft(t.title);
                  }}
                >
                  {t.title}
                </button>
              )}
              <button
                type="button"
                aria-label="重命名"
                className="hidden shrink-0 rounded p-0.5 text-muted-foreground hover:text-foreground group-hover:block"
                onClick={() => {
                  setEditingId(t.id);
                  setDraft(t.title);
                }}
              >
                <Pencil className="size-3" />
              </button>
              <button
                type="button"
                aria-label="删除"
                className="hidden shrink-0 rounded p-0.5 text-muted-foreground hover:text-destructive group-hover:block"
                onClick={() => {
                  if (confirm(`删除会话「${t.title}」？`)) remove.mutate(t.id);
                }}
              >
                <Trash2 className="size-3" />
              </button>
            </div>
          );
        })}
      </div>
    </aside>
  );
}
