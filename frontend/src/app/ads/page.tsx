"use client";

import { Sidebar } from "@/components/layout/Sidebar";
import { BannerAd } from "@/components/ads/BannerAd";
import { useState } from "react";
import { useCredits } from "@/hooks/useCredits";

export default function AdsPage() {
  const [isWatching, setIsWatching] = useState(false);
  const [timeLeft, setTimeLeft] = useState(30);
  const [message, setMessage] = useState("");
  const { addCredits } = useCredits();

  const handleWatchAd = () => {
    setIsWatching(true);
    setMessage("");
    let remaining = 30;
    
    // Simulate watching a video ad
    const interval = setInterval(() => {
      remaining -= 1;
      setTimeLeft(remaining);
      
      if (remaining <= 0) {
        clearInterval(interval);
        setIsWatching(false);
        setTimeLeft(30);
        addCredits(3); // Award 3 credits for full 30s ad
        setMessage("Reward granted! You earned 3 credits.");
      }
    }, 1000);
  };

  return (
    <div className="flex h-[calc(100vh-4rem)]">
      <Sidebar />
      <div className="flex-1 flex flex-col p-8 overflow-y-auto items-center">
        <div className="w-full max-w-4xl space-y-8">
          
          <div className="text-center space-y-4 mb-12">
            <h1 className="text-4xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-indigo-500">
              Watch & Earn
            </h1>
            <p className="text-lg text-[var(--text-secondary)]">
              Support Equated and earn free AI credits by watching short sponsored messages.
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            {/* Video Ad Card */}
            <div className="bg-[var(--bg-card)] border border-white/5 rounded-2xl p-8 flex flex-col items-center justify-center min-h-[300px] shadow-xl relative overflow-hidden group">
              <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-indigo-500 to-purple-500"></div>
              
              {isWatching ? (
                <div className="text-center space-y-6 w-full">
                  <div className="w-full h-4 bg-white/5 rounded-full overflow-hidden">
                    <div 
                      className="h-full bg-indigo-500 transition-all duration-1000 ease-linear"
                      style={{ width: `${((30 - timeLeft) / 30) * 100}%` }}
                    />
                  </div>
                  <p className="text-2xl font-mono text-indigo-400">{timeLeft}s remaining</p>
                  <p className="text-sm opacity-70">Please do not close this window</p>
                </div>
              ) : (
                <div className="text-center space-y-6">
                  <div className="w-20 h-20 bg-indigo-500/10 rounded-full flex items-center justify-center mx-auto text-4xl group-hover:scale-110 transition-transform">
                    ▶️
                  </div>
                  <div>
                    <h3 className="text-xl font-bold">Watch Video Ad</h3>
                    <p className="text-[var(--text-secondary)] mt-2">Earn 3 premium credits</p>
                  </div>
                  <button
                    onClick={handleWatchAd}
                    className="w-full py-4 bg-indigo-600 hover:bg-indigo-500 rounded-xl font-bold transition-all shadow-lg hover:shadow-indigo-500/25 active:scale-95 text-lg"
                  >
                    Start Watching (30s)
                  </button>
                </div>
              )}
            </div>

            {/* Status Card */}
            <div className="bg-[var(--bg-card)] border border-white/5 rounded-2xl p-8 flex flex-col justify-between shadow-xl">
              <div>
                <h3 className="text-xl font-bold mb-6">Today&apos;s Rewards</h3>
                <div className="space-y-4">
                  <div className="flex justify-between items-center p-4 bg-white/5 rounded-xl">
                    <span className="text-[var(--text-secondary)]">Ads Watched Today</span>
                    <span className="font-bold text-lg">0 / 5</span>
                  </div>
                  <div className="flex justify-between items-center p-4 bg-white/5 rounded-xl">
                    <span className="text-[var(--text-secondary)]">Credits Earned</span>
                    <span className="font-bold text-lg text-green-400">+0</span>
                  </div>
                </div>
              </div>

              {message && (
                <div className="mt-6 p-4 bg-green-500/10 border border-green-500/20 rounded-xl text-center text-green-400 animate-slide-up">
                  {message}
                </div>
              )}
            </div>
          </div>

          <div className="mt-12 w-full">
            <h3 className="text-lg font-bold mb-4 px-4 text-[var(--text-secondary)] uppercase tracking-wider text-sm">Sponsored Links</h3>
            <BannerAd />
          </div>

        </div>
      </div>
    </div>
  );
}
