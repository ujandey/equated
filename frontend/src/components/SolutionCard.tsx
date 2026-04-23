"use client";

import { useState } from "react";
import katex from "katex";
import "katex/dist/katex.min.css";
import ReactMarkdown from "react-markdown";
import remarkMath from "remark-math";
import remarkGfm from "remark-gfm";
import rehypeKatex from "rehype-katex";
import { ChevronDown, ChevronRight, CheckCircle2, AlertTriangle, CircleDot } from "lucide-react";
import type { SolutionMeta } from "@/types/message";

// ── KaTeX Renderers ────────────────────────────────────────────────────────

function KaTeXInline({ latex }: { latex: string }) {
  try {
    const html = katex.renderToString(latex, {
      throwOnError: false,
      displayMode: false,
    });
    return <span dangerouslySetInnerHTML={{ __html: html }} />;
  } catch {
    return <span className="font-mono text-sm">{latex}</span>;
  }
}

function KaTeXDisplay({ latex }: { latex: string }) {
  // Strip surrounding dollar signs if present (legacy format guard)
  const clean = latex
    .replace(/^\$\$/, '').replace(/\$\$$/, '')
    .replace(/^\$/, '').replace(/\$$/, '')
    .trim();

  try {
    const html = katex.renderToString(clean, {
      throwOnError: false,
      displayMode: true,
    });
    return (
      <div
        className="flex justify-center py-3 px-4 overflow-x-auto"
        dangerouslySetInnerHTML={{ __html: html }}
      />
    );
  } catch {
    return <div className="font-mono text-sm py-2 px-4 text-center">{clean}</div>;
  }
}

// ── Verification badge configs ─────────────────────────────────────────────

type VerificationStatus = "verified" | "unverified" | "partial";

const verificationConfig = {
  verified: {
    borderColor: "border-green-600",
    badgeBg: "bg-green-950",
    badgeText: "text-green-400",
    badgeBorder: "border-green-700",
    icon: "✓",
    label: "CROSS-CHECKED",
    Icon: CheckCircle2,
    warning: null,
  },
  unverified: {
    borderColor: "border-amber-600",
    badgeBg: "bg-amber-950",
    badgeText: "text-amber-400",
    badgeBorder: "border-amber-700",
    icon: "⚠",
    label: "UNVERIFIED",
    Icon: AlertTriangle,
    warning:
      "This answer could not be symbolically verified. Double-check your work.",
  },
  partial: {
    borderColor: "border-blue-600",
    badgeBg: "bg-blue-950",
    badgeText: "text-blue-400",
    badgeBorder: "border-blue-700",
    icon: "◎",
    label: "PARTIALLY VERIFIED",
    Icon: CircleDot,
    warning: null,
  },
} as const;

// ── Helper components ──────────────────────────────────────────────────────

const Divider = () => <hr className="border-t border-zinc-700/50 my-5" />;

const SectionLabel = ({ children }: { children: React.ReactNode }) => (
  <p className="text-xs font-mono tracking-widest text-purple-400 uppercase mb-2">
    {children}
  </p>
);

// ── Step interfaces ────────────────────────────────────────────────────────

interface NormalizedStep {
  number: number;
  title: string;
  explanation: string;
  equation: string | null;
}

/**
 * Normalize a step object from the backend to a consistent shape.
 * Handles both legacy { step, rule, explanation } and new { number, title, explanation, equation }.
 */
function normalizeStep(raw: Record<string, unknown>, index: number): NormalizedStep {
  return {
    number: (raw.number as number) ?? (raw.step as number) ?? index + 1,
    title: (raw.title as string) || (raw.rule as string) || `Step ${index + 1}`,
    explanation: (raw.explanation as string) || "",
    equation: (raw.equation as string | null) ?? null,
  };
}

// ── Markdown-based step body (fallback when no KaTeX equation) ─────────────

const REMARK = [remarkGfm, remarkMath];
const REHYPE = [rehypeKatex];

function StepBody({ body }: { body: string }) {
  return (
    <div className="mt-3 text-sm text-zinc-300 leading-relaxed prose prose-invert prose-sm max-w-none prose-p:mb-2 prose-p:last:mb-0 [&_.katex-display]:my-0 [&_.katex-display]:overflow-x-auto">
      <ReactMarkdown remarkPlugins={REMARK} rehypePlugins={REHYPE}>
        {body}
      </ReactMarkdown>
    </div>
  );
}

// ── SolutionCard props ─────────────────────────────────────────────────────

interface SolutionCardProps {
  content: string;
  solution: SolutionMeta | undefined;
  verified: boolean | undefined;
  verificationConfidence: "high" | "medium" | "low" | undefined;
  model: string | undefined;
  duration: number | undefined;
}

// ── SolutionCard Component ─────────────────────────────────────────────────

export function SolutionCard({
  content,
  solution,
  verified,
  verificationConfidence,
  model,
  duration,
}: SolutionCardProps) {
  // Determine verification status
  const status: VerificationStatus =
    solution?.verification_status ??
    (verified === true
      ? "verified"
      : verified === false
        ? "unverified"
        : "partial");

  const config = verificationConfig[status];
  const BadgeIcon = config.Icon;

  // Normalize final answer — strip ::cross-checked:: prefix if present
  const rawFinalAnswer = solution?.final_answer || "";
  const cleanFinalAnswer = rawFinalAnswer
    .replace(/^::cross-checked::/, "")
    .trim();

  // Answer summary — prefer new answer_summary, fall back to quick_summary
  const answerSummary =
    solution?.answer_summary || solution?.quick_summary || "";

  // Concept explanation
  const conceptExplanation = solution?.concept_explanation || "";

  // Normalize steps
  const normalizedSteps: NormalizedStep[] = (solution?.steps || []).map(
    (s, i) => normalizeStep(s as unknown as Record<string, unknown>, i)
  );

  // Confidence
  const confidence = solution?.confidence ?? (
    verificationConfidence === "high" ? 0.97 :
    verificationConfidence === "medium" ? 0.72 :
    verificationConfidence === "low" ? 0.35 : 0.5
  );

  // Step expansion state
  const firstStep = normalizedSteps[0]?.number ?? 1;
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(
    new Set([firstStep])
  );
  const [showAll, setShowAll] = useState(false);

  const toggleStep = (num: number) => {
    setExpandedSteps((prev) => {
      const next = new Set(prev);
      if (next.has(num)) next.delete(num);
      else next.add(num);
      return next;
    });
  };

  const handleShowAll = () => {
    setExpandedSteps(new Set(normalizedSteps.map((s) => s.number)));
    setShowAll(true);
  };

  return (
    <div className="w-full font-mono">
      {/* ── A: Answer Hero ──────────────────────────────────────────────── */}
      <div
        className={`bg-zinc-900 border-2 ${config.borderColor} p-6 rounded-t-lg`}
      >
        {/* Verification badge */}
        <div
          className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded text-xs font-mono tracking-widest border ${config.badgeBg} ${config.badgeText} ${config.badgeBorder} mb-4`}
        >
          <BadgeIcon className="w-3 h-3" />
          <span>{config.label}</span>
        </div>

        {/* Final Answer — large, centered, KaTeX display mode */}
        {cleanFinalAnswer && (
          <div className="flex justify-center py-2">
            <div className="text-3xl [&_.katex-display]:my-1 [&_.katex-display]:overflow-x-auto">
              <KaTeXDisplay latex={cleanFinalAnswer} />
            </div>
          </div>
        )}

        {/* One sentence summary */}
        {answerSummary && (
          <p className="text-sm text-zinc-400 text-center mt-2">
            {answerSummary}
          </p>
        )}

        {/* Warning for unverified */}
        {config.warning && (
          <p className="text-xs text-amber-400 text-center mt-3 font-mono">
            {config.warning}
          </p>
        )}
      </div>

      {/* ── B: Problem Interpretation ──────────────────────────────────── */}
      {solution?.problem_interpretation && (
        <div className="border-2 border-t-0 border-zinc-700 px-6 py-4 bg-zinc-950">
          <Divider />
          <SectionLabel>Problem interpretation</SectionLabel>
          <p className="text-sm text-zinc-300 leading-relaxed font-sans">
            {solution.problem_interpretation}
          </p>
        </div>
      )}

      {/* ── C: Concept Used ────────────────────────────────────────────── */}
      {solution?.concept_used && (
        <div className="border-2 border-t-0 border-zinc-700 px-6 py-4 bg-zinc-950">
          <Divider />
          <SectionLabel>Concept used</SectionLabel>
          <span className="inline-block text-xs font-mono text-purple-300 bg-purple-950 border border-purple-800 rounded px-2.5 py-1 mb-2">
            {solution.concept_used}
          </span>
          {conceptExplanation && (
            <p className="text-sm text-zinc-300 leading-relaxed font-sans">
              {conceptExplanation}
            </p>
          )}
        </div>
      )}

      {/* ── D: Step-by-Step Solution ───────────────────────────────────── */}
      {normalizedSteps.length > 0 && (
        <div className="border-2 border-t-0 border-zinc-700 px-6 py-5 bg-zinc-950">
          <Divider />
          <SectionLabel>Step-by-step solution</SectionLabel>

          <div className="space-y-4 mt-4">
            {normalizedSteps.map((step) => {
              const isExpanded = expandedSteps.has(step.number);
              return (
                <div key={step.number} className="mb-4">
                  {isExpanded ? (
                    /* Expanded step */
                    <div className="border-l-2 border-purple-600 pl-4">
                      <span className="text-xs font-mono text-zinc-500 bg-zinc-800 px-2 py-0.5 rounded inline-block mb-2">
                        STEP {String(step.number).padStart(2, "0")}
                      </span>
                      <p className="text-base font-medium text-white mb-1.5 font-sans">
                        {step.title}
                      </p>
                      <p className="text-sm text-zinc-300 leading-relaxed mb-0 font-sans">
                        {step.explanation}
                      </p>
                      {step.equation && (
                        <KaTeXDisplay latex={step.equation} />
                      )}
                      <button
                        onClick={() => toggleStep(step.number)}
                        className="text-xs font-mono text-zinc-600 hover:text-zinc-400 mt-2 transition-colors"
                      >
                        collapse ▴
                      </button>
                    </div>
                  ) : (
                    /* Collapsed step */
                    <button
                      onClick={() => toggleStep(step.number)}
                      className="w-full flex items-center gap-3 border-l-2 border-zinc-700 hover:border-purple-700 pl-4 py-1.5 text-left transition-colors group"
                    >
                      <span className="text-xs font-mono text-zinc-500 bg-zinc-800 px-2 py-0.5 rounded shrink-0">
                        STEP {String(step.number).padStart(2, "0")}
                      </span>
                      <span className="text-sm text-zinc-400 group-hover:text-zinc-200 transition-colors font-sans">
                        {step.title}
                      </span>
                      <span className="ml-auto text-xs text-zinc-600 shrink-0 pr-1">
                        ▸
                      </span>
                    </button>
                  )}
                </div>
              );
            })}
          </div>

          {!showAll &&
            normalizedSteps.some((s) => !expandedSteps.has(s.number)) && (
              <button
                onClick={handleShowAll}
                className="text-xs font-mono text-purple-400 border border-purple-800 hover:border-purple-600 rounded px-3.5 py-1.5 mt-1 transition-colors"
              >
                Show all steps ↓
              </button>
            )}
        </div>
      )}

      {/* Fallback: when steps are empty, show raw content as markdown */}
      {normalizedSteps.length === 0 && content && (
        <div className="border-2 border-t-0 border-zinc-700 px-6 py-5 bg-zinc-950">
          <SectionLabel>Solution</SectionLabel>
          <div className="prose prose-invert prose-sm max-w-none text-zinc-300 font-sans [&_.katex-display]:overflow-x-auto">
            <ReactMarkdown remarkPlugins={REMARK} rehypePlugins={REHYPE}>
              {content
                .replace(/^::cross-checked::.+\n\n/, "")
                .replace(/\n\n---\s*\n\*\*Practice check:\*\*[\s\S]*$/, "")
                .trimEnd()}
            </ReactMarkdown>
          </div>
        </div>
      )}

      {/* ── E: Metadata footer ─────────────────────────────────────────── */}
      <div className="border-2 border-t-0 border-zinc-700 px-5 py-2 bg-zinc-900 rounded-b-lg flex justify-end items-center">
        <Divider />
        <p className="text-xs font-mono text-zinc-600 text-right">
          {[
            model && `model: ${model}`,
            `confidence: ${Math.round(confidence * 100)}%`,
            duration && `${Math.round(duration)}ms`,
            status === "verified" && "engine: sympy",
          ]
            .filter(Boolean)
            .join("  ·  ")}
        </p>
      </div>
    </div>
  );
}
