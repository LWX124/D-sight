import { useEffect, useState } from "react";
import { Trash2 } from "lucide-react";
import { RuntimeProvider } from "@/chat/RuntimeProvider";
import { Thread } from "@/chat/Thread";
import { clearKbThread, fetchKbThreadId } from "@/lib/kb";

// 单库对话：后端路径与普通聊天完全相同，只是把挂载集合锁定为当前库。
// 每库一个 type="kb" 的常驻会话，折叠/切库/切面板回来历史都还在。
export default function KbAssistant({ kbId }: { kbId: string }) {
  const [threadId, setThreadId] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setThreadId(null);
    fetchKbThreadId(kbId)
      .then((id) => {
        if (alive) setThreadId(id);
      })
      .catch(console.error);
    return () => {
      alive = false;
    };
  }, [kbId]);

  const handleClear = async () => {
    if (!threadId || !confirm("清除当前对话记录？此操作不可撤销。")) return;
    try {
      setThreadId(await clearKbThread(kbId, threadId));
    } catch (e) {
      console.error(e);
    }
  };

  if (!threadId) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
        正在加载对话…
      </div>
    );
  }

  return (
    // key 变化时重建 runtime：切库或清除对话都会换 threadId → 历史随之刷新
    <RuntimeProvider key={threadId} threadId={threadId} mountedKbIds={[kbId]}>
      <div className="flex h-full flex-col">
        <div className="flex shrink-0 items-center justify-between border-b px-3 py-1.5">
          <span className="text-xs text-muted-foreground">仅检索当前知识库</span>
          <button
            type="button"
            onClick={handleClear}
            title="清除对话"
            aria-label="清除对话"
            data-testid="kb-clear-chat"
            className="rounded-md border border-border p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            <Trash2 className="size-3" />
          </button>
        </div>
        <div className="min-h-0 flex-1 overflow-hidden">
          <Thread />
        </div>
      </div>
    </RuntimeProvider>
  );
}
