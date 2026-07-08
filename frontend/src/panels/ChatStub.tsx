export default function ChatStub() {
  return (
    <div className="flex h-full flex-col">
      <div className="flex-1 overflow-y-auto p-4">
        <div className="flex h-full items-center justify-center">
          <p className="text-sm text-muted-foreground">AI 新闻助手即将上线</p>
        </div>
      </div>
      <div className="border-t border-border p-3">
        <input
          type="text"
          disabled
          placeholder="即将支持对新闻提问..."
          className="w-full rounded-lg border border-border bg-muted px-3 py-2 text-sm text-muted-foreground placeholder:text-muted-foreground/60"
        />
      </div>
    </div>
  );
}
