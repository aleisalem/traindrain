import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark" | "colorblind";

const THEMES: readonly Theme[] = ["light", "dark", "colorblind"];

function prefersDarkDefault(): Theme {
  if (typeof window === "undefined" || !window.matchMedia) return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/**
 * Session-only theme selection for the scaffold placeholder page.
 * Server-side persistence of the user's preference lands in a later ticket;
 * until then, a fresh load falls back to the OS light/dark preference —
 * never colorblind, which is always an explicit opt-in.
 */
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(prefersDarkDefault);

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);

  const cycleTheme = useCallback(() => {
    setTheme((current) => THEMES[(THEMES.indexOf(current) + 1) % THEMES.length]);
  }, []);

  return { theme, setTheme, cycleTheme, themes: THEMES };
}
