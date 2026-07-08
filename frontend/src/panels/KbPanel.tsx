import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import {
  createKb,
  fetchDocs,
  fetchKbs,
  shareKb,
  subscribeKb,
  uploadDoc,
  type Kb,
  type KbDoc,
} from "@/lib/kb";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const kbKey = ["kb"] as const;

const STATUS_LABEL: Record<string, string> = {
  pending: "排队中",
  processing: "处理中",
  ready: "就绪",
  failed: "失败",
};

function StatusBadge({ status }: { status: string }) {
  const done = status === "ready";
  const failed = status === "failed";
  return (
    <span
      className={
        "inline-flex items-center rounded-md px-1.5 py-0.5 text-xs font-medium " +
        (done
          ? "bg-emerald-100 text-emerald-700"
          : failed
            ? "bg-destructive/10 text-destructive"
            : "bg-muted text-muted-foreground")
      }
    >
      {STATUS_LABEL[status] ?? status}
    </span>
  );
}

function DocList({ kbId }: { kbId: string }) {
  const { data: docs = [] } = useQuery({
    queryKey: ["kb-docs", kbId],
    queryFn: () => fetchDocs(kbId),
    refetchInterval: (query) => {
      const list = (query.state.data as KbDoc[] | undefined) ?? [];
      return list.some((d) => d.status === "pending" || d.status === "processing")
        ? 1500
        : false;
    },
  });

  if (docs.length === 0) {
    return <p className="text-xs text-muted-foreground">暂无文档</p>;
  }
  return (
    <ul className="space-y-1">
      {docs.map((d) => (
        <li key={d.id} className="flex items-center justify-between gap-2 text-sm">
          <span className="min-w-0 flex-1 truncate" title={d.filename}>
            {d.filename}
          </span>
          {d.status === "ready" && (
            <span className="shrink-0 text-xs text-muted-foreground">{d.chunk_count} 片</span>
          )}
          <StatusBadge status={d.status} />
        </li>
      ))}
    </ul>
  );
}

function KbCard({ kb }: { kb: Kb }) {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [slug, setSlug] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: (file: File) => uploadDoc(kb.id, file),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["kb-docs", kb.id] });
      qc.invalidateQueries({ queryKey: kbKey });
    },
  });

  const share = useMutation({
    mutationFn: () => shareKb(kb.id),
    onSuccess: (r) => {
      setSlug(r.share_slug);
      qc.invalidateQueries({ queryKey: kbKey });
    },
  });

  return (
    <Card className="flex flex-col rounded-xl">
      <CardHeader>
        <CardTitle className="flex items-center justify-between gap-2">
          <span className="min-w-0 truncate">{kb.name}</span>
          <span className="shrink-0 text-xs font-normal text-muted-foreground">
            {kb.doc_count} 文档
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-3">
        <DocList kbId={kb.id} />
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
        <div className="mt-auto flex flex-wrap gap-2">
          <Button
            size="sm"
            variant="outline"
            data-testid={`kb-upload-${kb.id}`}
            disabled={upload.isPending}
            onClick={() => fileRef.current?.click()}
          >
            <Upload className="size-4" />
            上传文档
          </Button>
          <Button
            size="sm"
            variant="outline"
            data-testid={`kb-share-${kb.id}`}
            disabled={share.isPending}
            onClick={() => share.mutate()}
          >
            {kb.is_shared ? "查看分享" : "生成分享"}
          </Button>
        </div>
        {slug && (
          <p className="break-all text-xs text-muted-foreground" data-testid={`kb-slug-${kb.id}`}>
            分享码：<code className="font-mono">{slug}</code>
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export default function KbPanel() {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [subMsg, setSubMsg] = useState<string | null>(null);

  const { data: kbs = [], isLoading, isError } = useQuery({
    queryKey: kbKey,
    queryFn: fetchKbs,
  });

  const create = useMutation({
    mutationFn: () => createKb(name.trim()),
    onSuccess: () => {
      setName("");
      qc.invalidateQueries({ queryKey: kbKey });
    },
  });

  const subscribe = useMutation({
    mutationFn: () => subscribeKb(slug.trim()),
    onSuccess: (r) => {
      setSlug("");
      setSubMsg(`已订阅「${r.name}」`);
      qc.invalidateQueries({ queryKey: kbKey });
    },
    onError: () => setSubMsg("订阅失败：分享码无效或已关闭"),
  });

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-5xl space-y-6 p-5">
        <div className="flex flex-wrap items-end gap-4">
          <div className="flex items-end gap-2">
            <Input
              placeholder="新建知识库名称"
              className="w-56"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && name.trim()) create.mutate();
              }}
            />
            <Button
              data-testid="kb-create"
              disabled={!name.trim() || create.isPending}
              onClick={() => create.mutate()}
            >
              建库
            </Button>
          </div>
          <div className="flex items-end gap-2">
            <Input
              placeholder="输入分享码订阅"
              className="w-56"
              value={slug}
              onChange={(e) => {
                setSlug(e.target.value);
                setSubMsg(null);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && slug.trim()) subscribe.mutate();
              }}
            />
            <Button
              variant="outline"
              data-testid="kb-subscribe"
              disabled={!slug.trim() || subscribe.isPending}
              onClick={() => subscribe.mutate()}
            >
              订阅
            </Button>
          </div>
          {subMsg && <p className="text-xs text-muted-foreground">{subMsg}</p>}
        </div>

        {isLoading && <p className="text-sm text-muted-foreground">加载中…</p>}
        {isError && <p className="text-sm text-destructive">加载知识库失败</p>}
        {!isLoading && !isError && kbs.length === 0 && (
          <p className="text-sm text-muted-foreground">还没有知识库，先建一个吧</p>
        )}
        {!isLoading && !isError && kbs.length > 0 && (
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {kbs.map((kb) => (
              <KbCard key={kb.id} kb={kb} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
