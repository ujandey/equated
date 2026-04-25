"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Camera, Upload, X } from "lucide-react";
import { api, MultiQuestionResponse, QuestionOption, SolveResponse } from "@/lib/api";
import { QuestionSelector } from "./QuestionSelector";

interface ImageUploadProps {
  onClose: () => void;
  onSolveComplete: (result: SolveResponse) => void;
  sessionId?: string;
}

type UIState =
  | { kind: "idle" }
  | { kind: "preview"; file: File; previewUrl: string }
  | { kind: "loading"; phase: number }
  | { kind: "multi"; response: MultiQuestionResponse }
  | { kind: "error"; message: string; partial?: { id: string; text: string; latex: string }[] };

const LOADING_PHASES = [
  "Preprocessing image...",
  "Detecting questions...",
  "Extracting math...",
];

const ACCEPTED_TYPES = ["image/jpeg", "image/png", "image/webp", "image/heic"];
const ACCEPTED_EXTENSIONS = [".jpg", ".jpeg", ".png", ".webp", ".heic"];
const MAX_MB = 10;

function isAcceptedImage(file: File): boolean {
  if (ACCEPTED_TYPES.includes(file.type)) return true;
  const lowerName = file.name.toLowerCase();
  return ACCEPTED_EXTENSIONS.some((ext) => lowerName.endsWith(ext));
}

export function ImageUpload({ onClose, onSolveComplete, sessionId }: ImageUploadProps) {
  const [state, setState] = useState<UIState>({ kind: "idle" });
  const [dragOver, setDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const phaseTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Cycle loading phase text
  useEffect(() => {
    if (state.kind !== "loading") return;
    phaseTimerRef.current = setInterval(() => {
      setState((prev) =>
        prev.kind === "loading"
          ? { ...prev, phase: (prev.phase + 1) % LOADING_PHASES.length }
          : prev,
      );
    }, 1200);
    return () => {
      if (phaseTimerRef.current) clearInterval(phaseTimerRef.current);
    };
  }, [state.kind]);

  useEffect(() => {
    if (state.kind !== "preview") return;
    return () => URL.revokeObjectURL(state.previewUrl);
  }, [state]);

  const handleFile = useCallback((file: File) => {
    if (!isAcceptedImage(file)) {
      setState({ kind: "error", message: "Please upload a JPG, PNG, WebP, or HEIC image." });
      return;
    }
    if (file.size > MAX_MB * 1024 * 1024) {
      setState({ kind: "error", message: `Image too large. Max ${MAX_MB}MB.` });
      return;
    }
    const previewUrl = URL.createObjectURL(file);
    setState({ kind: "preview", file, previewUrl });
  }, []);

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile],
  );

  const handleInputChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  };

  const analyze = async () => {
    if (state.kind !== "preview") return;
    const { file } = state;
    setState({ kind: "loading", phase: 0 });
    try {
      const result = await api.solveImage(file, sessionId);
      if (result.status === "multi_question") {
        setState({ kind: "multi", response: result as MultiQuestionResponse });
      } else {
        onSolveComplete(result as SolveResponse);
        onClose();
      }
    } catch (err: any) {
      const payload = err?.payload?.detail ?? err?.payload ?? {};
      if (payload?.error === "low_confidence") {
        setState({
          kind: "error",
          message: payload.message ?? "Could not read the image clearly.",
          partial: payload.partial_questions ?? [],
        });
      } else if (err?.status === 413) {
        setState({ kind: "error", message: `Image too large. Max ${MAX_MB}MB.` });
      } else if (err?.status === 415) {
        setState({ kind: "error", message: "Please upload a JPG, PNG, WebP, or HEIC image." });
      } else {
        setState({
          kind: "error",
          message: "Image parsing unavailable. Type your question instead.",
        });
      }
    }
  };

  const handleQuestionSelected = async (questionId: string, questions: QuestionOption[]) => {
    setState({ kind: "loading", phase: 0 });
    try {
      const result = await api.selectQuestion(questionId, questions, "", sessionId);
      onSolveComplete(result as SolveResponse);
      onClose();
    } catch {
      setState({ kind: "error", message: "Something went wrong. Please try again." });
    }
  };

  const prefillManual = (text: string) => {
    onClose();
    // Dispatch a custom event that ChatWindow listens for to prefill the input
    window.dispatchEvent(new CustomEvent("equated:prefill", { detail: { text } }));
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative z-10 w-full max-w-lg bg-[#0d0d0d] border border-white/10 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-white/10">
          <span className="font-mono text-xs uppercase tracking-widest text-slate-400">
            Upload Image
          </span>
          <button
            onClick={onClose}
            className="text-slate-500 hover:text-white transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-6">
          {/* ── Idle: drop zone ── */}
          {state.kind === "idle" && (
            <div
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`border-2 border-dashed transition-all cursor-pointer flex flex-col items-center justify-center gap-4 py-16 px-8 ${
                dragOver
                  ? "border-violet-500 bg-violet-500/5"
                  : "border-white/10 hover:border-white/25 bg-white/[0.02]"
              }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept={ACCEPTED_TYPES.join(",")}
                className="hidden"
                onChange={handleInputChange}
              />
              <div className="flex gap-4 text-slate-500">
                <Upload className="w-8 h-8" />
                <Camera className="w-8 h-8" />
              </div>
              <div className="text-center">
                <p className="font-mono text-sm text-slate-300">
                  Drop image here or{" "}
                  <span className="text-violet-400 underline underline-offset-2">browse</span>
                </p>
                <p className="font-mono text-xs text-slate-600 mt-2">
                  JPG · PNG · WebP · HEIC &nbsp;·&nbsp; Max {MAX_MB}MB
                </p>
              </div>
            </div>
          )}

          {/* ── Preview ── */}
          {state.kind === "preview" && (
            <div className="space-y-4">
              <div className="relative border border-white/10 overflow-hidden">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img
                  src={state.previewUrl}
                  alt="Preview"
                  className="w-full max-h-72 object-contain bg-black/30"
                />
              </div>
              <div className="flex gap-3">
                <button
                  onClick={analyze}
                  className="flex-1 bg-violet-600 hover:bg-violet-500 text-white font-mono text-xs uppercase tracking-widest py-3 transition-colors"
                >
                  Analyze Image →
                </button>
                <button
                  onClick={() => {
                    URL.revokeObjectURL(state.previewUrl);
                    setState({ kind: "idle" });
                  }}
                  className="px-4 py-3 border border-white/10 text-slate-400 hover:text-white font-mono text-xs transition-colors"
                >
                  Change
                </button>
              </div>
            </div>
          )}

          {/* ── Loading ── */}
          {state.kind === "loading" && (
            <div className="flex flex-col items-center justify-center py-16 gap-5">
              <div className="w-8 h-8 border-2 border-violet-500/30 border-t-violet-500 rounded-full animate-spin" />
              <p className="font-mono text-xs uppercase tracking-widest text-slate-400 animate-pulse">
                {LOADING_PHASES[state.phase]}
              </p>
            </div>
          )}

          {/* ── Multi-question ── */}
          {state.kind === "multi" && (
            <QuestionSelector
              response={state.response}
              onSelect={handleQuestionSelected}
            />
          )}

          {/* ── Error ── */}
          {state.kind === "error" && (
            <div className="space-y-5">
              <div className="border border-red-500/20 bg-red-500/5 p-4">
                <p className="font-mono text-sm text-red-400">{state.message}</p>
                {state.partial && state.partial.length > 0 && (
                  <div className="mt-3 space-y-2">
                    <p className="font-mono text-xs text-slate-500 uppercase tracking-widest">
                      Partial extraction:
                    </p>
                    {state.partial.map((q) => (
                      <div key={q.id} className="border border-white/5 bg-white/[0.03] p-3">
                        <p className="font-mono text-xs text-slate-300">{q.text}</p>
                      </div>
                    ))}
                    <button
                      onClick={() => prefillManual(state.partial![0].text)}
                      className="w-full mt-2 border border-violet-500/30 text-violet-400 hover:bg-violet-500/10 font-mono text-xs uppercase tracking-widest py-2 transition-colors"
                    >
                      Type it manually instead →
                    </button>
                  </div>
                )}
              </div>
              <button
                onClick={() => setState({ kind: "idle" })}
                className="w-full border border-white/10 text-slate-400 hover:text-white font-mono text-xs uppercase tracking-widest py-3 transition-colors"
              >
                Try another image
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
