import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { MessageSquare } from "lucide-react";
import { fetchKbs } from "@/lib/kb";
import KbAssistant from "@/panels/kb/KbAssistant";
import KbDocumentDetail from "@/panels/kb/KbDocumentDetail";
import KbDocumentIndex from "@/panels/kb/KbDocumentIndex";
import KbList from "@/panels/kb/KbList";
import { cn } from "@/lib/utils";

// 三栏：库列表 → 内容索引 → 详情（详情下方挂可折叠对话栏）
export default function KbPanel() {
  const [kbId, setKbId] = useState<string | null>(null);
  const [docId, setDocId] = useState<string | null>(null);
  const [chatOpen, setChatOpen] = useState(false);

  const { data: kbs = [] } = useQuery({ queryKey: ["kb"], queryFn: fetchKbs });

  // 首次加载完成后默认选中第一个库，省掉一次点击
  useEffect(() => {
    if (kbId === null && kbs.length > 0) setKbId(kbs[0].id);
  }, [kbId, kbs]);

  return (
    <div className="flex h-full min-h-0">
      <aside className="w-56 shrink-0 border-r">
        <KbList
          selectedId={kbId}
          onSelect={(id) => {
            setKbId(id);
            setDocId(null); // 切库后原文档不属于新库，清掉选中
          }}
        />
      </aside>

      {kbId === null ? (
        <div className="flex flex-1 items-center justify-center text-sm text-muted-foreground">
          选择或新建一个知识库
        </div>
      ) : (
        <>
          <section className="w-72 shrink-0 border-r">
            <KbDocumentIndex kbId={kbId} selectedDocId={docId} onSelect={setDocId} />
          </section>

          <section className="flex min-w-0 flex-1 flex-col">
            <div className="flex shrink-0 items-center justify-end border-b px-3 py-1.5">
              <button
                type="button"
                data-testid="kb-chat-toggle"
                onClick={() => setChatOpen((v) => !v)}
                className={cn(
                  "flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs hover:bg-accent",
                  chatOpen && "bg-accent",
                )}
              >
                <MessageSquare className="size-3.5" />
                {chatOpen ? "收起对话" : "与本库对话"}
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-hidden">
              <KbDocumentDetail kbId={kbId} docId={docId} />
            </div>
            {chatOpen && (
              <div className="h-2/5 min-h-0 shrink-0 border-t">
                <KbAssistant kbId={kbId} />
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
