"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";
import { useChatStore } from "@/store/chatStore";
import { History, Brain, Sigma, FolderOpen, Hexagon, Menu } from "lucide-react";

interface Session {
  id: string;
  title: string;
  updated_at: string;
}

export function Sidebar() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  
  const { sessionId, setSessionId, clearMessages, addMessage } = useChatStore();

  useEffect(() => {
    fetchSessions();
  }, []);

  const fetchSessions = async () => {
    try {
      setIsLoading(true);
      const data = await api.getSessions();
      setSessions(data.sessions || []);
    } catch (err) {
      console.error("Failed to fetch sessions:", err);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSessionClick = async (id: string) => {
    if (id === sessionId) return;
    try {
      const data = await api.getSession(id);
      setSessionId(id);
      clearMessages();
      if (data.messages && data.messages.length > 0) {
        data.messages.forEach((msg: any) => addMessage(msg));
      }
      if (window.innerWidth < 768) setIsOpen(false); // Close on mobile
    } catch (err) {
      console.error("Failed to load session:", err);
    }
  };

  const handleNewSession = () => {
    setSessionId("");
    clearMessages();
    if (window.innerWidth < 768) setIsOpen(false); // Close on mobile
  };

  return (
    <>
      {/* Mobile Toggle */}
      <div 
        className={`md:hidden absolute z-50 top-4 left-4 p-2 bg-surface-glass rounded-lg text-on-surface cursor-pointer backdrop-blur shadow-sm border border-border-glass`}
        onClick={() => setIsOpen(!isOpen)}
      >
        <Menu className="w-5 h-5" />
      </div>

      <aside
        className={`fixed left-0 top-0 h-full flex flex-col py-6 bg-background/80 backdrop-blur-md w-[180px] z-40 border-r border-border-glass transition-transform duration-300 md:translate-x-0 ${
          isOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="px-6 mb-10 md:mt-0 mt-12">
          <div className="flex flex-col gap-1">
            <span className="text-xl md:text-2xl font-black text-primary tracking-tighter leading-none">Equated<br/>Solver</span>
            <span className="text-[9px] uppercase tracking-widest text-slate-500 font-label mt-1">Precision Tutoring</span>
          </div>
        </div>
        
        <nav className="flex-1 space-y-6 overflow-y-auto no-scrollbar pb-6">
          <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-2">
              <button className="group flex items-center gap-3 text-primary font-bold border-l-2 border-primary pl-4 transition-all">
                <History className="w-5 h-5" />
                <span className="text-sm font-label tracking-tight">History</span>
              </button>
              
              <div className="flex flex-col px-4 gap-1 mt-2">
                {isLoading ? (
                  <span className="text-xs text-slate-500 font-label ml-6">Loading...</span>
                ) : sessions.length === 0 ? (
                  <span className="text-xs text-slate-500 font-label ml-6">No sessions yet</span>
                ) : (
                  sessions.map((s) => {
                    const isActive = s.id === sessionId;
                    return (
                      <button
                        key={s.id}
                        onClick={() => handleSessionClick(s.id)}
                        className={`text-left text-xs font-label truncate ml-6 px-2 py-1.5 rounded-md transition-colors ${
                          isActive ? "bg-surface-glass text-primary" : "text-slate-400 hover:text-white"
                        }`}
                      >
                        {s.title || "Untitled"}
                      </button>
                    );
                  })
                )}
              </div>
            </div>

            <button className="group flex items-center gap-3 text-slate-400 pl-4 hover:bg-surface-glass hover:text-primary transition-colors py-2 rounded-r-full">
              <Brain className="w-5 h-5" />
              <span className="text-sm font-label tracking-tight">Active</span>
            </button>
            <button className="group flex items-center gap-3 text-slate-400 pl-4 hover:bg-surface-glass hover:text-primary transition-colors py-2 rounded-r-full">
              <Sigma className="w-5 h-5" />
              <span className="text-sm font-label tracking-tight">Proofs</span>
            </button>
            <button className="group flex items-center gap-3 text-slate-400 pl-4 hover:bg-surface-glass hover:text-primary transition-colors py-2 rounded-r-full">
              <FolderOpen className="w-5 h-5" />
              <span className="text-sm font-label tracking-tight">Archive</span>
            </button>
          </div>

          <div className="px-4 mt-8">
            <button 
              onClick={handleNewSession}
              className="w-full py-2 px-4 rounded-full bg-surface-glass text-primary text-[10px] sm:text-xs font-mono border border-border-glass hover:border-primary/50 transition-all font-bold tracking-widest hover:bg-primary/10 active:scale-95"
            >
              + new_solve()
            </button>
          </div>
        </nav>

        <div className="px-6 pt-4 flex items-center gap-2 text-slate-500 text-[10px] font-mono border-t border-border-glass mt-auto bg-background">
          <Hexagon className="w-4 h-4 text-primary" />
          <span>⬡ 1,240 credits</span>
        </div>
      </aside>

      {/* Mobile Backdrop */}
      {isOpen && (
        <div 
          className="fixed inset-0 bg-black/50 z-30 md:hidden backdrop-blur-sm transition-all"
          onClick={() => setIsOpen(false)}
        />
      )}
    </>
  );
}
