/**
 * Message type shared across chat components.
 */

export interface Message {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  created_at: string;
  metadata?: {
    structured?: any;    // Structured solution response
    model?: string;
    cached?: boolean;
    tokens?: number;
  };
}

export interface Session {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count?: number;
}
