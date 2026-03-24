import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Equated — AI STEM Learning Assistant",
  description:
    "Solve STEM problems step-by-step with verified solutions, structured explanations, and multi-engine AI.",
  keywords: ["STEM", "AI tutor", "math solver", "physics", "step-by-step"],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <head>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/katex@0.16.9/dist/katex.min.css" />
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.9.0/build/styles/github-dark.min.css" />
      </head>
      <body className="antialiased font-body overflow-hidden">
        {/* Atmospheric Glows */}
        <div className="fixed top-[-10%] right-[-10%] w-[500px] h-[500px] bg-primary/5 blur-[120px] rounded-full pointer-events-none z-0"></div>
        <div className="fixed bottom-[-5%] left-[20%] w-[400px] h-[400px] bg-secondary/5 blur-[100px] rounded-full pointer-events-none z-0"></div>
        {children}
      </body>
    </html>
  );
}
