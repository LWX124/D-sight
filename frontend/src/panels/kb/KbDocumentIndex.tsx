import { useRef } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, MessageSquare, Newspaper, Trash2, Upload } from "lucide-react";
import {
  deleteDoc,
  deleteKbSource,
  fetchDocs,
  fetchKbSources,
  uploadDoc,
  type KbDoc,
  type KbSource,
} from "@/lib/kb";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const STATUS_LABEL: Record<string, string> = {
  pending: "排队中",
  processing: "处理中",
  ready: "就绪",
  failed: "失败",
};

const SOURCE_STATUS: Record<string, string> = {
  pending: "等待同步",
  syncing: "同步中",
  failed: "同步失败",
  limited: "已达上限，停止入库",
  // ready 不显示——就绪是常态
};

const SOURCE_ICON: Record<string, typeof FileText> = {
  upload: FileText,
  wechat_article: MessageSquare,
  news_item: Newspaper,
};

function StatusBadge({ status }: { status: string }) {
  if (status === "ready") return null; // 就绪是常态，不占视觉
  const failed = status === "failed";
  return (
    <span
      className={cn(
        "shrink-0 rounded-md px-1.5 py-0.5 text-xs font-medium",
        failed ? "bg-destructive/10 text-destructive" : "bg-muted text-muted-foreground",
      )}
    >
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

export default function KbDocumentIndex({
  kbId,
  selectedDocId,
  onSelect,
}: {
  kbId: string;
  selectedDocId: string | null;
  onSelect: (docId: string) => void;
}) {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const docsKey = ["kb-docs", kbId] as const;

  const { data: docs = [], isLoading } = useQuery({
    queryKey: docsKey,
    queryFn: () => fetchDocs(kbId),
    // 有在处理的文档就轮询，全部落定后停下（沿用旧 DocList 的做法）
    refetchInterval: (query) => {
      const list = (query.state.data as KbDoc[] | undefined) ?? [];
      return list.some((d) => d.status === "pending" || d.status === "processing") ? 1500 : false;
    },
  });

  const upload = useMutation({
    mutationFn: (file: File) => uploadDoc(kbId, file),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: docsKey });
      qc.invalidateQueries({ queryKey: ["kb"] });
    },
  });

  const remove = useMutation({
    mutationFn: (docId: string) => deleteDoc(kbId, docId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: docsKey });
      qc.invalidateQueries({ queryKey: ["kb"] });
    },
  });

  const sourcesKey = ["kb-sources", kbId] as const;
  const { data: sources = [] } = useQuery({
    queryKey: sourcesKey,
    queryFn: () => fetchKbSources(kbId),
    // 同步中的源会变状态，轮询到落定为止
    refetchInterval: (query) => {
      const list = (query.state.data as KbSource[] | undefined) ?? [];
      return list.some((s) => s.status === "pending" || s.status === "syncing") ? 3000 : false;
    },
  });

  const unsubscribe = useMutation({
    mutationFn: ({ id, purge }: { id: string; purge: boolean }) =>
      deleteKbSource(kbId, id, purge),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: sourcesKey });
      qc.invalidateQueries({ queryKey: docsKey });
      qc.invalidateQueries({ queryKey: ["kb"] });
    },
  });

  return (
    <div className="flex h-full flex-col">
      <div className="flex shrink-0 items-center justify-between gap-2 border-b px-3 py-2">
        <span className="text-xs font-medium text-muted-foreground">内容（{docs.length}）</span>
        <input
          ref={fileRef}
          type="file"
          accept=".txt,.md,.pdf"
          className="hidden"
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) upload.mutate(f);
            e.target.value = "";
          }}
        />
        <Button
          size="sm"
          variant="outline"
          className="h-7"
          data-testid={`kb-upload-${kbId}`}
          disabled={upload.isPending}
          onClick={() => fileRef.current?.click()}
        >
          <Upload className="size-3.5" />
          上传
        </Button>
      </div>

      {sources.length > 0 && (
        <ul className="shrink-0 space-y-1 border-b px-3 py-1.5">
          {sources.map((s) => (
            <li key={s.id} className="flex items-center gap-1.5 text-xs">
              <span className="min-w-0 flex-1 truncate" title={s.display_name}>
                订阅：{s.display_name}
              </span>
              {SOURCE_STATUS[s.status] && (
                <span
                  className={cn(
                    "shrink-0 rounded px-1 py-0.5",
                    s.status === "limited" || s.status === "failed"
                      ? "bg-destructive/10 text-destructive"
                      : "bg-muted text-muted-foreground",
                  )}
                  title={s.error ?? undefined}
                >
                  {SOURCE_STATUS[s.status]}
                </span>
              )}
              <button
                type="button"
                data-testid={`kb-source-remove-${s.id}`}
                aria-label={`断开订阅 ${s.display_name}`}
                disabled={unsubscribe.isPending}
                onClick={() => {
                  // 默认保留已入库文档——知识库是「我攒下的资料」，不该因退订而蒸发
                  const purge = confirm(
                    `断开「${s.display_name}」的订阅。\n\n确定 = 同时删除该订阅带进来的文档\n取消 = 保留已入库文档`,
                  );
                  unsubscribe.mutate({ id: s.id, purge });
                }}
                className="shrink-0 text-muted-foreground hover:text-destructive"
              >
                <Trash2 className="size-3" />
              </button>
            </li>
          ))}
        </ul>
      )}

      {upload.isError && (
        <p className="border-b px-3 py-1.5 text-xs text-destructive" role="alert">
          {String(upload.error)}
        </p>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
        {isLoading && <p className="px-1.5 text-sm text-muted-foreground">加载中…</p>}
        {!isLoading && docs.length === 0 && (
          <p className="px-1.5 text-sm text-muted-foreground">暂无内容</p>
        )}
        <ul className="space-y-0.5">
          {docs.map((d) => {
            const Icon = SOURCE_ICON[d.source_type] ?? FileText;
            return (
              <li
                key={d.id}
                className={cn(
                  "group flex items-center gap-1.5 rounded px-1.5 py-1 hover:bg-accent/50",
                  selectedDocId === d.id && "bg-accent",
                )}
              >
                <Icon className="size-3.5 shrink-0 text-muted-foreground" />
                <button
                  type="button"
                  onClick={() => onSelect(d.id)}
                  className="min-w-0 flex-1 truncate text-left text-sm"
                  title={d.title}
                >
                  {d.title}
                </button>
                {d.published_at && (
                  <span className="shrink-0 text-[11px] tabular-nums text-muted-foreground">
                    {new Date(d.published_at).toLocaleDateString("zh-CN", {
                      month: "2-digit",
                      day: "2-digit",
                    })}
                  </span>
                )}
                <StatusBadge status={d.status} />
                <button
                  type="button"
                  data-testid={`kb-doc-delete-${d.id}`}
                  aria-label={`删除 ${d.title}`}
                  disabled={remove.isPending}
                  onClick={() => remove.mutate(d.id)}
                  className="shrink-0 text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
                >
                  <Trash2 className="size-3.5" />
                </button>
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}
