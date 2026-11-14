"use client";

import { useEffect, useState } from "react";
import { Moon, Sun } from "lucide-react";

import { Button } from "@/components/ui/button";

const STORAGE_KEY = "repomind-theme";

export function ThemeToggle() {
  // Starts in sync with the SSR default (dark); corrected on mount to match
  // whatever the inline script in layout.tsx already applied to <html>.
  const [isDark, setIsDark] = useState(true);

  useEffect(() => {
    // Reconciles React state with the DOM class the blocking inline script in
    // layout.tsx already set before hydration (that script reads localStorage, not
    // this component, to avoid a hydration mismatch on this component's own first
    // render). Syncing with an external, non-React-owned source of truth (the DOM
    // class) after mount is exactly what this effect is for.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setIsDark(document.documentElement.classList.contains("dark"));
  }, []);

  function toggle() {
    const next = !isDark;
    setIsDark(next);
    document.documentElement.classList.toggle("dark", next);
    try {
      localStorage.setItem(STORAGE_KEY, next ? "dark" : "light");
    } catch {
      // localStorage unavailable (private mode, etc.) -- the toggle still works
      // for this page view, it just won't persist across visits.
    }
  }

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={toggle}
      aria-label="Toggle dark mode"
    >
      {isDark ? <Sun /> : <Moon />}
    </Button>
  );
}

export const THEME_STORAGE_KEY = STORAGE_KEY;
