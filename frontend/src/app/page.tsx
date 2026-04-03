"use client";

import Link from "next/link";
import { Terminal, CheckCircle } from "lucide-react";

export default function HomePage() {
  return (
    <div
      className="h-screen w-full overflow-y-auto overflow-x-hidden text-tertiary selection:bg-primary selection:text-white cursor-crosshair relative pb-20"
      style={{
        backgroundColor: "#09090b",
        backgroundImage: "radial-gradient(circle at 2px 2px, rgba(139, 92, 246, 0.05) 1px, transparent 0)",
        backgroundSize: "32px 32px"
      }}
    >
      <div className="noise-overlay"></div>

      {/* TopNavBar */}
      <nav className="bg-background/80 backdrop-blur-md flex justify-between items-center w-full px-6 md:px-12 py-6 fixed top-0 z-50 border-b border-white/5">
        <div className="font-serif italic text-2xl tracking-tighter text-on-surface">
          EQUATED
        </div>
        <div className="hidden md:flex gap-12">
          <Link href="#" className="text-primary font-bold border-b-2 border-primary font-mono text-xs uppercase tracking-widest hover:text-primary/80 transition-colors duration-100">Archive</Link>
          <Link href="#" className="text-on-surface opacity-60 font-mono text-xs uppercase tracking-widest hover:text-primary transition-colors duration-100">Logos</Link>
          <Link href="#" className="text-on-surface opacity-60 font-mono text-xs uppercase tracking-widest hover:text-primary transition-colors duration-100">Theory</Link>
        </div>
        <Link
          href="/chat"
          className="bg-primary text-white px-6 py-2.5 rounded-full font-mono text-xs uppercase tracking-widest border border-primary/20 hover:bg-transparent hover:text-primary hover:border-primary transition-all duration-300 primary-glow-hover"
        >
          Solve First Question Free
        </Link>
      </nav>

      <main className="pt-32">
        {/* Hero Section */}
        <section className="relative px-6 md:px-12 py-20 min-h-[819px] flex flex-col xl:flex-row gap-20 items-start">
          {/* Background Decoration */}
          <div className="ghost-symbol absolute -top-10 -right-20 text-[20rem] text-primary opacity-5 hidden lg:block">∫</div>

          <div className="flex-1 max-w-3xl z-10 w-full">
            <p className="font-mono text-primary text-xs tracking-[0.3em] mb-8 uppercase flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-primary animate-pulse"></span>
              LOGIC-TERMINAL-v5.0
            </p>
            <h1 className="font-serif text-5xl md:text-8xl text-on-surface leading-[0.95] mb-12 tracking-tighter">
              The tutor most <span className="italic text-primary">students</span> <br /> can afford.
            </h1>
            <p className="font-mono text-base md:text-lg text-outline leading-relaxed max-w-xl mb-12">
              Equated explains every step. Not just the answer — the understanding behind it. Theoretical rigor meets computational speed in a luminous environment.
            </p>
            <div className="flex flex-col sm:flex-row gap-6 w-full">
              <Link href="/chat" className="bg-primary text-center text-white px-10 py-5 rounded-full font-mono text-sm font-bold uppercase tracking-widest hover:scale-105 transition-all duration-300 primary-glow-hover">
                → [EXECUTE_SOLVE]
              </Link>
              <button className="glass-panel text-center px-10 py-5 rounded-full font-mono text-sm uppercase tracking-widest text-on-surface hover:border-primary hover:text-primary transition-all duration-300">
                View Archive
              </button>
            </div>
          </div>

          {/* Problem Animated Placeholder */}
          <div className="flex-1 w-full bg-surface-container rounded-2xl p-6 md:p-8 border border-white/10 shadow-2xl relative overflow-hidden group">
            <div className="absolute inset-0 bg-gradient-to-br from-primary/5 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500"></div>
            <div className="absolute top-4 right-4 text-[10px] font-mono text-secondary opacity-50">SYNC: READY</div>
            <div className="font-mono text-sm space-y-4 relative z-10">
              <div className="text-secondary opacity-60"># INPUT_PROMPT</div>
              <div className="text-on-surface text-xl">∫ x² · sin(x) dx</div>

              <div className="mt-8 pt-8 border-t border-white/5">
                <div className="flex items-center gap-4 text-secondary">
                  <Terminal className="w-4 h-4" />
                  <span className="text-xs tracking-widest">CALCULATING REASONING PATH...</span>
                </div>

                <div className="mt-4 space-y-6">
                  <div className="bg-surface-container-low rounded-xl p-4 border border-white/5">
                    <span className="text-primary text-[10px] block mb-2 font-bold">STEP 01: Integration by Parts</span>
                    <span className="text-on-surface/80 leading-relaxed">Let u = x², dv = sin(x)dx. Thus du = 2xdx, v = -cos(x).</span>
                  </div>
                  <div className="bg-surface-container-low rounded-xl p-4 border border-white/5 opacity-50">
                    <span className="text-primary text-[10px] block mb-2 font-bold">STEP 02: Apply Formula</span>
                    <span className="text-on-surface/80 leading-relaxed">-x²cos(x) - ∫(-cos(x) · 2x)dx</span>
                  </div>
                  <div className="text-secondary animate-pulse px-2">_</div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Social Proof Strip */}
        <section className="bg-surface-container-lowest border-y border-white/5 py-16 px-6 md:px-12 overflow-hidden">
          <div className="flex flex-wrap justify-between items-center gap-12 font-mono text-xs tracking-widest uppercase">
            <div className="flex flex-col gap-1 mx-auto text-center md:text-left md:mx-0">
              <span className="text-primary text-3xl font-bold">47,000+</span>
              <span className="text-outline">Problems Solved</span>
            </div>
            <div className="flex flex-col gap-1 mx-auto text-center md:text-left md:mx-0">
              <span className="text-secondary text-3xl font-bold">4.2s</span>
              <span className="text-outline">Average Solve Time</span>
            </div>
            <div className="flex flex-col gap-1 mx-auto text-center md:text-left md:mx-0">
              <span className="text-on-surface text-3xl font-bold tracking-tighter">SYMPY_VERIFIED</span>
              <span className="text-outline">Step Accuracy Matrix</span>
            </div>
            <div className="hidden lg:block text-outline opacity-40 italic">
              Coordinates: 28.6139° N, 77.2090° E
            </div>
          </div>
        </section>

        {/* Value Section */}
        <section className="px-6 md:px-12 py-32 space-y-32 bg-background">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-16 relative w-full">
            {/* Reasoning */}
            <div className="relative group p-8 rounded-2xl transition-all duration-300 hover:bg-white/5">
              <div className="ghost-symbol absolute -top-10 -left-6 text-[12rem] text-primary opacity-5 transition-all duration-300 group-hover:opacity-10 hidden md:block">∫</div>
              <div className="relative z-10 md:pt-12">
                <h3 className="font-serif text-3xl text-on-surface mb-6">Theoretical Reasoning</h3>
                <p className="font-mono text-sm text-outline leading-relaxed">We don&apos;t provide final values. We reconstruct the cognitive map required to derive them, emphasizing first principles over rote memorization.</p>
              </div>
            </div>

            {/* Concept */}
            <div className="relative group p-8 rounded-2xl transition-all duration-300 hover:bg-white/5">
              <div className="ghost-symbol absolute -top-10 -left-6 text-[12rem] text-secondary opacity-5 transition-all duration-300 group-hover:opacity-10 hidden md:block">∇</div>
              <div className="relative z-10 md:pt-12">
                <h3 className="font-serif text-3xl text-on-surface mb-6">Concept-First Logic</h3>
                <p className="font-mono text-sm text-outline leading-relaxed">Every solution starts with the &apos;Why&apos;. We identify the core physical or mathematical law before a single calculation is performed.</p>
              </div>
            </div>

            {/* Accuracy */}
            <div className="relative group p-8 rounded-2xl transition-all duration-300 hover:bg-white/5">
              <div className="ghost-symbol absolute -top-10 -left-6 text-[12rem] text-on-surface opacity-5 transition-all duration-300 group-hover:opacity-10 hidden md:block">Σ</div>
              <div className="relative z-10 md:pt-12">
                <h3 className="font-serif text-3xl text-on-surface mb-6">Exam-Tuned Precision</h3>
                <p className="font-mono text-sm text-outline leading-relaxed">Trained on thousands of past paper iterations. Accuracy isn&apos;t an aim; it&apos;s a computational constant verified by symbolic algebra.</p>
              </div>
            </div>
          </div>
        </section>

        {/* Solve Experience Widget */}
        <section className="px-6 md:px-12 py-32 bg-surface-container-low overflow-hidden">
          <div className="flex flex-col xl:flex-row gap-20">
            <div className="xl:w-1/3">
              <h2 className="font-serif text-4xl md:text-5xl text-on-surface mb-8 leading-tight">Deep Solving. <br /><span className="text-primary italic">No Shortcuts.</span></h2>
              <p className="font-mono text-sm text-outline mb-12">Upload a photo or type your problem. Equated decomposes the complexity into manageable logical units.</p>
              <div className="space-y-4 font-mono text-xs uppercase tracking-widest">
                <div className="flex items-center gap-4 text-primary">
                  <CheckCircle className="w-4 h-4" />
                  <span>Balancing Redox Reactions</span>
                </div>
                <div className="flex items-center gap-4 text-primary">
                  <CheckCircle className="w-4 h-4" />
                  <span>Projectile Motion Vectors</span>
                </div>
                <div className="flex items-center gap-4 text-primary">
                  <CheckCircle className="w-4 h-4" />
                  <span>Organic Synthesis Paths</span>
                </div>
              </div>
            </div>

            <div className="xl:w-2/3 glass-panel rounded-2xl p-px overflow-hidden violet-glow">
              <div className="bg-background/40 p-6 md:p-12 relative overflow-hidden h-full">
                <div className="absolute top-0 right-0 w-64 h-64 bg-primary/10 blur-[100px]"></div>

                <div className="mb-12 relative z-10">
                  <div className="text-[10px] font-mono text-primary mb-2 uppercase tracking-[0.3em] font-bold">[PROMPT_SOLVER]</div>
                  <div className="font-serif text-lg md:text-2xl text-on-surface border-b border-white/10 pb-4">
                    &quot;Balance the reaction: MnO₄⁻ + Fe²⁺ → Mn²⁺ + Fe³⁺ in acidic medium.&quot;
                  </div>
                </div>

                <div className="space-y-12 relative z-10">
                  <div>
                    <span className="font-mono text-secondary text-[10px] uppercase mb-4 block tracking-[0.2em] font-bold">ANALYSIS_REASONING</span>
                    <p className="font-mono text-sm text-on-surface/80 border-l-2 border-primary pl-4 md:pl-6 py-2">
                      The Permanganate ion is a strong oxidizing agent. We must split this into half-reactions for Fe (oxidation) and Mn (reduction).
                    </p>
                  </div>

                  <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                    <div className="bg-white/5 rounded-xl p-6 border border-white/5 hover:border-primary/30 transition-colors">
                      <span className="font-mono text-primary text-[10px] block mb-4 font-bold">OXIDATION HALF</span>
                      <span className="font-mono text-base md:text-lg text-on-surface break-words">Fe²⁺ → Fe³⁺ + e⁻</span>
                    </div>
                    <div className="bg-white/5 rounded-xl p-6 border border-white/5 hover:border-primary/30 transition-colors">
                      <span className="font-mono text-primary text-[10px] block mb-4 font-bold">REDUCTION HALF</span>
                      <span className="font-mono text-base md:text-lg text-on-surface break-words">MnO₄⁻ + 8H⁺ + 5e⁻ → Mn²⁺ + 4H₂O</span>
                    </div>
                  </div>

                  <div className="pt-8 border-t border-white/5 text-center">
                    <button className="font-mono text-primary text-[10px] md:text-xs uppercase tracking-[0.2em] md:tracking-[0.4em] hover:text-white transition-colors">
                      [EXPAND_COMPLETE_DERIVATION]
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* Pricing Section */}
        <section className="px-6 md:px-12 py-32 md:py-40">
          <div className="max-w-4xl mx-auto text-center mb-24">
            <h2 className="font-serif text-4xl md:text-5xl text-on-surface mb-6 italic">Less than a cup of chai <br className="hidden md:block" /> per week.</h2>
            <p className="font-mono text-[10px] md:text-xs text-outline uppercase tracking-[0.2em] md:tracking-[0.4em]">Uncompromised education shouldn&apos;t be a luxury.</p>
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-px bg-white/5 rounded-2xl overflow-hidden max-w-5xl mx-auto border border-white/5">
            {/* Free Tier */}
            <div className="bg-background p-8 md:p-12 hover:bg-surface-container transition-all duration-500 group">
              <span className="font-mono text-xs text-secondary uppercase tracking-[0.3em] mb-8 block font-bold">ENTRY_LEVEL</span>
              <h3 className="font-serif text-3xl md:text-4xl text-on-surface mb-2 italic">Theory Access</h3>
              <p className="font-mono text-xs text-outline mb-12 uppercase tracking-widest">5 SOLVES / DAY</p>

              <ul className="space-y-4 mb-16 font-mono text-xs text-outline group-hover:text-on-surface/70 transition-colors">
                <li className="flex items-center gap-2"><span className="text-primary">+</span> BASIC REASONING PATHS</li>
                <li className="flex items-center gap-2"><span className="text-primary">+</span> STANDARD ACCURACY MATRIX</li>
                <li className="flex items-center gap-2 opacity-40"><span className="text-primary">-</span> DELAYED SOLVE QUEUE</li>
              </ul>

              <div className="font-mono text-2xl text-on-surface mb-8">₹0 <span className="text-xs text-outline font-normal">/ FOREVER</span></div>
              <Link href="/auth/signup" className="flex items-center justify-center w-full glass-panel py-4 rounded-full font-mono text-xs uppercase tracking-widest hover:border-primary hover:text-primary transition-all duration-300">
                Initialize
              </Link>
            </div>

            {/* Paid Tier */}
            <div className="bg-background p-8 md:p-12 hover:bg-surface-container transition-all duration-500 relative overflow-hidden group">
              <div className="absolute -right-8 -top-8 text-8xl text-primary opacity-5 ghost-symbol group-hover:opacity-10 transition-opacity">λ</div>
              <span className="font-mono text-xs text-primary uppercase tracking-[0.3em] mb-8 block font-bold">UNLIMITED_ARCHIVE</span>
              <h3 className="font-serif text-3xl md:text-4xl text-on-surface mb-2 italic">Computational Elite</h3>
              <p className="font-mono text-xs text-outline mb-12 uppercase tracking-widest">UNLIMITED SOLVES</p>

              <ul className="space-y-4 mb-16 font-mono text-xs text-outline group-hover:text-on-surface/70 transition-colors">
                <li className="flex items-center gap-2"><span className="text-primary">+</span> DEEP DERIVATION ENGINES</li>
                <li className="flex items-center gap-2"><span className="text-primary">+</span> SYMPY_VERIFIED PROOFING</li>
                <li className="flex items-center gap-2"><span className="text-primary">+</span> PRIORITY SERVER CLUSTERS</li>
              </ul>

              <div className="font-mono text-2xl text-on-surface mb-8">₹49 <span className="text-xs text-outline font-normal">/ PACK</span></div>
              <Link href="/credits" className="flex items-center justify-center w-full bg-primary text-white py-4 rounded-full font-mono text-xs font-bold uppercase tracking-widest hover:scale-[1.02] transition-all duration-300 primary-glow-hover">
                Upgrade Terminal
              </Link>
            </div>
          </div>
        </section>
      </main>

      {/* Footer */}
      <footer className="bg-background border-t border-primary/20 flex flex-col lg:flex-row justify-between items-start lg:items-center w-full px-6 md:px-12 py-12 gap-8 mt-20 relative overflow-hidden">
        <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-transparent via-primary/40 to-transparent"></div>
        <div className="flex flex-col gap-3">
          <div className="text-lg font-bold text-primary font-serif tracking-tighter uppercase">EQUATED ARCHIVE</div>
          <div className="font-mono text-[10px] tracking-widest uppercase text-on-surface opacity-40">
            © 2024 EQUATED ARCHIVE. 28.6139° N, 77.2090° E
          </div>
        </div>

        <div className="flex flex-wrap gap-8 md:gap-12 w-full lg:w-auto">
          <Link className="font-mono text-[10px] tracking-widest uppercase text-on-surface opacity-40 hover:text-primary hover:opacity-100 transition-all" href="#">Protocol</Link>
          <Link className="font-mono text-[10px] tracking-widest uppercase text-on-surface opacity-40 hover:text-primary hover:opacity-100 transition-all" href="#">Terminal</Link>
          <Link className="font-mono text-[10px] tracking-widest uppercase text-on-surface opacity-40 hover:text-primary hover:opacity-100 transition-all" href="#">Contact</Link>
        </div>

        <div className="font-mono text-[10px] text-primary/60 border border-primary/20 px-4 py-2 rounded-full w-full lg:w-auto text-center">
          [ GRID_INDEX: 5.0.LL.1 ]
        </div>
      </footer>

      {/* Corner Coordinates Decoration */}
      <div className="fixed bottom-6 right-6 z-50 pointer-events-none hidden md:block mix-blend-screen">
        <div className="font-mono text-[8px] text-primary/30 transform rotate-90 origin-right space-y-4">
          <div>SYS_STABLE_V5.0</div>
          <div>LAT:28.6139 - LON:77.2090</div>
        </div>
      </div>
    </div>
  );
}

