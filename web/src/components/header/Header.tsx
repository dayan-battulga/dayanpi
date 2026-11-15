import { Moon, Sun } from "lucide-react";
import { riseDelay } from "@/components/shared/rise";
import type { Connection } from "@/lib/types";

const STATUS_LABELS: Record<Connection, string> = {
  connected: "Live",
  reconnecting: "Reconnecting",
  disconnected: "Offline",
};

interface HeaderProps {
  connection: Connection;
  undervoltage: boolean;
  theme: "light" | "dark";
  onToggleTheme: () => void;
}

export function Header({ connection, undervoltage, theme, onToggleTheme }: HeaderProps) {
  return (
    <header className="topbar rise" style={riseDelay(0)}>
      <div className="brand">
        <span className="wordmark">dayanpi</span>
        <span className="label">pi 5 · desk</span>
      </div>
      <nav className="sections" aria-label="Sections">
        <a href="#focus-card">Focus</a>
        <a href="#camera">Camera</a>
        <a href="#pi">Pi</a>
      </nav>
      <div className="topbar-end">
        <span id="power-alert" className="pill pill-hot" hidden={!undervoltage}>
          Undervoltage
        </span>
        <p id="status" className="pill" data-state={connection} aria-live="polite">
          <span className="status-dot" aria-hidden="true"></span>
          <span className="status-label">{STATUS_LABELS[connection]}</span>
        </p>
        <button
          type="button"
          id="theme-toggle"
          className="icon-button"
          aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          onClick={onToggleTheme}
        >
          <Sun className="icon-sun" size={18} strokeWidth={1.8} aria-hidden="true" />
          <Moon className="icon-moon" size={18} strokeWidth={1.8} aria-hidden="true" />
        </button>
      </div>
    </header>
  );
}
