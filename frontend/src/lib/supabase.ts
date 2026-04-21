import { createClient } from "@supabase/supabase-js";

/**
 * Supabase client.
 * Falls back to empty strings when env vars are missing (local dev without auth).
 * Auth calls will simply return null sessions, and the app works in anonymous mode.
 */
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
const supabasePublishableKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY || "";

export const supabase = createClient(
  supabaseUrl || "https://placeholder.supabase.co",
  supabasePublishableKey || "placeholder-key"
);
