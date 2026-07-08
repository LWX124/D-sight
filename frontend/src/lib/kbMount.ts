import { create } from "zustand";

// 聊天挂载的知识库选择：内存 zustand store。RuntimeProvider 的 body 函数用非 hook
// getter 在每次发送时读取最新选中集合，随消息以 mountedKbIds 发送。
type KbMountState = {
  mountedKbIds: string[];
  toggle: (id: string) => void;
};

export const useKbMountStore = create<KbMountState>((set, get) => ({
  mountedKbIds: [],
  toggle: (id) => {
    const cur = get().mountedKbIds;
    set({
      mountedKbIds: cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id],
    });
  },
}));

export function getMountedKbIds(): string[] {
  return useKbMountStore.getState().mountedKbIds;
}
