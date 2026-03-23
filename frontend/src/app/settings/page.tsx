"use client";

import { useState, useEffect } from "react";
import { Sidebar } from "@/components/layout/Sidebar";
import { supabase } from "@/lib/supabase";

export default function SettingsPage() {
  const [name, setName] = useState("");
  const [eduLevel, setEduLevel] = useState("College");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    async function loadProfile() {
      const { data: { session } } = await supabase.auth.getSession();
      if (session?.user?.email) {
        setName(session.user.email.split("@")[0]);
      } else {
        setName("Equated User");
      }
    }
    loadProfile();
  }, []);

  const handleSave = (e: React.FormEvent) => {
    e.preventDefault();
    setSaved(true);
    setTimeout(() => setSaved(false), 3000);
  };

  return (
    <div className="flex h-[calc(100vh-4rem)]">
      <Sidebar />
      <div className="flex-1 flex flex-col items-center justify-center p-8 overflow-y-auto">
        <div className="w-full max-w-2xl bg-[var(--bg-card)] rounded-2xl border border-white/5 p-8 shadow-2xl">
          <h1 className="text-3xl font-bold mb-2">Settings</h1>
          <p className="text-[var(--text-secondary)] mb-8">Manage your personal preferences and academic profile.</p>

          <form onSubmit={handleSave} className="space-y-6">
            <div>
              <label className="block text-sm font-medium mb-2">Display Name</label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full px-4 py-3 rounded-xl bg-[var(--bg-secondary)] border border-white/5 focus:border-indigo-500 outline-none transition-colors"
                placeholder="Enter your name"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-2">Education Level</label>
              <select
                value={eduLevel}
                onChange={(e) => setEduLevel(e.target.value)}
                className="w-full px-4 py-3 rounded-xl bg-[var(--bg-secondary)] border border-white/5 focus:border-indigo-500 outline-none transition-colors"
              >
                <option value="Middle School">Middle School</option>
                <option value="High School">High School</option>
                <option value="College">College</option>
                <option value="Professional">Professional</option>
              </select>
            </div>

            <div className="pt-4 flex items-center justify-between border-t border-white/5">
              {saved ? (
                <span className="text-green-400 font-medium">✓ Settings saved successfully</span>
              ) : (
                <span className="text-sm opacity-50">Local changes apply instantly</span>
              )}
              <button
                 type="submit"
                 disabled={!name}
                 className="px-6 py-2 bg-indigo-600 hover:bg-indigo-500 rounded-xl font-semibold transition-colors disabled:opacity-50"
              >
                Save Changes
              </button>
            </div>
          </form>
        </div>
      </div>
    </div>
  );
}
