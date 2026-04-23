import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeKatex from "rehype-katex";
import rehypeHighlight from "rehype-highlight";
import type { Message } from "@/types/message";
import { Sparkles, AlertTriangle, RotateCcw, ShieldAlert, Clock, CheckCircle2 } from "lucide-react";
import { SolutionCard } from "@/components/SolutionCard";

// Regex to strip the ::cross-checked:: prefix from streamed solve content.
// This callout is only shown during streaming — once the done event arrives
// with intent==="solve", SolutionCard takes over and parses it internally.
const CROSS_CHECKED_RE = /^::cross-checked::(.+)\n\n/;

interface Props {
  message: Message;
  onRetry?: (content: string) => void;
}

export function MessageBubble({ message, onRetry }: Props) {
  const isUser = message.role === "user";
  const hasError = !isUser && Boolean(message.metadata?.error);
  const isRateLimited = hasError && Boolean(message.metadata?.rateLimited);
  const isUnverified =
    !isUser &&
    !hasError &&
    message.metadata?.verified === false;

  // A solve response is "done" once the SSE done event has been received
  // (signalled by the presence of message.metadata.model, which is set
  // in the finalize callback of useChat after the done event).
  const isSolveDone =
    !isUser &&
    !hasError &&
    message.metadata?.intent === "solve" &&
    Boolean(message.metadata?.model);

  // ── User message ──────────────────────────────────────────────────────────
  if (isUser) {
    return (
      <div className="max-w-3xl mx-auto mb-12 w-full animate-fade-in group">
        <div className="glass-panel border-l-2 border-primary/50 p-6 rounded-r-lg group-hover:border-primary transition-all">
          <p className="font-body text-[1.125rem] text-on-surface/80 leading-relaxed italic">
            &quot;{message.content}&quot;
          </p>
          <span className="text-[10px] opacity-40 mt-4 block text-right font-mono tracking-widest uppercase">
            {new Date(message.created_at).toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
        </div>
      </div>
    );
  }

  // ── Rate-limit error ──────────────────────────────────────────────────────
  if (isRateLimited) {
    const waitSeconds = message.metadata?.retryAfterSeconds ?? 60;
    return (
      <div className="flex flex-col items-start max-w-3xl mx-auto w-full group animate-fade-in">
        <div className="w-full rounded-xl border border-amber-500/30 bg-amber-500/5 p-6 space-y-4">
          <div className="flex items-center gap-3">
            <Clock className="w-5 h-5 text-amber-400 shrink-0" />
            <span className="text-[0.6875rem] font-bold text-amber-400 uppercase tracking-widest">
              Rate Limit Reached
            </span>
          </div>
          <p className="font-body text-sm text-on-surface/70 leading-relaxed">
            You&apos;ve sent too many requests. Please wait{" "}
            <span className="font-mono text-amber-300">{waitSeconds}s</span> before
            trying again.
          </p>
          {message.metadata?.retryContent && onRetry && (
            <button
              onClick={() => onRetry(message.metadata!.retryContent!)}
              className="flex items-center gap-2 px-4 py-2 rounded-full bg-amber-500/10 border border-amber-500/20 text-amber-300 text-xs font-mono uppercase tracking-widest hover:bg-amber-500/20 hover:border-amber-500/40 transition-all active:scale-95"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Retry
            </button>
          )}
        </div>
      </div>
    );
  }

  // ── Generic error state ───────────────────────────────────────────────────
  if (hasError) {
    return (
      <div className="flex flex-col items-start max-w-3xl mx-auto w-full group animate-fade-in">
        <div className="w-full rounded-xl border border-error/30 bg-error/5 p-6 space-y-4">
          <div className="flex items-center gap-3">
            <AlertTriangle className="w-5 h-5 text-error shrink-0" />
            <span className="text-[0.6875rem] font-bold text-error uppercase tracking-widest">
              Something went wrong
            </span>
          </div>
          <p className="font-body text-sm text-on-surface/70 leading-relaxed">
            {message.metadata!.error}
          </p>
          {/* Partial content streamed before the error */}
          {message.content && (
            <div className="mt-4 pt-4 border-t border-border-glass prose prose-invert prose-sm max-w-none font-body text-on-surface/60">
              <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkMath]}
                rehypePlugins={[rehypeKatex, rehypeHighlight]}
              >
                {message.content}
              </ReactMarkdown>
            </div>
          )}
          {message.metadata?.retryContent && onRetry && (
            <button
              onClick={() => onRetry(message.metadata!.retryContent!)}
              className="flex items-center gap-2 px-4 py-2 rounded-full bg-primary/10 border border-primary/20 text-primary text-xs font-mono uppercase tracking-widest hover:bg-primary/20 hover:border-primary/40 transition-all active:scale-95"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              Try Again
            </button>
          )}
        </div>
      </div>
    );
  }

  // ── Completed solve response → SolutionCard ───────────────────────────────
  // Rendered once the SSE done event has been received (model is set).
  // Conversational replies (intent !== "solve") never reach this branch.
  if (isSolveDone) {
    return (
      <div className="max-w-3xl mx-auto w-full animate-fade-in">
        <div className="flex items-center gap-3 mb-4 px-2">
          <Sparkles className="w-5 h-5 text-primary" />
          <span className="text-[0.6875rem] font-bold text-primary uppercase tracking-widest">
            Equated AI Tutor
          </span>
          <span className="text-[10px] font-mono text-zinc-600 ml-auto">
            {new Date(message.created_at).toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
        </div>
        <SolutionCard
          content={message.content}
          solution={message.metadata?.solution}
          verified={message.metadata?.verified}
          verificationConfidence={message.metadata?.verificationConfidence}
          model={message.metadata?.model}
          duration={message.metadata?.duration}
        />
      </div>
    );
  }

  // ── Streaming or conversational AI message ────────────────────────────────
  // Used during active streaming AND for non-solve (explain) responses.
  const crossCheckedMatch = message.content.match(CROSS_CHECKED_RE);
  const crossCheckedAnswer = crossCheckedMatch?.[1]?.trim();
  const mainContent = crossCheckedMatch
    ? message.content.slice(crossCheckedMatch[0].length)
    : message.content;

  return (
    <div className="flex flex-col items-start max-w-3xl mx-auto w-full group">
      <div className="flex items-center gap-3 mb-4 px-2">
        <Sparkles className="w-5 h-5 text-primary" />
        <span className="text-[0.6875rem] font-bold text-primary uppercase tracking-widest">
          Equated AI Tutor
        </span>
      </div>
      <div className="glass-panel p-6 sm:p-10 rounded-xl w-full border-t-[3px] border-primary/40 shadow-xl overflow-hidden relative">

        {/* Cross-checked callout — shown during streaming before SolutionCard takes over */}
        {crossCheckedAnswer && (
          <div className="flex items-start gap-3 mb-6 px-4 py-3 rounded-lg border border-emerald-500/30 bg-emerald-500/8">
            <CheckCircle2 className="w-4 h-4 text-emerald-400 mt-0.5 shrink-0" />
            <div>
              <span className="text-[0.6875rem] font-bold text-emerald-400 uppercase tracking-widest block mb-1.5">
                Cross-checked
              </span>
              <div className="text-emerald-200 font-semibold text-base leading-relaxed prose prose-invert max-w-none [&>p]:mb-0">
                <ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>
                  {crossCheckedAnswer}
                </ReactMarkdown>
              </div>
            </div>
          </div>
        )}

        {/* Unverified banner — for explain-mode and unverified solve */}
        {isUnverified && (
          <div className="flex items-start gap-3 mb-6 px-4 py-3 rounded-lg border border-amber-500/25 bg-amber-500/8">
            <ShieldAlert className="w-4 h-4 text-amber-400 mt-0.5 shrink-0" />
            <p className="text-[0.75rem] font-body text-amber-300/80 leading-snug">
              <span className="font-semibold text-amber-300">Unverified — </span>
              the symbolic math engine could not confirm this answer. Review the
              steps carefully before relying on the result.
            </p>
          </div>
        )}

        <div className="prose prose-invert prose-indigo max-w-none prose-pre:bg-black/80 prose-pre:border prose-pre:border-border-glass prose-p:leading-relaxed text-on-surface/90 font-body">
          <ReactMarkdown
            remarkPlugins={[remarkGfm, remarkMath]}
            rehypePlugins={[rehypeKatex, rehypeHighlight]}
          >
            {mainContent}
          </ReactMarkdown>
        </div>

        {/* Footer metadata */}
        <div className="flex items-center gap-3 mt-6 pt-4 border-t border-border-glass">
          {message.metadata?.model && (
            <span className="text-[10px] font-mono text-slate-500 uppercase tracking-widest">
              {message.metadata.model}
            </span>
          )}
          {message.metadata?.duration != null && (
            <span className="text-[10px] font-mono text-slate-600">
              {Math.round(message.metadata.duration)}ms
            </span>
          )}
          {message.metadata?.verified !== undefined && (
            <span
              className={`text-[10px] font-mono uppercase tracking-widest ${
                message.metadata.verified ? "text-emerald-500" : "text-amber-500"
              }`}
            >
              {message.metadata.verified ? "✓ verified" : "unverified"}
            </span>
          )}
        </div>

        <span className="text-[10px] opacity-40 mt-2 block text-left font-mono tracking-widest uppercase">
          {new Date(message.created_at).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
          })}
        </span>
      </div>
    </div>
  );
}
