import type { LangChainMessage } from "@assistant-ui/react-langgraph";

// DeepSeek 的思维链走 additional_kwargs.reasoning_content（纯字符串，流式逐块拼接），
// 而 convertLangChainMessages 只认 additional_kwargs.reasoning（content-block 形状，
// 见其源码 allContent = [additional_kwargs?.reasoning, ...content]）——两者不通，
// 所以思考过程一直没渲染。这里归一：把 reasoning_content 提升为 {type:"reasoning"} 块，
// 让上游 converter 映射成 assistant-ui 的 reasoning part（Thread 已有 Reasoning 组件）。
//
// 单独成文件（而非放在 RuntimeProvider）以免破坏该组件文件的 react-refresh 约束。
export function withReasoning(message: LangChainMessage): LangChainMessage {
  if (message.type !== "ai") return message;
  const kwargs = (message as { additional_kwargs?: Record<string, unknown> })
    .additional_kwargs;
  const text = kwargs?.reasoning_content;
  if (typeof text !== "string" || !text || kwargs?.reasoning) return message;
  return {
    ...message,
    additional_kwargs: { ...kwargs, reasoning: { type: "reasoning", reasoning: text } },
  } as LangChainMessage;
}
