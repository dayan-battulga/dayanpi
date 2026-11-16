import { Moon, Sun } from "lucide-react";
import { useTheme } from "@/hooks/useTheme";

export function ThemeToggle() {
  const { theme, toggleTheme } = useTheme();
  return (
    <button
      type="button"
      id="theme-toggle"
      className="icon-button"
      aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
      onClick={toggleTheme}
    >
      <Sun className="icon-sun" size={18} strokeWidth={1.8} aria-hidden="true" />
      <Moon className="icon-moon" size={18} strokeWidth={1.8} aria-hidden="true" />
    </button>
  );
}
