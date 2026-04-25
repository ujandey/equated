"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { MessageBubble } from "./MessageBubble";
import { useChat } from "@/hooks/useChat";
import { useChatStore } from "@/store/chatStore";
import { Header } from "@/components/layout/Header";
import { ImageUpload } from "@/components/ImageUpload";
import type { Message } from "@/types/message";
import type { SolveResponse } from "@/lib/api";
import {
  Sparkles, Send, Paperclip, Lightbulb, CheckCircle2,
  BookOpen, Book, AlertTriangle, LineChart
} from "lucide-react";

export function ChatWindow() {
  const [input, setInput] = useState("");
  const [showImageUpload, setShowImageUpload] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const lastUserMsgRef = useRef<HTMLDivElement>(null);
  const wasLoadingRef = useRef(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const { messages, isLoading, sendMessage } = useChat();
  const currentSessionId = useChatStore((state) => state.sessionId);
  const addMessage = useChatStore((state) => state.addMessage);
  const setSessionId = useChatStore((state) => state.setSessionId);

  // While streaming: keep latest content in view
  useEffect(() => {
    if (isLoading) {
      messagesEndRef.current?.scrollIntoView({ behavior: "instant" });
    }
  }, [messages, isLoading]);

  // When streaming finishes: scroll back to the start of the exchange
  useEffect(() => {
    if (wasLoadingRef.current && !isLoading) {
      lastUserMsgRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    wasLoadingRef.current = isLoading;
  }, [isLoading]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;
    const query = input;
    setInput("");
    await sendMessage(query);
  };

  const handleRetry = async (content: string) => {
    await sendMessage(content);
  };

  const setPrompt = (prompt: string) => {
    setInput(prompt);
    inputRef.current?.focus();
  };

  // Prefill input from ImageUpload "Type manually" button
  useEffect(() => {
    const handler = (e: Event) => {
      const text = (e as CustomEvent<{ text: string }>).detail.text;
      setInput(text);
      inputRef.current?.focus();
    };
    window.addEventListener("equated:prefill", handler);
    return () => window.removeEventListener("equated:prefill", handler);
  }, []);

  const handleImageSolveComplete = useCallback((result: SolveResponse) => {
    addMessage({
      id: crypto.randomUUID(),
      role: "user",
      content: result.problem_interpretation?.trim() || "Question solved from uploaded image",
      created_at: new Date().toISOString(),
    });

    addMessage({
      id: crypto.randomUUID(),
      role: "assistant",
      content: result.quick_summary || result.final_answer || "",
      created_at: new Date().toISOString(),
      metadata: {
        model: result.model_used,
        verified: result.verified,
        verificationConfidence:
          result.verification_confidence === "high" ||
          result.verification_confidence === "medium" ||
          result.verification_confidence === "low"
            ? result.verification_confidence
            : undefined,
        intent: "solve",
        solution: {
          problem_interpretation: result.problem_interpretation,
          concept_used: result.concept_used,
          concept_explanation: result.concept_explanation,
          subject_hint: result.subject_hint,
          quick_summary: result.quick_summary,
          answer_summary: result.answer_summary,
          final_answer: result.final_answer,
          steps: result.steps,
          verification_status: result.verification_status,
          confidence: result.confidence,
        },
      },
    });

    if (result.session_id) {
      setSessionId(result.session_id);
    }
  }, [addMessage, setSessionId]);

  return (
    <>
      <Header />

      {showImageUpload && (
        <ImageUpload
          onClose={() => setShowImageUpload(false)}
          onSolveComplete={handleImageSolveComplete}
          sessionId={currentSessionId ?? undefined}
        />
      )}
      
      <div className="flex-1 flex h-full w-full min-h-0 overflow-hidden pt-16">
        {/* Central Canvas (Study Area) */}
        <section className="flex-1 overflow-y-auto px-4 md:px-12 py-8 scroll-smooth pb-48 no-scrollbar">
          {messages.length === 0 && (
            <div className="text-center text-on-surface/50 mt-20 max-w-lg mx-auto animate-fade-in">
              <div className="w-16 h-16 rounded-2xl bg-surface-glass border border-border-glass mx-auto mb-6 flex items-center justify-center">
                <Sparkles className="w-10 h-10 text-primary" />
              </div>
              <h3 className="text-2xl font-headline text-on-surface mb-2">How can I help you today?</h3>
              <p className="font-body text-sm">Ask a complex STEM question or type an equation to get started.</p>
              <div className="flex gap-2 mt-8 overflow-x-auto no-scrollbar pb-2 justify-center opacity-70 hover:opacity-100 transition-opacity">
                <button onClick={() => setPrompt("Solve x^2 - 5x + 6 = 0")} className="whitespace-nowrap px-4 py-1.5 rounded-full bg-surface-glass border border-border-glass text-[0.75rem] text-slate-400 hover:text-primary hover:border-primary/20 transition-all">Solve x² − 5x + 6 = 0</button>
                <button onClick={() => setPrompt("Differentiate sin(x) * e^x")} className="whitespace-nowrap px-4 py-1.5 rounded-full bg-surface-glass border border-border-glass text-[0.75rem] text-slate-400 hover:text-primary hover:border-primary/20 transition-all">Differentiate sin(x) · eˣ</button>
                <button onClick={() => setPrompt("Integrate 1/(1+x^2) dx")} className="whitespace-nowrap px-4 py-1.5 rounded-full bg-surface-glass border border-border-glass text-[0.75rem] text-slate-400 hover:text-primary hover:border-primary/20 transition-all">∫ 1/(1+x²) dx</button>
                <button onClick={() => setPrompt("Explain Stokes Theorem")} className="whitespace-nowrap px-4 py-1.5 rounded-full bg-surface-glass border border-border-glass text-[0.75rem] text-slate-400 hover:text-primary hover:border-primary/20 transition-all">Explain Stokes Theorem</button>
              </div>
            </div>
          )}

          <div className="space-y-12">
            {(() => {
              const lastUserIndex = messages.reduce((last, m, i) => m.role === "user" ? i : last, -1);
              return messages.map((msg: Message, index: number) => (
                <div
                  key={msg.id}
                  className="animate-slide-up w-full"
                  ref={index === lastUserIndex ? lastUserMsgRef : undefined}
                >
                  <MessageBubble message={msg} onRetry={handleRetry} />
                </div>
              ));
            })()}
            <div ref={messagesEndRef} />
          </div>

          {isLoading && (
            <div className="flex justify-center animate-pulse pt-4">
              <div className="px-4 py-2 bg-surface-glass border border-border-glass rounded-full flex items-center gap-2 text-[0.75rem] text-on-surface/40 font-mono">
                <span className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-ping"></span>
                COMPUTING_RESPONSE...
              </div>
            </div>
          )}
        </section>

        {/* Context Rail (Right Panel) */}
        <aside className="w-80 bg-background/50 border-l border-border-glass p-6 overflow-y-auto hidden xl:block pb-48 no-scrollbar">
          <div className="space-y-8">
            {/* Formula Card Placeholder */}
            <div className="group">
              <div className="flex items-center justify-between mb-3">
                <span className="text-[10px] font-mono uppercase tracking-widest text-slate-500">Key Formula</span>
                <Book className="w-4 h-4 text-primary" />
              </div>
              <div className="glass-panel p-5 rounded-2xl group-hover:border-primary/40 transition-all">
                <h4 className="font-headline text-lg mb-2 text-on-surface">Relevant Formula</h4>
                <code className="block font-mono text-xs text-primary bg-background/50 p-2 rounded mb-3">
                  Pending context...
                </code>
                <p className="text-[11px] font-body text-slate-400">
                  Formula will appear here based on the current active derivation.
                </p>
              </div>
            </div>

            {/* Mistake Alert Box Placeholder */}
            <div className="bg-error/10 border border-error/20 p-5 rounded-2xl">
              <div className="flex items-center gap-2 mb-3 text-error">
                <AlertTriangle className="w-5 h-5" />
                <span className="font-label text-xs font-bold uppercase tracking-tighter">Mistake Alert</span>
              </div>
              <p className="font-body text-sm text-on-surface-variant leading-relaxed">
                Connect your past submissions to enable personalized cognitive warnings.
              </p>
            </div>

            {/* Visualization Placeholder */}
            <div className="rounded-2xl glass-panel h-48 flex items-center justify-center relative overflow-hidden group">
              <div className="absolute inset-0 w-full h-full bg-surface-glass opacity-20 group-hover:scale-110 transition-transform duration-700" />
              <div className="relative z-10 text-center px-4">
                <LineChart className="w-8 h-8 text-primary mx-auto mb-2 opacity-50" />
                <span className="text-[10px] font-mono text-slate-400 uppercase">Live Projection Buffer</span>
              </div>
            </div>
          </div>
        </aside>
      </div>

      {/* Bottom Shell (Navigation & Input) */}
      <div className="fixed bottom-0 left-0 md:left-[180px] right-0 z-50 pointer-events-none">
        {/* Hint Strip */}
        <div className="flex justify-center mb-4 pointer-events-auto">
          <nav className="flex items-center gap-1 bg-surface-glass backdrop-blur-xl rounded-full p-1 shadow-[0_-10px_30px_rgba(0,0,0,0.3)] border border-border-glass">
            <button className="bg-primary text-background rounded-full px-4 py-1.5 font-mono text-[10px] uppercase tracking-widest flex items-center gap-2">
              <Lightbulb className="w-3 h-3" />
              Hint mode
            </button>
            <button className="text-slate-400 px-4 py-1.5 font-mono text-[10px] uppercase tracking-widest flex items-center gap-2 hover:text-white transition-colors">
              <CheckCircle2 className="w-3 h-3" />
              Verify mode
            </button>
            <button className="text-slate-400 px-4 py-1.5 font-mono text-[10px] uppercase tracking-widest flex items-center gap-2 hover:text-white transition-colors">
              <BookOpen className="w-3 h-3" />
              Explain only
            </button>
          </nav>
        </div>

        {/* Sticky Input Area */}
        <div className="max-w-4xl mx-auto px-4 md:px-8 pb-8 pointer-events-auto">
          <form 
            onSubmit={handleSubmit}
            className="relative glass-panel rounded-xl shadow-2xl overflow-hidden focus-within:ring-2 ring-primary/50 transition-all flex items-center"
          >
            <input 
              ref={inputRef}
              className="w-full bg-transparent border-none text-on-surface placeholder:text-slate-500 focus:ring-0 py-5 pl-6 pr-24 outline-none font-body text-base md:text-lg h-full" 
              placeholder="Type an equation, ask a question, or describe a problem..." 
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={isLoading}
            />
            <div className="absolute right-4 top-1/2 -translate-y-1/2 flex items-center gap-3">
              <button
                type="button"
                onClick={() => setShowImageUpload(true)}
                className="text-slate-500 hover:text-primary transition-colors hidden sm:block"
                title="Upload image"
              >
                <Paperclip className="w-5 h-5" />
              </button>
              <button 
                type="submit"
                disabled={isLoading || !input.trim()}
                className="bg-primary w-10 h-10 md:w-12 md:h-12 rounded-full flex items-center justify-center text-background hover:scale-110 active:scale-95 transition-all neon-glow disabled:opacity-50 disabled:hover:scale-100"
              >
                <Send className="w-5 h-5 ml-0.5" />
              </button>
            </div>
          </form>

        </div>
      </div>
    </>
  );
}
