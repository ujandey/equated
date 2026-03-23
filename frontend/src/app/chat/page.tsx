"use client";

import { ChatWindow } from "@/components/chat/ChatWindow";
import { Sidebar } from "@/components/layout/Sidebar";

export default function ChatPage() {
  return (
    <div 
      className="flex h-screen bg-background text-on-surface selection:bg-primary/30 overflow-hidden"
      style={{
        backgroundImage: "linear-gradient(rgba(139, 92, 246, 0.03) 1px, transparent 1px)",
        backgroundSize: "100% 2.5rem"
      }}
    >
      <Sidebar />
      <main className="flex-1 flex flex-col relative w-full md:ml-[180px] transition-all overflow-hidden">
        <ChatWindow />
      </main>
    </div>
  );
}
