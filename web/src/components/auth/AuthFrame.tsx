import { type ReactNode, useEffect } from "react";
import { ThemeToggle } from "@/components/shared/ThemeToggle";
import { Wordmark } from "@/components/shared/Wordmark";
import { showTabIcon } from "@/hooks/useTabIcon";

// The sign-in and join pages (Login.dc.html, Join.dc.html): a soft still glow at the top, the slim top bar with just
// the wordmark and the theme, and the form centered under it. The camera test borrows it with its own wider card.
export function AuthFrame({ wide = false, className, children }: { wide?: boolean; className?: string; children: ReactNode }) {
  // Signed out (or the camera test, which has no stream) there's no state to show: the gray tab icon and lamp.
  useEffect(() => showTabIcon(null), []);
  return (
    <div className="auth">
      <header className="topbar topbar-auth">
        <Wordmark state={null} className="wordmark" />
        <ThemeToggle />
      </header>
      <main className="auth-main">
        <div className={["auth-card", wide && "is-wide", className].filter(Boolean).join(" ")}>{children}</div>
      </main>
    </div>
  );
}
