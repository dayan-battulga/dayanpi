import { useEffect, useSyncExternalStore } from "react";
import { readStored, writeStored } from "@/lib/storage";

type Theme = "light" | "dark";

const THEME_FADE_MS = 700;

export interface ThemeControl {
  theme: Theme;
  toggleTheme: () => void;
}

// data-theme on <html> is the only copy, so the top bar's button and ⌘K's command never disagree.
const themeListeners = new Set<() => void>();
let fadeTimer: number | undefined;

function readTheme(): Theme {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}

function watchTheme(onChange: () => void): () => void {
  themeListeners.add(onChange);
  return () => themeListeners.delete(onChange);
}

// Fades the colors only while switching, so live updates never pay for it.
function applyTheme(next: Theme): void {
  const root = document.documentElement;
  root.classList.add("theme-fade");
  window.clearTimeout(fadeTimer);
  fadeTimer = window.setTimeout(() => root.classList.remove("theme-fade"), THEME_FADE_MS);
  root.dataset.theme = next;
  themeListeners.forEach((listener) => listener());
}

// index.html sets data-theme before the first paint; this keeps it, and follows the device until you pick one.
export function useTheme(): ThemeControl {
  const theme = useSyncExternalStore(watchTheme, readTheme);

  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const followDevice = (event: MediaQueryListEvent) => {
      if (readStored("theme", null) === null) {
        applyTheme(event.matches ? "dark" : "light");
      }
    };
    media.addEventListener("change", followDevice);
    return () => media.removeEventListener("change", followDevice);
  }, []);

  const toggleTheme = () => {
    const next = readTheme() === "dark" ? "light" : "dark";
    writeStored("theme", next);
    applyTheme(next);
  };
  return { theme, toggleTheme };
}
