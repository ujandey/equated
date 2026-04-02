import { create } from "zustand";
import type { Message } from "@/types/message";

interface ChatState {
  messages: Message[];
  sessionId: string | null;
  addMessage: (msg: Message) => void;
  replaceMessages: (messages: Message[]) => void;
  clearMessages: () => void;
  setSessionId: (id: string) => void;
}

export const useChatStore = create<ChatState>((set) => ({
  messages: [],
  sessionId: null,

  addMessage: (msg) =>
    set((state) => ({ messages: [...state.messages, msg] })),

  replaceMessages: (messages) => set({ messages }),

  clearMessages: () => set({ messages: [] }),

  setSessionId: (id) => set({ sessionId: id }),
}));
