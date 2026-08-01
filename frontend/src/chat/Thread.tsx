// assistant-ui 组件组装：直接采用 shadcn registry 生成的完整 Thread
// （流式文本 + markdown + 工具调用过程可见 via ToolFallback/ToolGroup）。
import { useRef, type FormEvent } from "react";
import { ArrowUpIcon } from "lucide-react";
import { Button } from "@/components/ui/button";

export { Thread } from "@/components/assistant-ui/thread";

export function DraftThreadComposer({
  isCreating,
  error,
  onSend,
}: {
  isCreating: boolean;
  error: string | null;
  onSend: (message: string) => void;
}) {
  const inputRef = useRef<HTMLTextAreaElement>(null);

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const message = inputRef.current?.value.trim() ?? "";
    if (!message || isCreating) return;
    onSend(message);
  }

  return (
    <div className="flex h-full flex-col justify-center bg-background">
      <div className="mx-auto flex w-full max-w-[44rem] flex-col gap-6 px-4">
        <h1 className="text-center text-2xl font-semibold">How can I help you today?</h1>
        <form onSubmit={handleSubmit} className="relative flex w-full flex-col">
          <div className="border-border/60 focus-within:border-border flex w-full flex-col gap-2 rounded-3xl border bg-muted/30 p-2 shadow-sm">
            <textarea
              ref={inputRef}
              aria-label="Message input"
              placeholder="Send a message..."
              rows={1}
              autoFocus
              disabled={isCreating}
              className="caret-primary placeholder:text-muted-foreground/80 max-h-32 min-h-10 w-full resize-none bg-transparent px-2.5 py-1 text-base outline-none"
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
            />
            <div className="flex justify-end">
              <Button
                type="submit"
                size="icon"
                disabled={isCreating}
                aria-label="Send message"
                className="size-7 rounded-full"
              >
                <ArrowUpIcon className="size-4.5" />
              </Button>
            </div>
          </div>
          {error && <p role="alert" className="mt-2 px-2 text-xs text-destructive">{error}</p>}
        </form>
      </div>
    </div>
  );
}
