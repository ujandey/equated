"use client";

import { useState, useCallback } from "react";
import { supabase } from "@/lib/supabase";
import { useChatStore } from "@/store/chatStore";
import type { Message } from "@/types/message";

export function useChat() {
  const { messages, addMessage, sessionId, setSessionId, replaceMessages } = useChatStore();
  const [isLoading, setIsLoading] = useState(false);

  const sendMessage = useCallback(
    async (content: string) => {
      // Add user message locally
      const userMsg: Message = {
        id: crypto.randomUUID(),
        role: "user",
        content,
        created_at: new Date().toISOString(),
      };
      addMessage(userMsg);

      setIsLoading(true);
      try {
        // Create initial empty assistant message
        const assistantId = crypto.randomUUID();
        const assistantMsg: Message = {
          id: assistantId,
          role: "assistant",
          content: "",
          created_at: new Date().toISOString(),
        };
        addMessage(assistantMsg);

        // Fetch user auth token
        const { data: { session } } = await supabase.auth.getSession();
        const token = session?.access_token;
        
        // Build payload including session_id if it exists
        const payload: any = { content, stream: true };
        if (useChatStore.getState().sessionId) {
          payload.session_id = useChatStore.getState().sessionId;
        }

        // Use relative URL so requests route through Next.js proxy (avoids CORS)
        const response = await fetch(`/api/v1/chat/stream`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            ...(token ? { Authorization: `Bearer ${token}` } : {}),
          },
          body: JSON.stringify(payload),
        });

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }

        const reader = response.body?.getReader();
        const decoder = new TextDecoder();
        let currentContent = "";
        let finalModel = "";
        let finalDuration = 0;
        let contextReset = false;

        if (reader) {
          while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            const chunk = decoder.decode(value, { stream: true });
            const lines = chunk.split("\n");

            for (const line of lines) {
              if (line.startsWith("data: ")) {
                const dataStr = line.replace("data: ", "").trim();
                if (dataStr === "[DONE]") break;

                try {
                  const event = JSON.parse(dataStr);
                  
                  if (event.type === "token") {
                    currentContent += event.content;
                    useChatStore.setState((state) => ({
                      messages: state.messages.map((m) =>
                        m.id === assistantId ? { ...m, content: currentContent } : m
                      )
                    }));
                  } else if (event.type === "done") {
                    // Capture metadata and session_id upon completion
                    finalModel = event.model || "";
                    finalDuration = event.duration_ms || 0;
                    contextReset = Boolean(event.context_reset);
                    
                    if (event.session_id) {
                       useChatStore.getState().setSessionId(event.session_id);
                    }
                  } else if (event.type === "error") {
                    console.error("Stream error:", event.message);
                    useChatStore.setState((state) => ({
                      messages: state.messages.map((m) =>
                        m.id === assistantId
                          ? { ...m, content: currentContent + "\n\n*(Error: " + event.message + ")*" }
                          : m
                      )
                    }));
                  }
                } catch (e) {
                  // Ignore incomplete JSON chunks from split network boundaries
                }
              }
            }
          }
          
          // Final update with metadata
          if (finalModel) {
             const finalizeMessages = (stateMessages: Message[]) =>
               stateMessages.map((m) =>
                 m.id === assistantId ? {
                   ...m,
                   content: currentContent,
                   metadata: { ...m.metadata, model: finalModel, duration: finalDuration }
                 } : m
               );

             if (contextReset) {
               const currentPair = useChatStore.getState().messages.filter(
                 (m) => m.id === userMsg.id || m.id === assistantId
               );
               replaceMessages(finalizeMessages(currentPair));
             } else {
               useChatStore.setState((state) => ({
                  messages: finalizeMessages(state.messages)
               }));
             }
          }
        }
      } catch (error) {
        console.error("Chat error:", error);
        const errorMsg: Message = {
          id: crypto.randomUUID(),
          role: "assistant",
          content: "Sorry, something went wrong. Please try again.",
          created_at: new Date().toISOString(),
        };
        addMessage(errorMsg);
      } finally {
        setIsLoading(false);
      }
    },
    [addMessage, replaceMessages]
  );

  return { messages, isLoading, sendMessage };
}
