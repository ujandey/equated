import { Sparkles, CheckCircle2 } from "lucide-react";

interface SolutionStep {
  step: number;
  rule: string;
  explanation: string;
}

interface Solution {
  problem_interpretation: string;
  concept_used: string;
  steps: SolutionStep[];
  final_answer: string;
  quick_summary: string;
  alternative_method?: string;
  common_mistakes?: string;
}

interface Props {
  solution: Solution;
}

export function SolutionCard({ solution }: Props) {
  return (
    <div className="space-y-12">
      {/* Concept Anchor */}
      <div className="flex items-start gap-4">
        <Sparkles className="w-5 h-5 text-primary mt-1 shrink-0" />
        <p className="font-label text-[0.875rem] leading-relaxed text-on-surface/90">
          <span className="font-bold text-primary mr-2">Concept Anchor:</span> 
          {solution.concept_used} {solution.problem_interpretation}
        </p>
      </div>

      {/* Steps List */}
      <div className="space-y-12">
        {solution.steps.map((step, idx) => (
          <div key={step.step} className="space-y-4 animate-slide-up group">
            <header className="flex justify-between items-end border-b border-border-glass pb-2">
              <h2 className="font-headline text-2xl text-on-surface">Derivation Phase {idx + 1}</h2>
              <span className="font-mono text-[10px] text-slate-500 uppercase tracking-widest pl-4 shrink-0">
                Step {String(idx + 1).padStart(2, '0')} / {String(solution.steps.length).padStart(2, '0')}
              </span>
            </header>
            <div className="grid grid-cols-1 md:grid-cols-5 gap-8">
              <div className="md:col-span-3">
                <p className="font-body text-[0.9375rem] text-on-surface/90 leading-relaxed">
                  {step.explanation}
                </p>
              </div>
              {step.rule && (
                <div className="md:col-span-2 bg-white/5 rounded-xl p-4 flex items-center justify-center border border-border-glass transition-colors group-hover:border-primary/20">
                  <code className="font-mono text-primary text-[0.875rem] text-center w-full break-normal whitespace-pre-wrap">
                    {step.rule}
                  </code>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Footer / Highlights */}
      <div className="pt-8 border-t border-border-glass space-y-4">
        {solution.quick_summary && (
          <p className="font-label text-sm text-slate-400">
            <span className="font-bold text-slate-300">Quick Summary:</span> {solution.quick_summary}
          </p>
        )}
        {solution.common_mistakes && (
          <p className="font-label text-sm text-error">
            <span className="font-bold">Avoid:</span> {solution.common_mistakes}
          </p>
        )}
      </div>

      {/* Final Answer Block */}
      <div className="pt-4">
        <div className="bg-primary p-6 rounded-xl flex items-center justify-between shadow-lg neon-glow">
          <div className="flex items-center gap-4">
            <CheckCircle2 className="w-8 h-8 text-background shrink-0" />
            <h3 className="font-headline text-xl md:text-3xl text-background font-black break-words pr-2">
              {solution.final_answer}
            </h3>
          </div>
          <button className="hidden sm:block shrink-0 bg-background text-primary px-4 py-2 rounded-full font-mono text-[10px] font-bold hover:scale-105 transition-transform border border-primary/20">
            SAVE_TO_ARCHIVE()
          </button>
        </div>
      </div>
    </div>
  );
}
