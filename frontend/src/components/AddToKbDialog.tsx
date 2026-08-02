import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { X } from "lucide-react";
import { addKbItems, addKbSource, createKb, fetchKbs } from "@/lib/kb";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

type Item = { source_type: string; source_ref_id: string };
type Source = { source_type: string; source_ref_id: string; display_name: string };

// 四处复用：公众号文章卡片、正文区、左侧订阅项（整号）、快讯多选操作行。
export default function AddToKbDialog({
  open,
  onClose,
  mode,
  items,
  source,
  title,
}: {
  open: boolean;
  onClose: () => void;
  mode: "items" | "source";
  items?: Item[];
  source?: Source;
  title?: string;
}) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  const { data: kbs = [], isLoading } = useQuery({
    queryKey: ["kb"],
    queryFn: fetchKbs,
    enabled: open,
  });

  const submit = useMutation({
    mutationFn: async (kbId: string) => {
      if (mode === "source") {
        if (!source) throw new Error("缺少订阅源信息");
        await addKbSource(kbId, source);
        return "已开始同步该号的历史文章，之后有新文章会自动入库";
      }
      const r = await addKbItems(kbId, items ?? []);
      const parts: string[] = [];
      if (r.added) parts.push(`${r.added} 条已加入`);
      if (r.duplicate) parts.push(`${r.duplicate} 条已在库中`);
      if (r.failed.length) parts.push(`${r.failed.length} 条失败`);
      return parts.join("，") || "没有可加入的内容";
    },
    onSuccess: (text) => {
      setMsg(text);
      qc.invalidateQueries({ queryKey: ["kb"] });
    },
    onError: (e) => setMsg(String(e instanceof Error ? e.message : e)),
  });

  const createAndAdd = useMutation({
    mutationFn: async () => {
      const kb = await createKb(name.trim());
      setName("");
      return kb.id;
    },
    onSuccess: (kbId) => {
      qc.invalidateQueries({ queryKey: ["kb"] });
      submit.mutate(kbId);
    },
    onError: (e) => setMsg(String(e instanceof Error ? e.message : e)),
  });

  if (!open) return null;

  const heading = title ?? (mode === "source" ? "整号订阅到知识库" : "加入知识库");
  const busy = submit.isPending || createAndAdd.isPending;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-label={heading}
        className="w-80 rounded-lg border bg-background p-4 shadow-lg"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-medium">{heading}</h3>
          <button type="button" onClick={onClose} aria-label="关闭" className="text-muted-foreground hover:text-foreground">
            <X className="size-4" />
          </button>
        </div>

        <div className="mt-3 max-h-56 space-y-0.5 overflow-y-auto">
          {isLoading && <p className="text-xs text-muted-foreground">加载中…</p>}
          {!isLoading && kbs.length === 0 && (
            <p className="text-xs text-muted-foreground">还没有知识库，用下面的输入框建一个</p>
          )}
          {kbs.map((kb) => (
            <button
              key={kb.id}
              type="button"
              data-testid={`add-to-kb-${kb.id}`}
              disabled={busy}
              onClick={() => submit.mutate(kb.id)}
              className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-accent/50 disabled:opacity-50"
            >
              <span className="min-w-0 flex-1 truncate">{kb.name}</span>
              <span className="shrink-0 text-xs text-muted-foreground">{kb.doc_count}</span>
            </button>
          ))}
        </div>

        <div className="mt-3 flex gap-1.5 border-t pt-3">
          <Input
            placeholder="新建知识库并加入"
            className="h-8 text-sm"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && name.trim()) createAndAdd.mutate();
            }}
          />
          <Button
            size="sm"
            data-testid="add-to-kb-create"
            disabled={!name.trim() || busy}
            onClick={() => createAndAdd.mutate()}
          >
            新建
          </Button>
        </div>

        {msg && <p className="mt-2 text-xs text-muted-foreground">{msg}</p>}
      </div>
    </div>
  );
}
