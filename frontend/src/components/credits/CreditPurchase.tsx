"use client";

import { useState } from "react";
import { api } from "@/lib/api";

const PACKS = [
  { id: "basic",    credits: 30,  price: "₹10",  popular: false },
  { id: "standard", credits: 100, price: "₹25",  popular: true },
  { id: "premium",  credits: 300, price: "₹50",  popular: false },
];

declare global {
  interface Window {
    Razorpay: any;
  }
}

export function CreditPurchase() {
  const [loading, setLoading] = useState<string | null>(null);

  const loadRazorpayScript = () => {
    return new Promise((resolve) => {
      const script = document.createElement("script");
      script.src = "https://checkout.razorpay.com/v1/checkout.js";
      script.onload = () => resolve(true);
      script.onerror = () => resolve(false);
      document.body.appendChild(script);
    });
  };

  const handlePurchase = async (packId: string) => {
    try {
      setLoading(packId);
      
      const res = await loadRazorpayScript();
      if (!res) {
        alert("Failed to load payment gateway. Are you online?");
        return;
      }

      // 1. Create order on backend
      const orderData = await api.createOrder(packId);
      
      // 2. Initialize Razorpay Checkout
      const options = {
        key: process.env.NEXT_PUBLIC_RAZORPAY_KEY_ID || "rzp_test_12345", // Test key fallback
        amount: orderData.amount,
        currency: orderData.currency,
        name: "Equated Credits",
        description: `${packId.toUpperCase()} Pack Upgrade`,
        order_id: orderData.id,
        handler: async function (response: any) {
          try {
            // 3. Verify payment on backend
            await api.purchaseCredits(
              packId,
              response.razorpay_payment_id,
              response.razorpay_order_id,
              response.razorpay_signature
            );
            alert("Payment successful! Credits added to your account.");
            window.location.reload(); // Refresh credits balance
          } catch (err: any) {
             alert("Payment verification failed: " + err.message);
          }
        },
        prefill: {
          name: "Equated User",
        },
        theme: {
          color: "#4f46e5", // Indigo-600
        },
      };

      const paymentObject = new window.Razorpay(options);
      paymentObject.open();

    } catch (error: any) {
      console.error("Purchase error:", error);
      alert("Error initializing payment: " + error.message);
    } finally {
      setLoading(null);
    }
  };

  return (
    <div className="p-6 rounded-2xl bg-[var(--bg-card)] border border-white/5">
      <h2 className="text-lg font-semibold mb-4">Credit Packs</h2>

      <div className="space-y-3">
        {PACKS.map((pack) => (
          <button
            key={pack.id}
            onClick={() => handlePurchase(pack.id)}
            disabled={loading !== null}
            className={`w-full p-4 rounded-xl border transition-all duration-200 text-left flex items-center justify-between ${
              pack.popular
                ? "border-indigo-500 bg-indigo-500/10 hover:bg-indigo-500/20"
                : "border-white/5 hover:border-white/10 hover:bg-white/5"
            } ${loading === pack.id ? "opacity-50 cursor-wait" : ""}`}
          >
            <div>
              <div className="font-semibold">{pack.credits} credits</div>
              <div className="text-sm text-[var(--text-secondary)]">
                {pack.price} • ₹{(parseFloat(pack.price.replace("₹", "")) / pack.credits).toFixed(2)}/solve
              </div>
            </div>
            <div className="flex items-center gap-2">
              {pack.popular && (
                <span className="text-xs px-2 py-1 rounded-full bg-indigo-500 text-white">Popular</span>
              )}
              {loading === pack.id ? (
                <span className="text-sm border border-indigo-500 text-indigo-400 px-3 py-1 rounded-full animate-pulse">Loading...</span>
              ) : (
                <span className="text-lg font-bold">{pack.price}</span>
              )}
            </div>
          </button>
        ))}
      </div>

      <p className="mt-4 text-xs text-center text-[var(--text-secondary)]">
        Powered by Razorpay • UPI, Cards, Wallets accepted
      </p>
    </div>
  );
}
