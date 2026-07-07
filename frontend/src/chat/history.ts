// 聊天历史恢复 + 会话内 token 刷新（修复 T7 两个缺陷）。
// 二者都走 apiFetch，复用其 401→单飞刷新→重试链路，避免绕过刷新导致的中途 401。
import { apiFetch } from "@/lib/api";
import { useAuthStore } from "@/lib/auth";
import type { LangChainMessage } from "@assistant-ui/react-langgraph";

interface State {
  messages: LangChainMessage[];
}

// 缺陷 (a)：刷新页面聊天历史不恢复。挂载时用 apiFetch 拉该 thread 的 human/ai 文本轮，
// 填入 assistant-transport 的 initialState。请求失败/无历史一律降级为空历史（不阻塞 UI）。
export async function loadInitialState(threadId: string): Promise<State> {
  try {
    const r = await apiFetch(`/api/threads/${threadId}/messages`);
    if (!r.ok) return { messages: [] };
    const data = (await r.json()) as { messages: LangChainMessage[] };
    return { messages: data.messages ?? [] };
  } catch {
    return { messages: [] };
  }
}

// 缺陷 (b)：assistant-transport 用自己的 fetch 发聊天请求，绕过 apiFetch 单飞刷新，
// access token（15min）过期后发消息直接 401。发送前先探测 /api/auth/me：若 token 已
// 过期，apiFetch 会自动触发单飞刷新并更新 store，随后取到的即是新 token。
export async function ensureFreshToken(): Promise<string | null> {
  await apiFetch("/api/auth/me");
  return useAuthStore.getState().accessToken;
}
