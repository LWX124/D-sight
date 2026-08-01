import { describe, expect, it } from "vitest";
import { unstable_createMessageConverter as createMessageConverter } from "@assistant-ui/react";
import {
  convertLangChainMessages,
  type LangChainMessage,
} from "@assistant-ui/react-langgraph";
import { withReasoning } from "./reasoning";

// DeepSeek 把思维链放在 additional_kwargs.reasoning_content（字符串），而
// convertLangChainMessages 只认 additional_kwargs.reasoning（content-block 形状）。
// withReasoning 负责这层归一；下面既验证归一本身，也验证归一后确实产出 reasoning part。
describe("withReasoning：DeepSeek 思维链归一", () => {
  const aiWithReasoning = {
    type: "ai",
    content: "约 1500 元",
    additional_kwargs: { reasoning_content: "先查行情，再核对财报" },
  } as unknown as LangChainMessage;

  it("reasoning_content 提升为 reasoning content-block", () => {
    const out = withReasoning(aiWithReasoning) as unknown as {
      additional_kwargs: { reasoning: { type: string; reasoning: string } };
    };
    expect(out.additional_kwargs.reasoning).toEqual({
      type: "reasoning",
      reasoning: "先查行情，再核对财报",
    });
  });

  it("归一后 converter 产出 reasoning part（思考过程可渲染）", () => {
    const converter = createMessageConverter(convertLangChainMessages);
    const [message] = converter.toThreadMessages([withReasoning(aiWithReasoning)]);
    const types = message.content.map((p) => p.type);
    expect(types).toContain("reasoning");
    expect(types).toContain("text");
  });

  it("无 reasoning_content 或非 ai 消息原样返回", () => {
    const plainAi = { type: "ai", content: "hi" } as unknown as LangChainMessage;
    expect(withReasoning(plainAi)).toBe(plainAi);
    const human = {
      type: "human",
      content: "hi",
      additional_kwargs: { reasoning_content: "不该出现在用户消息里" },
    } as unknown as LangChainMessage;
    expect(withReasoning(human)).toBe(human);
  });

  it("已有 reasoning 时不覆盖（避免与其他 provider 冲突）", () => {
    const existing = {
      type: "ai",
      content: "hi",
      additional_kwargs: {
        reasoning_content: "新的",
        reasoning: { type: "reasoning", reasoning: "原有的" },
      },
    } as unknown as LangChainMessage;
    expect(withReasoning(existing)).toBe(existing);
  });
});
