import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeHighlight from "rehype-highlight";
import type { Message } from "@/types/message";
import { Sparkles } from "lucide-react";

interface Props {
  message: Message;
}

export function MessageBubble({ message }: Props) {
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div className="max-w-3xl mx-auto mb-12 w-full animate-fade-in group">
        <div className="glass-panel border-l-2 border-primary/50 p-6 rounded-r-lg group-hover:border-primary transition-all">
          <p className="font-body text-[1.125rem] text-on-surface/80 leading-relaxed italic">
            &quot;{message.content}&quot;
          </p>
          <span className="text-[10px] opacity-40 mt-4 block text-right font-mono tracking-widest uppercase">
            {new Date(message.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </span>
        </div>
      </div>
    );
  }

  // AI Message
  return (
    <div className="flex flex-col items-start max-w-3xl mx-auto w-full group">
      <div className="flex items-center gap-3 mb-4 px-2">
        <Sparkles className="w-5 h-5 text-primary" />
        <span className="text-[0.6875rem] font-bold text-primary uppercase tracking-widest">Equated AI Tutor</span>
      </div>
      <div className="glass-panel p-6 sm:p-10 rounded-xl w-full border-t-[3px] border-primary/40 shadow-xl overflow-hidden relative">
        <div className="prose prose-invert prose-indigo max-w-none prose-pre:bg-black/80 prose-pre:border prose-pre:border-border-glass prose-p:leading-relaxed text-on-surface/90 font-body">
          <ReactMarkdown
            remarkPlugins={[remarkGfm, remarkMath]}
            rehypePlugins={[rehypeKatex, rehypeHighlight]}
          >
            {message.content}
          </ReactMarkdown>
        </div>
        <span className="text-[10px] opacity-40 mt-8 block text-left font-mono tracking-widest uppercase">
          {new Date(message.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </span>
      </div>
    </div>
  );
}

