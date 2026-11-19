import { m } from "motion/react";
import type { ReactNode } from "react";
import { Link, useLocation } from "react-router";
import { AccountMenu } from "@/components/header/AccountMenu";
import { ThemeToggle } from "@/components/shared/ThemeToggle";
import { Wordmark } from "@/components/shared/Wordmark";
import { SPRINGS } from "@/lib/motion";
import { readInitial } from "@/lib/room";
import type { Connection, FocusState, LampColor, Seat, User } from "@/lib/types";

interface HeaderProps {
  connection: Connection;
  lampState: FocusState | null; // the wordmark's lamp: the tab icon's state
  lampColor: LampColor; // and your lamp color, for focused
  user: User | null;
  phone: boolean;
  here?: Seat[] | null; // who's here, on the room's page only
  hereLabel?: string;
  onOpenPalette: () => void;
}

const PALETTE_KEY = /Mac|iPhone|iPad/.test(navigator.userAgent) ? "⌘K" : "Ctrl K";

interface PillLinkProps {
  to: string;
  kind: "tab" | "dock";
  label?: string;
  under?: string; // pages below this count too: someone's desk (/people/...) is part of the Room
  children: ReactNode;
}

// A page link; the active one carries the pill, which slides over when you pick another (the toggle spring).
export function PillLink({ to, kind, label, under, children }: PillLinkProps) {
  const { pathname } = useLocation();
  const active = pathname === to || (under != null && pathname.startsWith(under));
  return (
    <Link to={to} className={kind === "tab" ? "tab" : "dock-item"} aria-label={label} aria-current={active ? "page" : undefined}>
      {active && <m.span layoutId={`${kind}-pill`} className={`${kind}-pill`} transition={SPRINGS.toggle} />}
      {children}
    </Link>
  );
}

// The room's faces in the top bar (Room.dc.html): everyone here, ringed in their state color.
function HereFaces({ here, label }: { here: Seat[]; label: string }) {
  return (
    <div className="here-faces">
      {here.map((seat) => (
        <span key={seat.username} className="here-face" data-state={seat.state} data-lamp={seat.lamp} aria-hidden="true">
          {readInitial(seat.name)}
        </span>
      ))}
      <span className="sr-only">{label}</span>
    </div>
  );
}

// The top bar on every signed-in page: the wordmark, the pages (in the dock instead on a phone), who's here on the
// room's page, ⌘K (neither on a phone, like RoomPhone), the theme and you.
export function Header({ connection, lampState, lampColor, user, phone, here, hereLabel, onOpenPalette }: HeaderProps) {
  return (
    <header className="topbar">
      <span className="brand">
        <Wordmark state={lampState} lamp={lampColor} className="wordmark" />
        {connection === "reconnecting" && (
          <span role="status" className="reconnecting">
            Reconnecting
          </span>
        )}
      </span>
      {!phone && (
        <nav className="tabs" aria-label="Pages">
          <PillLink to="/" kind="tab" under="/people/">
            Room
          </PillLink>
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
        {!phone && here != null && here.length > 0 && <HereFaces here={here} label={hereLabel ?? ""} />}
        {!phone && (
          <button type="button" className="command-button" aria-label="Search and commands" aria-keyshortcuts="Meta+K Control+K" onClick={onOpenPalette}>
            {PALETTE_KEY}
          </button>
        )}
        <ThemeToggle />
        {user != null && <AccountMenu user={user} />}
      </div>
    </header>
  );
}
