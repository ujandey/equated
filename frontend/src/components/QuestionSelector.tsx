"use client";

import { useState } from "react";
import { MultiQuestionResponse, QuestionOption } from "@/lib/api";

// KaTeX is loaded via react-markdown + rehype-katex in MessageBubble; here we
// render LaTeX inline with a simple delimited block so the existing pipeline
// can pick it up, or fall back to plain text when KaTeX isn't in scope.
function LatexDisplay({ latex, plain }: { latex: string; plain: string }) {
  if (!latex) return <span className="font-mono text-xs text-slate-300">{plain}</span>;
  return (
    <span
      className="font-mono text-xs text-violet-300 break-all"
      title={plain}
    >
      {latex}
    </span>
  );
}

interface QuestionSelectorProps {
  response: MultiQuestionResponse;
  onSelect: (questionId: string, questions: QuestionOption[]) => void;
}

export function QuestionSelector({ response, onSelect }: QuestionSelectorProps) {
  const [selecting, setSelecting] = useState<string | null>(null);
  const { questions } = response;

  const handleSelect = async (id: string) => {
    setSelecting(id);
    await onSelect(id, questions);
  };

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="border-b border-white/10 pb-4">
        <p className="font-mono text-xs uppercase tracking-widest text-slate-400">
          Found {questions.length} questions in your image.
        </p>
        <p className="font-mono text-sm text-slate-200 mt-1">
          Which would you like to solve?
        </p>
      </div>

      {/* Question cards */}
      <div className="space-y-3 max-h-[50vh] overflow-y-auto pr-1 no-scrollbar">
        {questions.map((q) => {
          const isLoading = selecting === q.id;
          const isDisabled = selecting !== null && selecting !== q.id;

          return (
            <div
              key={q.id}
              className={`border transition-all ${
                isLoading
                  ? "border-violet-500/60 bg-violet-500/5"
                  : isDisabled
                  ? "border-white/5 opacity-40"
                  : "border-white/10 hover:border-white/25 bg-white/[0.02]"
              }`}
            >
              <div className="p-4">
                {/* Question number + subject badge */}
                <div className="flex items-center gap-2 mb-3">
                  <span className="font-mono text-[10px] text-violet-400 border border-violet-500/30 px-2 py-0.5">
                    Q{q.id}
                  </span>
                  <span className="font-mono text-[10px] text-slate-600 uppercase tracking-wider">
                    {q.subject_hint}
                  </span>
                </div>

                {/* Plain text */}
                <p className="font-mono text-sm text-slate-200 leading-relaxed mb-2">
                  {q.text}
                </p>

                {/* LaTeX display */}
                {q.latex && q.latex !== q.text && (
                  <div className="bg-black/30 border border-white/5 px-3 py-2 mt-2 overflow-x-auto no-scrollbar">
                    <LatexDisplay latex={q.latex} plain={q.text} />
                  </div>
                )}
              </div>

              {/* Solve button */}
              <div className="border-t border-white/5 px-4 py-3">
                <button
                  onClick={() => handleSelect(q.id)}
                  disabled={selecting !== null}
                  className={`font-mono text-xs uppercase tracking-widest transition-all flex items-center gap-2 ${
                    isLoading
                      ? "text-violet-400 cursor-wait"
                      : isDisabled
                      ? "text-slate-600 cursor-not-allowed"
                      : "text-violet-400 hover:text-violet-300"
                  }`}
                >
                  {isLoading ? (
                    <>
                      <span className="w-3 h-3 border border-violet-500/40 border-t-violet-400 rounded-full animate-spin" />
                      Solving...
                    </>
                  ) : (
                    "Solve this →"
                  )}
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Footer note */}
      <p className="font-mono text-[10px] text-slate-600 text-center pt-2">
        Want to solve all of them? Solve one at a time.
      </p>
    </div>
  );
}
