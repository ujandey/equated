"use client";

import { useChatStore } from "@/store/chatStore";
import { ImagePlus, Settings, ArrowRight } from "lucide-react";

export function Header() {
  return (
    <header className="fixed left-0 md:left-[180px] top-0 right-0 h-16 flex justify-between items-center px-4 md:px-8 z-30 bg-background/20 backdrop-blur-sm border-b border-border-glass transition-all duration-300">
      <div className="flex gap-8 items-center pl-12 md:pl-0">
        <nav className="hidden md:flex gap-6 font-headline text-lg tracking-wide">
          <a className="text-primary border-b border-primary" href="#">Formulae</a>
          <a className="text-slate-500 hover:text-primary transition-all duration-300" href="#">Concepts</a>
          <a className="text-slate-500 hover:text-primary transition-all duration-300" href="#">Mistake Alerts</a>
        </nav>
      </div>
      
      <div className="flex items-center gap-4">
        <div className="relative group hidden sm:block">
          <input 
            className="bg-surface-glass border border-border-glass rounded-full px-6 py-1.5 text-sm w-48 md:w-64 focus:ring-1 focus:ring-primary focus:border-primary transition-all placeholder:text-slate-600 outline-none text-on-surface" 
            placeholder="Search knowledge base..." 
            type="text"
          />
        </div>
        <div className="flex gap-4 text-slate-400 items-center">
          <button className="hover:text-primary transition-colors">
            <ImagePlus className="w-5 h-5" />
          </button>
          <button className="hover:text-primary transition-colors">
            <Settings className="w-5 h-5" />
          </button>
          <button className="text-primary font-bold hover:translate-x-1 transition-transform">
            <ArrowRight className="w-5 h-5" />
          </button>
        </div>
      </div>
    </header>
  );
}
