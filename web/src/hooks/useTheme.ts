import { useCallback, useEffect, useRef, useState } from "react";
import { readStored, writeStored } from "@/lib/storage";

type Theme = "light" | "dark";

const THEME_FADE_MS = 700;

export interface ThemeControl {
  theme: Theme;
  toggleTheme: () => void;
}

// index.html sets data-theme before the first paint; this keeps it, follows the device until
// you pick one, and fades the colors only while switching so live updates never pay for it.
export function useTheme(): ThemeControl {
  const [theme, setTheme] = useState<Theme>(() => (document.documentElement.dataset.theme === "dark" ? "dark" : "light"));
  const fadeTimer = useRef<number | undefined>(undefined);

  const applyTheme = useCallback((next: Theme) => {
    const root = document.documentElement;
    root.classList.add("theme-fade");
    window.clearTimeout(fadeTimer.current);
    fadeTimer.current = window.setTimeout(() => root.classList.remove("theme-fade"), THEME_FADE_MS);
    root.dataset.theme = next;
    setTheme(next);
  }, []);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const followDevice = (event: MediaQueryListEvent) => {
      if (readStored("theme", null) === null) {
        applyTheme(event.matches ? "dark" : "light");
      }
    };
    media.addEventListener("change", followDevice);
    return () => media.removeEventListener("change", followDevice);
  }, [applyTheme]);

  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    writeStored("theme", next);
    applyTheme(next);
  };
  return { theme, toggleTheme };
}
