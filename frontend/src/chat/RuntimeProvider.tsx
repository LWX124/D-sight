// 移植自官方 with-assistant-transport 示例 MyRuntimeProvider.tsx，做四处适配：
//  1) api 指向同源代理 "/api/chat"（Vite dev proxy / 生产同源反代）
//  2) headers 注入 JWT，读取当前内存中的 access token
//  3) body 携带 threadId（由 props 传入；threadId 变化时上层用 key 重建 runtime）
//  4) 无前端工具（去掉 toolkit/Tools 相关代码）
// converter 与 LangChainMessageConverter 保留官方语义：state.messages + pendingCommands 乐观更新。
import type { ReactNode } from "react";
import {
  AssistantRuntimeProvider,
  useAssistantTransportRuntime,
  unstable_createMessageConverter as createMessageConverter,
} from "@assistant-ui/react";
import {
  convertLangChainMessages,
  type LangChainMessage,
} from "@assistant-ui/react-langgraph";
import { useAuthStore } from "@/lib/auth";

interface State {
  messages: LangChainMessage[];
}

const messageConverter = createMessageConverter(convertLangChainMessages);

export function RuntimeProvider({
  threadId,
  children,
}: {
  threadId: string;
  children: ReactNode;
}) {
  const runtime = useAssistantTransportRuntime<State>({
    initialState: { messages: [] },
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
    // 适配 2：JWT header，每次请求读当前 token
    headers: async () => ({
      Authorization: `Bearer ${useAuthStore.getState().accessToken ?? ""}`,
    }),
    // 适配 3：body 携带 threadId
    body: { threadId },
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {children}
    </AssistantRuntimeProvider>
  );
}
