import type { ReactNode } from "react";
import { ThemeToggle } from "@/components/shared/ThemeToggle";

// The sign-in and join pages (Login.dc.html, Join.dc.html): a soft still glow at the top, the slim top bar with just
// the wordmark and the theme, and the form centered under it.
export function AuthFrame({ wide = false, children }: { wide?: boolean; children: ReactNode }) {
  return (
    <div className="auth">
      <header className="topbar topbar-auth">
        <span className="wordmark">dayanpi</span>
        <ThemeToggle />
      </header>
      <main className="auth-main">
        <div className={wide ? "auth-card is-wide" : "auth-card"}>{children}</div>
      </main>
    </div>
  );
}
