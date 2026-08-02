import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { fetchDoc } from "@/lib/kb";

const SOURCE_LABEL: Record<string, string> = {
  upload: "上传文档",
  wechat_article: "微信公众号",
  news_item: "7x24 快讯",
};

export default function KbDocumentDetail({
  kbId,
  docId,
}: {
  kbId: string;
  docId: string | null;
}) {
  const { data: doc, isLoading, isError } = useQuery({
    queryKey: ["kb-doc", kbId, docId],
    queryFn: () => fetchDoc(kbId, docId as string),
    enabled: docId !== null,
  });

  if (docId === null) {
    return (
      <div className="flex h-full items-center justify-center px-6 text-sm text-muted-foreground">
        选择左侧内容查看详情
      </div>
    );
  }
  if (isLoading) {
    return <div className="p-5 text-sm text-muted-foreground">加载中…</div>;
  }
  if (isError || !doc) {
    return <div className="p-5 text-sm text-destructive">加载内容失败</div>;
  }

  return (
    <div className="h-full overflow-y-auto px-6 py-5">
      <h2 className="text-lg font-semibold leading-snug">{doc.title}</h2>
      <div className="mt-1.5 flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
        <span>{SOURCE_LABEL[doc.source_type] ?? doc.source_type}</span>
        {doc.published_at && (
          <span className="tabular-nums">{new Date(doc.published_at).toLocaleString("zh-CN")}</span>
        )}
        {doc.status === "ready" && <span>{doc.chunk_count} 片</span>}
        {doc.source_url && (
          <a
            href={doc.source_url}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-0.5 text-primary hover:underline"
          >
            原文
            <ExternalLink className="size-3" />
          </a>
        )}
      </div>

      {doc.status === "failed" && (
        <p className="mt-4 rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">
          处理失败：{doc.error}
        </p>
      )}

      {/* 展示入库时的文本快照，不回源重抓：检索命中的就是这份文本，
          展示与检索必须一致，否则用户会看到「AI 引用的和我看到的不一样」。 */}
      <pre className="mt-4 max-w-[65ch] whitespace-pre-wrap font-sans text-sm leading-7">
        {doc.text ?? (doc.status === "ready" ? "（无正文）" : "正在处理…")}
      </pre>
    </div>
  );
}
