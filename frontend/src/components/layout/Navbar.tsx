"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";
import type { User } from "@supabase/supabase-js";

export function Navbar() {
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    // Check active session
    supabase.auth.getSession().then(({ data: { session } }) => {
      setUser(session?.user ?? null);
    });

    // Listen to auth changes (login/logout)
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null);
    });

    return () => subscription.unsubscribe();
  }, []);

  const handleLogout = async () => {
    await supabase.auth.signOut();
  };

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 h-16 bg-[var(--bg-primary)]/80 backdrop-blur-lg border-b border-white/5">
      <div className="max-w-7xl mx-auto h-full flex items-center justify-between px-4">
        {/* Logo */}
        <Link href="/" className="text-xl font-bold bg-gradient-to-r from-indigo-400 to-purple-400 bg-clip-text text-transparent">
          Equated
        </Link>

        {/* Nav links */}
        <div className="flex items-center gap-4 sm:gap-6">
          <Link href="/chat" className="text-sm text-[var(--text-secondary)] hover:text-white transition-colors">
            Solver
          </Link>
          <Link href="/credits" className="text-sm text-[var(--text-secondary)] hover:text-white transition-colors">
            Credits
          </Link>
          
          {user ? (
            <div className="flex items-center gap-4 ml-2">
              <Link href="/settings" className="hidden sm:inline-block text-sm text-[var(--text-secondary)] hover:text-white transition-colors">
                {user.email?.split("@")[0] || "Profile"}
              </Link>
              <button
                onClick={handleLogout}
                className="text-sm px-4 py-2 bg-white/5 hover:bg-white/10 rounded-lg transition-colors border border-white/10"
              >
                Log Out
              </button>
            </div>
          ) : (
            <Link
              href="/auth/login"
              className="text-sm px-4 py-2 bg-indigo-600 hover:bg-indigo-500 rounded-lg transition-colors ml-2"
            >
              Log In
            </Link>
          )}
        </div>
      </div>
    </nav>
  );
}
