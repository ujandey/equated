/**
 * Message type shared across chat components.
 */

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
  metadata?: {
    structured?: any;              // Structured solution response (SolveResponse JSON)
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
  };
}

export interface Session {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count?: number;
}
