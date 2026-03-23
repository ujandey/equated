"use client";

import { useCredits } from "@/hooks/useCredits";

export function CreditBalance() {
  const { balance, loading } = useCredits();

  if (loading) {
    return (
      <div className="p-6 rounded-2xl bg-[var(--bg-card)] border border-white/5 animate-pulse">
        <div className="h-6 bg-white/5 rounded w-1/3 mb-4" />
        <div className="h-10 bg-white/5 rounded w-1/2" />
      </div>
    );
  }

  return (
    <div className="p-6 rounded-2xl bg-[var(--bg-card)] border border-white/5">
      <h2 className="text-lg font-semibold mb-4">Your Balance</h2>

      <div className="text-4xl font-bold text-indigo-400 mb-2">
        {balance?.credits ?? 0}
        <span className="text-base font-normal text-[var(--text-secondary)] ml-2">credits</span>
      </div>

      <div className="mt-4 space-y-2 text-sm text-[var(--text-secondary)]">
        <div className="flex justify-between">
          <span>Tier</span>
          <span className="capitalize font-medium text-white">{balance?.tier ?? "free"}</span>
        </div>
        <div className="flex justify-between">
          <span>Solves today</span>
          <span>{balance?.daily_solves_used ?? 0} / {balance?.daily_limit ?? 5}</span>
        </div>
      </div>

      {/* Daily usage bar */}
      <div className="mt-3 h-2 rounded-full bg-[var(--bg-secondary)] overflow-hidden">
        <div
          className="h-full bg-indigo-500 rounded-full transition-all duration-500"
          style={{
            width: `${Math.min(((balance?.daily_solves_used ?? 0) / (balance?.daily_limit ?? 5)) * 100, 100)}%`,
          }}
        />
      </div>
    </div>
  );
}
