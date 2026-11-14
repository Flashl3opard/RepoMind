import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { NavBar } from "@/components/nav-bar";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "RepoMind Dashboard",
  description: "Repos, Q&A, PR reviews, and benchmark results for RepoMind.",
};

// Dark by default. This inline script runs before paint (no `defer`/`async`) and
// only ever removes the `dark` class if the visitor previously chose light mode --
// it never adds JS-driven FOUC on first visit, since <html> already has `dark`
// below. Kept tiny and dependency-free on purpose (no next-themes).
const THEME_INIT_SCRIPT = `
try {
  if (localStorage.getItem("repomind-theme") === "light") {
    document.documentElement.classList.remove("dark");
  }
} catch (e) {}
`;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`dark ${geistSans.variable} ${geistMono.variable} h-full antialiased`}
      // The inline script below may remove "dark" before React hydrates (when the
      // visitor previously chose light mode) -- that's an intentional, expected
      // mismatch, not a bug.
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="min-h-full flex flex-col">
        <NavBar />
        <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col px-4 py-6">
          {children}
        </main>
      </body>
    </html>
  );
}
