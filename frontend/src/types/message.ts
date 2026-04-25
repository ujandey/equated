/**
 * Message type shared across chat components.
 */

export interface SolutionStep {
  step?: number;
  rule?: string;
  explanation: string;
  // New structured fields
  number?: number;
  title?: string;
  equation?: string | null;
}

/** Structured solution data injected into message metadata on solve responses. */
export interface SolutionMeta {
  problem_interpretation: string;
  concept_used: string;
  concept_explanation?: string;
  subject_hint?: string;
  quick_summary: string;
  answer_summary?: string;
  final_answer: string;
  steps: SolutionStep[];
  verification_status?: 'verified' | 'unverified' | 'partial';
  confidence?: number;
}

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
  metadata?: {
    structured?: any;              // legacy field (unused — kept for compat)
    model?: string;
    cached?: boolean;
    tokens?: number;
    duration?: number;
    error?: string;                // Error detail for error recovery UX
    retryContent?: string;         // Original user query for retry button
    verified?: boolean;            // Whether the math engine verified the answer
    verificationConfidence?: "high" | "medium" | "low";
    rateLimited?: boolean;         // True when the server returned 429
    retryAfterSeconds?: number;    // Seconds to wait before retrying after a rate limit
    intent?: string;               // "solve" | "explain" | "unclear" — set on done event
    solution?: SolutionMeta;       // Populated for solve responses after done event
  };
}

export interface Session {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count?: number;
}
