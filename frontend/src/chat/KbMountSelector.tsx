import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Library } from "lucide-react";
import { fetchKbs, fetchSubscribed } from "@/lib/kb";
import { useKbMountStore } from "@/lib/kbMount";
import { cn } from "@/lib/utils";

// 聊天挂载选择器：列出自有 + 已订阅知识库，点选后 id 进入 kbMount store，
// 随每条消息以 mountedKbIds 发送（见 RuntimeProvider 的 body 函数）。
export function KbMountSelector() {
  const [open, setOpen] = useState(false);
  const { mountedKbIds, toggle } = useKbMountStore();

  const { data: owned = [] } = useQuery({ queryKey: ["kb"], queryFn: fetchKbs });
  const { data: subscribed = [] } = useQuery({
    queryKey: ["kb-subscribed"],
    queryFn: fetchSubscribed,
  });

  // 自有库去重优先，避免自有与订阅重复出现。
  const ownedIds = new Set(owned.map((k) => k.id));
  const items = [
    ...owned.map((k) => ({ id: k.id, name: k.name })),
    ...subscribed.filter((k) => !ownedIds.has(k.id)),
  ];

  return (
    <div className="relative">
      <button
        type="button"
        data-testid="kb-mount-toggle"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1.5 rounded-md border border-border px-2 py-1 text-xs text-muted-foreground hover:bg-accent/50"
      >
        <Library className="size-3.5" />
        知识库{mountedKbIds.length > 0 ? ` (${mountedKbIds.length})` : ""}
      </button>
      {open && (
        <div className="absolute right-0 z-10 mt-1 w-56 rounded-md border border-border bg-popover p-1 shadow-md">
          {items.length === 0 ? (
            <p className="px-2 py-1.5 text-xs text-muted-foreground">暂无知识库</p>
          ) : (
            items.map((k) => {
              const on = mountedKbIds.includes(k.id);
              return (
                <button
                  key={k.id}
                  type="button"
                  data-testid={`kb-mount-${k.id}`}
                  onClick={() => toggle(k.id)}
                  className={cn(
                    "flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm hover:bg-accent/50",
                    on && "text-foreground",
                  )}
                >
                  <span
                    className={cn(
                      "flex size-4 shrink-0 items-center justify-center rounded border border-input text-[10px]",
                      on && "border-primary bg-primary text-primary-foreground",
                    )}
                  >
                    {on ? "✓" : ""}
                  </span>
                  <span className="min-w-0 flex-1 truncate">{k.name}</span>
                </button>
              );
            })
          )}
        </div>
      )}
    </div>
  );
}
