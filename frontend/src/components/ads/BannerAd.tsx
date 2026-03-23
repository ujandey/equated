"use client";

export function BannerAd() {
  const adsEnabled = process.env.NEXT_PUBLIC_ENABLE_ADS === "true";

  if (!adsEnabled) return null;

  return (
    <div className="px-4 py-2 border-t border-white/5">
      <div className="max-w-4xl mx-auto text-center">
        <div className="h-[50px] rounded-lg bg-[var(--bg-secondary)] border border-white/5 flex items-center justify-center text-xs text-[var(--text-secondary)]">
          {/* Ad network script loads here */}
          <span>Ad Space • Non-intrusive banner</span>
        </div>
      </div>
    </div>
  );
}
