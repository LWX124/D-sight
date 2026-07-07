// 移植自官方 with-assistant-transport 示例 MyRuntimeProvider.tsx，做四处适配：
//  1) api 指向同源代理 "/api/chat"（Vite dev proxy / 生产同源反代）
//  2) headers 注入 JWT，读取当前内存中的 access token
//  3) body 携带 threadId（由 props 传入；threadId 变化时上层用 key 重建 runtime）
//  4) 无前端工具（去掉 toolkit/Tools 相关代码）
// converter 与 LangChainMessageConverter 保留官方语义：state.messages + pendingCommands 乐观更新。
import { useEffect, useState, type ReactNode } from "react";
import {
  AssistantRuntimeProvider,
  useAssistantTransportRuntime,
  unstable_createMessageConverter as createMessageConverter,
} from "@assistant-ui/react";
import {
  convertLangChainMessages,
  type LangChainMessage,
} from "@assistant-ui/react-langgraph";
import { ensureFreshToken, loadInitialState } from "./history";

interface State {
  messages: LangChainMessage[];
}

const messageConverter = createMessageConverter(convertLangChainMessages);

// 缺陷 (a) 修复：挂载时先拉历史，加载完再以其为 initialState 建 runtime。
// 上层用 key={threadId} 重建本组件 → 切换/刷新会话都会重新加载。
export function RuntimeProvider({
  threadId,
  children,
  onSendResponse,
  onFinish,
}: {
  threadId: string;
  children: ReactNode;
  onSendResponse?: (status: number) => void;
  onFinish?: () => void;
}) {
  const [initialState, setInitialState] = useState<State | null>(null);

  useEffect(() => {
    let alive = true;
    loadInitialState(threadId).then((s) => {
      if (alive) setInitialState(s);
    });
    return () => {
      alive = false;
    };
  }, [threadId]);

  if (initialState === null) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
        正在加载会话…
      </div>
    );
  }
  return (
    <RuntimeInner
      threadId={threadId}
      initialState={initialState}
      onSendResponse={onSendResponse}
      onFinish={onFinish}
    >
      {children}
    </RuntimeInner>
  );
}

function RuntimeInner({
  threadId,
  initialState,
  children,
  onSendResponse,
  onFinish,
}: {
  threadId: string;
  initialState: State;
  children: ReactNode;
  onSendResponse?: (status: number) => void;
  onFinish?: () => void;
}) {
  const runtime = useAssistantTransportRuntime<State>({
    initialState,
    // 适配 1：同源代理
    api: "/api/chat",
    // converter：后端 langgraph 状态里的 messages（LangChainMessage[]）+ pendingCommands 乐观更新。
    // 乐观人类消息不带显式 id，使其与后端回显的人类消息（id 亦为空）归并到同一条，
    // 避免 id 不一致产生“2/2”幽灵分支。isRunning 取 isSending。
    converter: (state, { pendingCommands, isSending }) => {
      const optimistic: LangChainMessage[] = pendingCommands
        .filter((c) => c.type === "add-message")
        .map((c) => ({
          type: "human",
          content: c.message.parts
            .flatMap((p) => (p.type === "text" ? [p.text] : []))
            .join(""),
        }));
      return {
        messages: messageConverter.toThreadMessages([
          ...state.messages,
          ...optimistic,
        ]),
        isRunning: isSending,
      };
    },
    // 适配 2：JWT header。缺陷 (b) 修复：发送前先 ensureFreshToken——它经 apiFetch
    // 探测 /api/auth/me，token 过期时自动触发单飞刷新，返回最新 token，避免会话内 401。
    headers: async () => ({
      Authorization: `Bearer ${(await ensureFreshToken()) ?? ""}`,
    }),
    // 适配 3：body 携带 threadId
    body: { threadId },
    // 积分：onResponse 在 !ok 抛错之前拿到原始 Response（见 useAssistantTransportRuntime
    // 源码 options.onResponse?.(response) 早于 throw），故用状态码判 402 最稳，胜过解析错误消息。
    onResponse: (response) => onSendResponse?.(response.status),
    // 每次发送结束（成功或失败的 finally）刷新余额徽章。
    onFinish: () => onFinish?.(),
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {children}
    </AssistantRuntimeProvider>
  );
}
