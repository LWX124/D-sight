import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Library, Pencil, Plus, Store, Trash2 } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export type Thread = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
};

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

export function ThreadListSidebar({
  activeThreadId,
  onSelect,
}: {
  activeThreadId: string | null;
  onSelect: (id: string) => void;
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
    <aside className="flex h-svh w-64 shrink-0 flex-col border-r border-border bg-muted/30">
      <div className="p-3">
        <Button
          className="w-full justify-start gap-2"
          onClick={() => create.mutate()}
          disabled={create.isPending}
        >
          <Plus className="size-4" />
          新建会话
        </Button>
      </div>
      <nav className="flex-1 space-y-1 overflow-y-auto px-2 pb-3">
        {isLoading && <p className="px-2 py-1 text-sm text-muted-foreground">加载中…</p>}
        {!isLoading && threads.length === 0 && (
          <p className="px-2 py-1 text-sm text-muted-foreground">暂无会话</p>
        )}
        {threads.map((t) => {
          const active = t.id === activeThreadId;
          return (
            <div
              key={t.id}
              className={cn(
                "group flex items-center gap-1 rounded-lg px-2 py-1.5 text-sm",
                active ? "bg-accent text-accent-foreground" : "hover:bg-accent/50",
              )}
            >
              {editingId === t.id ? (
                <input
                  autoFocus
                  className="min-w-0 flex-1 rounded border border-input bg-background px-1 py-0.5 text-sm outline-none"
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
                  onClick={() => onSelect(t.id)}
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
                className="hidden shrink-0 rounded p-1 text-muted-foreground hover:text-foreground group-hover:block"
                onClick={() => {
                  setEditingId(t.id);
                  setDraft(t.title);
                }}
              >
                <Pencil className="size-3.5" />
              </button>
              <button
                type="button"
                aria-label="删除"
                className="hidden shrink-0 rounded p-1 text-muted-foreground hover:text-destructive group-hover:block"
                onClick={() => {
                  if (confirm(`删除会话「${t.title}」？`)) remove.mutate(t.id);
                }}
              >
                <Trash2 className="size-3.5" />
              </button>
            </div>
          );
        })}
      </nav>
      <div className="space-y-1 border-t border-border p-2">
        <Link
          to="/kb"
          data-testid="nav-kb"
          className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-muted-foreground hover:bg-accent/50 hover:text-foreground"
        >
          <Library className="size-4" />
          知识库
        </Link>
        <Link
          to="/skills"
          data-testid="nav-skills"
          className="flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm text-muted-foreground hover:bg-accent/50 hover:text-foreground"
        >
          <Store className="size-4" />
          技能市场
        </Link>
      </div>
    </aside>
  );
}
