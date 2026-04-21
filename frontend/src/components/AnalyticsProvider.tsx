"use client";

import { useEffect } from "react";
import { usePathname } from "next/navigation";
import { supabase } from "@/lib/supabase";
import { initAnalytics, identifyUser } from "@/lib/analytics";

export function AnalyticsProvider({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();

  useEffect(() => {
    initAnalytics();

    // Identify the logged-in user so PostHog links events to a person
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (session?.user) {
        identifyUser(session.user.id, {
          email: session.user.email,
        });
      }
    });

    // Re-identify on auth state changes (login / logout)
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      if (session?.user) {
        identifyUser(session.user.id, { email: session.user.email });
      }
    });

    return () => subscription.unsubscribe();
  }, []);

  // PostHog auto-captures pageviews; no manual tracking needed per pathname change.
  void pathname;

  return <>{children}</>;
}
