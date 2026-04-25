/**
 * Backend API client with typed helper methods.
 */

import { supabase } from "./supabase";

// ── Image OCR types ──────────────────────────────────────────────────────────

export interface QuestionOption {
  id: string;
  text: string;
  latex: string;
  subject_hint: string;
}

export interface MultiQuestionResponse {
  status: "multi_question";
  questions: QuestionOption[];
  image_type: string;
  engine_used: string;
}

const getBaseUrl = () => {
  if (typeof window === "undefined") {
    // Server-side: need actual backend URL for SSR
    return process.env.NEXT_INTERNAL_BACKEND_URL || "http://127.0.0.1:8000";
  }
  // Client-side: use empty string so requests become relative URLs
  // routed through Next.js rewrite proxy (avoids CORS)
  return "";
};

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;
  const baseUrl = getBaseUrl();

  const res = await fetch(`${baseUrl}${path}`, {
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
    ...options,
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ message: res.statusText }));
    throw new Error(error.message || error.detail || "API request failed");
  }
  return res.json();
}

async function requestForm<T>(path: string, body: FormData): Promise<T> {
  const { data: { session } } = await supabase.auth.getSession();
  const token = session?.access_token;
  const baseUrl = getBaseUrl();

  const res = await fetch(`${baseUrl}${path}`, {
    method: "POST",
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body,
  });
  if (!res.ok) {
    // Propagate structured error payloads (e.g. low_confidence with partial_questions)
    const error = await res.json().catch(() => ({ message: res.statusText }));
    const err = new Error(error.message || error.detail?.message || "API request failed") as any;
    err.status = res.status;
    err.payload = error;
    throw err;
  }
  return res.json();
}

// ── Solve response types ─────────────────────────────────────────────────────

export interface SolutionStepResponse {
  number?: number;
  title?: string;
  explanation: string;
  equation?: string | null;
  step?: number;
  rule?: string;
}

export interface SolveResponse {
  solve_id: string;
  session_id?: string | null;
  problem_interpretation: string;
  concept_used: string;
  concept_explanation: string;
  subject_hint: string;
  steps: SolutionStepResponse[];
  final_answer: string;
  quick_summary: string;
  answer_summary: string;
  alternative_method: string | null;
  common_mistakes: string | null;
  model_used: string;
  parser_source: string | null;
  parser_confidence: string | null;
  verified: boolean;
  verification_confidence: string | null;
  verification_status: 'verified' | 'unverified' | 'partial';
  math_check_passed: boolean;
  math_engine_result: string | null;
  confidence: number;
  cached: boolean;
  credits_remaining: number | null;
  debug: Record<string, unknown> | null;
}

export const api = {
  // Solver
  solve: (data: { question: string; input_type?: string; session_id?: string; stream?: boolean }) =>
    request<SolveResponse>("/api/v1/solve", { method: "POST", body: JSON.stringify(data) }),

  // Chat Sessions
  createSession: (title: string = "New Chat") =>
    request<any>("/api/v1/chat/sessions", { method: "POST", body: JSON.stringify({ title }) }),
  getSessions: (limit: number = 20) =>
    request<any>(`/api/v1/chat/sessions?limit=${limit}`),
  getSession: (sessionId: string) =>
    request<any>(`/api/v1/chat/sessions/${sessionId}`),
  updateSessionHeadline: (sessionId: string, title: string) =>
    request<any>(`/api/v1/chat/sessions/${sessionId}`, { method: "PATCH", body: JSON.stringify({ title }) }),
  deleteSession: (sessionId: string) =>
    request<any>(`/api/v1/chat/sessions/${sessionId}`, { method: "DELETE" }),

  // Credits
  getCredits: () => request<any>("/api/v1/credits/balance"),
  getPacks: () => request<any>("/api/v1/credits/packs"),
  createOrder: (packId: string) =>
    request<any>("/api/v1/credits/create-order", {
      method: "POST",
      body: JSON.stringify({ pack_id: packId }),
    }),
  purchaseCredits: (packId: string, paymentId: string, orderId?: string, signature?: string) =>
    request<any>("/api/v1/credits/purchase", {
      method: "POST",
      body: JSON.stringify({ 
        pack_id: packId, 
        payment_id: paymentId,
        order_id: orderId || "",
        signature: signature || ""
      }),
    }),

  // Analytics
  getMyUsage: () => request<any>("/api/v1/analytics/my-usage"),

  // Health
  health: () => request<any>("/api/health"),

  // Image OCR solve
  solveImage: (file: File, sessionId?: string): Promise<any | MultiQuestionResponse> => {
    const form = new FormData();
    form.append("file", file);
    if (sessionId) form.append("session_id", sessionId);
    return requestForm("/api/v1/solve/image", form);
  },

  selectQuestion: (
    questionId: string,
    questions: QuestionOption[],
    userId: string,
    sessionId?: string,
  ): Promise<any> =>
    request("/api/v1/solve/image/select", {
      method: "POST",
      body: JSON.stringify({ question_id: questionId, questions, user_id: userId, session_id: sessionId }),
    }),
};
