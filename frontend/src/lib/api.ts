/**
 * Backend API client with typed helper methods.
 */

import { supabase } from "./supabase";

const getBaseUrl = () => {
  if (typeof window === "undefined") {
    // Server-side: need actual backend URL for SSR
    return process.env.NEXT_INTERNAL_BACKEND_URL || "http://localhost:8000";
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

export const api = {
  // Solver
  solve: (data: { question: string; input_type?: string; session_id?: string; stream?: boolean }) =>
    request<any>("/api/v1/solve", { method: "POST", body: JSON.stringify(data) }),

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
};
