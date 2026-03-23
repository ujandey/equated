"use client";

import { useState, useEffect } from "react";
import { api } from "@/lib/api";

interface CreditData {
  credits: number;
  tier: string;
  daily_solves_used: number;
  daily_limit: number;
}

export function useCredits() {
  const [balance, setBalance] = useState<CreditData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadBalance();
  }, []);

  const loadBalance = async () => {
    try {
      const data = await api.getCredits();
      setBalance(data);
    } catch {
      setBalance(null);
    } finally {
      setLoading(false);
    }
  };

  const addCredits = (amount: number) => {
    if (balance) {
      setBalance({ ...balance, credits: balance.credits + amount });
    }
  };

  return { balance, loading, refresh: loadBalance, addCredits };
}
