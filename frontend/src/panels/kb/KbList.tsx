import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createKb, fetchKbs, shareKb, subscribeKb, type Kb } from "@/lib/kb";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

export const kbKey = ["kb"] as const;

export default function KbList({
  selectedId,
  onSelect,
}: {
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  const { data: kbs = [], isLoading, isError } = useQuery({ queryKey: kbKey, queryFn: fetchKbs });

  const create = useMutation({
    mutationFn: () => createKb(name.trim()),
    onSuccess: (kb) => {
      setName("");
      qc.invalidateQueries({ queryKey: kbKey });
      onSelect(kb.id);
    },
  });

  const subscribe = useMutation({
    mutationFn: () => subscribeKb(slug.trim()),
    onSuccess: (r) => {
      setSlug("");
      setMsg(`已订阅「${r.name}」`);
      qc.invalidateQueries({ queryKey: kbKey });
    },
    onError: () => setMsg("订阅失败：分享码无效或已关闭"),
  });

  const share = useMutation({
    mutationFn: (id: string) => shareKb(id),
    onSuccess: (r) => {
      setMsg(`分享码：${r.share_slug}`);
      qc.invalidateQueries({ queryKey: kbKey });
    },
  });

  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 space-y-2 border-b p-3">
        <div className="flex gap-1.5">
          <Input
            placeholder="新建知识库"
            className="h-8 text-sm"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && name.trim()) create.mutate();
            }}
          />
          <Button
            size="sm"
            data-testid="kb-create"
            disabled={!name.trim() || create.isPending}
            onClick={() => create.mutate()}
          >
            建库
          </Button>
        </div>
        <div className="flex gap-1.5">
          <Input
            placeholder="分享码订阅"
            className="h-8 text-sm"
            value={slug}
            onChange={(e) => {
              setSlug(e.target.value);
              setMsg(null);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && slug.trim()) subscribe.mutate();
            }}
          />
          <Button
            size="sm"
            variant="outline"
            data-testid="kb-subscribe"
            disabled={!slug.trim() || subscribe.isPending}
            onClick={() => subscribe.mutate()}
          >
            订阅
          </Button>
        </div>
        {msg && <p className="break-all text-xs text-muted-foreground">{msg}</p>}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-2">
        {isLoading && <p className="px-1 text-sm text-muted-foreground">加载中…</p>}
        {isError && <p className="px-1 text-sm text-destructive">加载知识库失败</p>}
        {!isLoading && !isError && kbs.length === 0 && (
          <p className="px-1 text-sm text-muted-foreground">还没有知识库，先建一个吧</p>
        )}
        <ul className="space-y-0.5">
          {kbs.map((kb: Kb) => (
            <li key={kb.id}>
              <button
                type="button"
                data-testid={`kb-item-${kb.id}`}
                onClick={() => onSelect(kb.id)}
                className={cn(
                  "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-accent/50",
                  selectedId === kb.id && "bg-accent font-medium",
                )}
              >
                <span className="min-w-0 flex-1 truncate">{kb.name}</span>
                <span className="shrink-0 text-xs text-muted-foreground">{kb.doc_count}</span>
              </button>
              {selectedId === kb.id && (
                <button
                  type="button"
                  data-testid={`kb-share-${kb.id}`}
                  disabled={share.isPending}
                  onClick={() => share.mutate(kb.id)}
                  className="ml-2 mt-0.5 text-xs text-muted-foreground hover:text-foreground"
                >
                  {kb.is_shared ? "查看分享" : "生成分享"}
                </button>
              )}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
