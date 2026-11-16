import { AccountMenu } from "@/components/header/AccountMenu";
import { riseDelay } from "@/components/shared/rise";
import { ThemeToggle } from "@/components/shared/ThemeToggle";
import type { Connection, User } from "@/lib/types";

const STATUS_LABELS: Record<Connection, string> = {
  connected: "Live",
  reconnecting: "Reconnecting",
  disconnected: "Offline",
};

interface HeaderProps {
  connection: Connection;
  undervoltage: boolean;
  user: User | null;
  piShown: boolean;
}

export function Header({ connection, undervoltage, user, piShown }: HeaderProps) {
  return (
    <header className="topbar rise" style={riseDelay(0)}>
      <div className="brand">
        <span className="wordmark">dayanpi</span>
        <span className="label">pi 5 · desk</span>
      </div>
      <nav className="sections" aria-label="Sections">
        <a href="#focus-card">Focus</a>
        <a href="#camera">Camera</a>
        {piShown && <a href="#pi">Pi</a>}
      </nav>
      <div className="topbar-end flex-wrap justify-end">
        <span id="power-alert" className="pill pill-hot" hidden={!undervoltage}>
          Undervoltage
        </span>
        <p id="status" className="pill" data-state={connection} aria-live="polite">
          <span className="status-dot" aria-hidden="true"></span>
          <span className="status-label">{STATUS_LABELS[connection]}</span>
        </p>
        {user != null && <AccountMenu user={user} />}
        <ThemeToggle />
      </div>
    </header>
  );
}
