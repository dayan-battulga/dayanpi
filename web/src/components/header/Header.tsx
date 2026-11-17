import { m } from "motion/react";
import type { ReactNode } from "react";
import { NavLink } from "react-router";
import { AccountMenu } from "@/components/header/AccountMenu";
import { ThemeToggle } from "@/components/shared/ThemeToggle";
import { SPRINGS } from "@/lib/motion";
import type { Connection, User } from "@/lib/types";

interface HeaderProps {
  connection: Connection;
  user: User | null;
  phone: boolean;
}

interface PillLinkProps {
  to: string;
  kind: "tab" | "dock";
  label?: string;
  children: ReactNode;
}

// A page link; the active one carries the pill, which slides over when you pick another (the toggle spring).
export function PillLink({ to, kind, label, children }: PillLinkProps) {
  return (
    <NavLink to={to} className={kind === "tab" ? "tab" : "dock-item"} aria-label={label}>
      {({ isActive }) => (
        <>
          {isActive && <m.span layoutId={`${kind}-pill`} className={`${kind}-pill`} transition={SPRINGS.toggle} />}
          {children}
        </>
      )}
    </NavLink>
  );
}

// The top bar on every signed-in page: the wordmark, the pages (in the dock instead on a phone), the theme and you.
export function Header({ connection, user, phone }: HeaderProps) {
  return (
    <header className="topbar">
      <span className="brand">
        <span className="wordmark">dayanpi</span>
        {connection === "reconnecting" && (
          <span role="status" className="reconnecting">
            Reconnecting
          </span>
        )}
      </span>
      {!phone && (
        <nav className="tabs" aria-label="Pages">
          <PillLink to="/me" kind="tab">
            Desk
          </PillLink>
          {user?.role === "owner" && (
            <PillLink to="/pi" kind="tab">
              Pi
            </PillLink>
          )}
        </nav>
      )}
      <div className="topbar-end">
        <ThemeToggle />
        {user != null && <AccountMenu user={user} />}
      </div>
    </header>
  );
}
