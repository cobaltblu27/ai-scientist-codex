import { useCallback, useEffect, useState } from "react";

export type Theme = "light" | "dark";

const KEY = "ai-scientist.theme";

function stored(): Theme | null {
  try {
    const v = localStorage.getItem(KEY);
    return v === "dark" || v === "light" ? v : null;
  } catch {
    return null;
  }
}

function systemTheme(): Theme {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Applies the theme to <html data-theme> so plain CSS can key off it. */
function apply(theme: Theme) {
  document.documentElement.dataset.theme = theme;
}

/** Runs once at startup, before React renders, to avoid a light flash. */
export function initTheme(): Theme {
  const t = stored() ?? systemTheme();
  apply(t);
  return t;
}

export function useTheme(): [Theme, () => void] {
  const [theme, setTheme] = useState<Theme>(() => (document.documentElement.dataset.theme as Theme) || initTheme());

  useEffect(() => {
    apply(theme);
  }, [theme]);

  // Follow the OS setting until the user picks one explicitly.
  useEffect(() => {
    if (stored()) return;
    const mq = window.matchMedia?.("(prefers-color-scheme: dark)");
    if (!mq) return;
    const onChange = (e: MediaQueryListEvent) => setTheme(e.matches ? "dark" : "light");
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((t) => {
      const next: Theme = t === "dark" ? "light" : "dark";
      try {
        localStorage.setItem(KEY, next);
      } catch {
        /* private mode etc. */
      }
      return next;
    });
  }, []);

  return [theme, toggle];
}
