import { useEffect } from "react";

export type Theme = "light" | "dark" | "colorblind";

export const THEMES: readonly Theme[] = ["light", "dark", "colorblind"];

/**
 * A brand-new user (or one who's never set a preference) falls back to the
 * OS light/dark setting — never to the colorblind theme, which is always an
 * explicit opt-in.
 */
export function prefersDarkDefault(): Theme {
  if (typeof window === "undefined" || !window.matchMedia) return "light";
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/**
 * The theme to show for a user: their own stored preference if they have
 * one, otherwise the OS light/dark default — never colorblind, which is
 * always an explicit opt-in. Shared by App.tsx (applying the theme
 * app-wide) and ProfilePage.tsx (highlighting the active choice), so the
 * fallback rule only lives in one place.
 */
export function resolveTheme(preferredTheme: string | null): Theme {
  return (preferredTheme as Theme | null) ?? prefersDarkDefault();
}

/**
 * Applies `theme` to the document root. `theme` itself is owned by the
 * caller — sourced from resolveTheme() — so this hook is just the DOM effect.
 */
export function useAppliedTheme(theme: Theme) {
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme]);
}
