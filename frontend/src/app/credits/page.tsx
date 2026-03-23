"use client";

import { CreditBalance } from "@/components/credits/CreditBalance";
import { CreditPurchase } from "@/components/credits/CreditPurchase";

export default function CreditsPage() {
  return (
    <div className="max-w-4xl mx-auto px-4 py-10">
      <h1 className="text-3xl font-bold mb-8">Credits & Usage</h1>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
        <CreditBalance />
        <CreditPurchase />
      </div>
    </div>
  );
}
