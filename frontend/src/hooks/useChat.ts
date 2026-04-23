"use client";

import { useState, useCallback } from "react";
import { supabase } from "@/lib/supabase";
import { trackEvent } from "@/lib/analytics";
import { useChatStore } from "@/store/chatStore";
import type { Message, SolutionMeta } from "@/types/message";

const MAX_RETRIES = 3;
const RETRYABLE_STATUSES = new Set([502, 503, 504]);

/** Fetch with automatic retry for network failures and 5xx server errors. */
async function fetchWithRetry(
  url: string,
  options: RequestInit,
  retries = MAX_RETRIES,
): Promise<Response> {
  for (let attempt = 0; attempt <= retries; attempt++) {
    try {
      const response = await fetch(url, options);
      // 4xx errors are definitive — return immediately without retrying.
      if (response.status >= 400 && response.status < 500) return response;
      // 5xx — retry unless this is the last attempt.
      if (RETRYABLE_STATUSES.has(response.status) && attempt < retries) {
        await delay(1000 * Math.pow(2, attempt));
        continue;
      }
      return response;
    } catch {
      // Network error (offline, DNS failure, etc.)
      if (attempt === retries) throw new Error("Network error — check your connection and try again.");
      await delay(1000 * Math.pow(2, attempt));
    }
  }
  throw new Error("Max retries exceeded");
}

function delay(ms: number) {
  return new Promise<void>((resolve) => setTimeout(resolve, ms));
}

export function useChat() {
  const { messages, addMessage, sessionId, setSessionId, replaceMessages } = useChatStore();
  const [isLoading, setIsLoading] = useState(false);

  const sendMessage = useCallback(
    async (content: string) => {
      const userMsg: Message = {
        id: crypto.randomUUID(),
        role: "user",
        content,
        created_at: new Date().toISOString(),
      };
      addMessage(userMsg);
      setIsLoading(true);
      const sendStart = performance.now();

      trackEvent("message_sent", { content_length: content.length });

      try {
        const { data: { session } } = await supabase.auth.getSession();
        const token = session?.access_token;
        const authHeaders: Record<string, string> = token
          ? { Authorization: `Bearer ${token}` }
          : {};

        await handleStreamMode(content, userMsg, authHeaders, sendStart);
      } catch (error) {
        const errDetail =
          error instanceof Error ? error.message : "Something went wrong";
        trackEvent("chat_error", {
          error: errDetail,
          latency_ms: Math.round(performance.now() - sendStart),
        });
        const errorMsg: Message = {
          id: crypto.randomUUID(),
          role: "assistant",
          content: "",
          created_at: new Date().toISOString(),
          metadata: { error: errDetail, retryContent: content },
        };
        addMessage(errorMsg);
      } finally {
        setIsLoading(false);
      }
    },
    [addMessage, replaceMessages],
  );

  /**
   * CHAT/STREAM MODE — SSE streaming with retry, 429 awareness, and
   * verification metadata extraction.
   */
  async function handleStreamMode(
    content: string,
    userMsg: Message,
    authHeaders: Record<string, string>,
    sendStart: number,
  ) {
    const assistantId = crypto.randomUUID();
    addMessage({
      id: assistantId,
      role: "assistant",
      content: "",
      created_at: new Date().toISOString(),
    });

    const payload: Record<string, unknown> = { content, stream: true };
    const currentSessionId = useChatStore.getState().sessionId;
    if (currentSessionId) payload.session_id = currentSessionId;

    const response = await fetchWithRetry("/api/v1/chat/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...authHeaders },
      body: JSON.stringify(payload),
    });

    // ── Rate limit ──────────────────────────────────────────────────────────
    if (response.status === 429) {
      const body = await response.json().catch(() => ({}));
      const retryAfterSeconds: number = body.retry_after_seconds ?? 60;
      trackEvent("rate_limit_hit", { retry_after_seconds: retryAfterSeconds });
      useChatStore.setState((state) => ({
        messages: state.messages.map((m) =>
          m.id === assistantId
            ? {
                ...m,
                metadata: {
                  error: `Rate limit reached — please wait ${retryAfterSeconds}s before trying again.`,
                  retryContent: content,
                  rateLimited: true,
                  retryAfterSeconds,
                },
              }
            : m,
        ),
      }));
      return;
    }

    if (!response.ok) {
      const err = await response.json().catch(() => ({ detail: response.statusText }));
      throw new Error(err.detail || err.message || `Chat failed (${response.status})`);
    }

    // ── Stream reading ───────────────────────────────────────────────────────
    const reader = response.body?.getReader();
    const decoder = new TextDecoder();
    let currentContent = "";
    let finalModel = "";
    let finalDuration = 0;
    let contextReset = false;
    let verified: boolean | undefined;
    let verificationConfidence: "high" | "medium" | "low" | undefined;
    let finalIntent: string | undefined;
    let finalSolution: SolutionMeta | undefined;

    if (!reader) throw new Error("No response body available.");

    // Buffer for SSE lines that may span multiple read() chunks.
    let lineBuffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      lineBuffer += decoder.decode(value, { stream: true });
      const lines = lineBuffer.split("\n");
      // Keep the last (possibly incomplete) line in the buffer.
      lineBuffer = lines.pop() ?? "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const dataStr = line.slice(6).trim();
        if (dataStr === "[DONE]") break;

        try {
          const event = JSON.parse(dataStr);

          if (event.type === "token") {
            currentContent += event.content;
            useChatStore.setState((state) => ({
              messages: state.messages.map((m) =>
                m.id === assistantId ? { ...m, content: currentContent } : m,
              ),
            }));
          } else if (event.type === "done") {
            finalModel = event.model || "";
            finalDuration = event.duration_ms || 0;
            contextReset = Boolean(event.context_reset);
            if (typeof event.verified === "boolean") verified = event.verified;
            if (event.verification_confidence) {
              verificationConfidence = event.verification_confidence as
                | "high"
                | "medium"
                | "low";
            }
            if (event.intent) finalIntent = event.intent as string;
            if (event.solution) finalSolution = event.solution as SolutionMeta;
            if (event.session_id) {
              useChatStore.getState().setSessionId(event.session_id);
            }
          } else if (event.type === "error") {
            useChatStore.setState((state) => ({
              messages: state.messages.map((m) =>
                m.id === assistantId
                  ? {
                      ...m,
                      content: currentContent,
                      metadata: {
                        ...m.metadata,
                        error: event.message,
                        retryContent: content,
                      },
                    }
                  : m,
              ),
            }));
          }
        } catch {
          // Incomplete JSON across chunk boundary — skip and continue.
        }
      }
    }

    // ── Final metadata update ────────────────────────────────────────────────
    const finalize = (stateMessages: Message[]) =>
      stateMessages.map((m) =>
        m.id === assistantId
          ? {
              ...m,
              content: currentContent,
              metadata: {
                ...m.metadata,
                ...(finalModel && { model: finalModel }),
                ...(finalDuration && { duration: finalDuration }),
                ...(verified !== undefined && { verified }),
                ...(verificationConfidence && { verificationConfidence }),
                ...(finalIntent && { intent: finalIntent }),
                ...(finalSolution && { solution: finalSolution }),
              },
            }
          : m,
      );

    trackEvent("response_received", {
      model: finalModel,
      latency_ms: Math.round(performance.now() - sendStart),
      server_duration_ms: finalDuration,
      verified,
      verification_confidence: verificationConfidence,
    });

    if (contextReset) {
      const pair = useChatStore
        .getState()
        .messages.filter((m) => m.id === userMsg.id || m.id === assistantId);
      replaceMessages(finalize(pair));
    } else {
      useChatStore.setState((state) => ({ messages: finalize(state.messages) }));
    }
  }

  return { messages, isLoading, sendMessage };
}
