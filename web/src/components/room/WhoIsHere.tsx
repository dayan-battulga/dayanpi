import { PanelRightClose, PanelRightOpen } from "lucide-react";
import { Link } from "react-router";
import { formatClock, formatDuration } from "@/lib/format";
import { describeSeatLine, describeSeatState, describeTaskMeta, readInitial } from "@/lib/room";
import type { Seat } from "@/lib/types";

interface WhoIsHereProps {
  others: Seat[]; // everyone here but you, each only with what they share
  elapsed: number; // seconds since the snapshot they came in
}

const deskPath = (seat: Seat) => `/people/${encodeURIComponent(seat.username)}`;
const liveClock = (seat: Seat, elapsed: number) => (seat.seconds_in_state == null ? "" : formatClock(seat.seconds_in_state + elapsed));

// Their to-dos as dots, filled for done ones (SideRail), with the count for screen readers.
function DoneDots({ todos }: { todos: NonNullable<Seat["todos"]> }) {
  return (
    <span className="rail-dots">
      <span className="sr-only">{`${todos.done} of ${todos.total} to-dos done`}</span>
      {Array.from({ length: todos.total }, (_, index) => (
        <span key={index} className="rail-dot" data-done={index < todos.done ? "" : undefined} aria-hidden="true" />
      ))}
    </span>
  );
}

interface RoomRailProps extends WhoIsHereProps {
  together: number; // today's focus of everyone here who shares it
  collapsed: boolean;
  onCollapse: (collapsed: boolean) => void;
}

// Who's here, as the sidebar on Desk, Pi and Settings from 1280 px up (SideRail.dc.html). It folds to a column of faces
// and remembers that. Each person opens their desk.
export function RoomRail({ others, elapsed, together, collapsed, onCollapse }: RoomRailProps) {
  const rail = collapsed ? (
    <aside className="rail rail-collapsed" aria-label="The room">
      <button type="button" className="rail-toggle" aria-label="Show the room panel" onClick={() => onCollapse(false)}>
        <PanelRightOpen size={18} strokeWidth={1.8} aria-hidden="true" />
      </button>
      {others.map((seat) => (
        <Link key={seat.username} className="rail-face" data-state={seat.state} data-lamp={seat.lamp} to={deskPath(seat)} title={[seat.name, seat.todos?.current].filter(Boolean).join(" · ")} aria-label={`Open ${seat.name}’s desk`}>
          {readInitial(seat.name)}
        </Link>
      ))}
    </aside>
  ) : (
    <aside className="rail" aria-labelledby="rail-title">
      <div className="rail-head">
        <h2 id="rail-title" className="rail-title">
          In the room
        </h2>
        <button type="button" className="rail-toggle" aria-label="Hide the room panel" onClick={() => onCollapse(true)}>
          <PanelRightClose size={18} strokeWidth={1.8} aria-hidden="true" />
        </button>
      </div>
      {others.length > 0 ? (
        <ul className="rail-people">
          {others.map((seat) => {
            const meta = describeTaskMeta(seat);
            return (
              <li key={seat.username} className="rail-row">
                <Link className="rail-person" data-state={seat.state} data-lamp={seat.lamp} to={deskPath(seat)} aria-label={`Open ${seat.name}’s desk`}>
                  <div className="rail-top">
                    <span className="rail-thumb" aria-hidden="true">
                      {readInitial(seat.name)}
                    </span>
                    <div className="rail-who">
                      <p className="rail-name">{seat.name}</p>
                      <p className="rail-state">
                        {describeSeatState(seat.state)} · <span className="mono">{liveClock(seat, elapsed)}</span>
                      </p>
                    </div>
                  </div>
                  {seat.todos?.current != null && <p className="rail-task">{seat.todos.current}</p>}
                  {meta && <p className="rail-meta">{meta}</p>}
                  {((seat.todos?.total ?? 0) > 0 || seat.focus_seconds != null) && (
                    <div className="rail-foot">
                      {seat.todos != null && seat.todos.total > 0 ? <DoneDots todos={seat.todos} /> : <span />}
                      {seat.focus_seconds != null && <span className="rail-today">{formatDuration(seat.focus_seconds)} today</span>}
                    </div>
                  )}
                </Link>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="rail-empty">Nobody else is here right now.</p>
      )}
      <Link className="rail-room" to="/">
        <span>{formatDuration(together)} together today</span>
        <span>Open the room →</span>
      </Link>
    </aside>
  );
  return rail;
}

// Who's here, as a frosted bar along the bottom between a phone's width and the sidebar's (BottomBar.dc.html).
export function RoomBar({ others, elapsed }: WhoIsHereProps) {
  return (
    <nav className="room-bar" aria-label="The room">
      {others.map((seat) => {
        const task = seat.todos?.current ?? null;
        const app = describeSeatLine({ ...seat, site: null }).app;
        return (
          <Link key={seat.username} className="bar-person" data-state={seat.state} data-lamp={seat.lamp} to={deskPath(seat)} aria-label={`Open ${seat.name}’s desk`}>
            <span className="bar-face" aria-hidden="true">
              {readInitial(seat.name)}
            </span>
            <span className="bar-name">{seat.name}</span>
            <span className="bar-timer">{liveClock(seat, elapsed)}</span>
            {(task != null || app != null) && <span className="bar-rule" aria-hidden="true" />}
            {task != null && <span className="bar-task">{task}</span>}
            {app != null && <span className="bar-app">{task != null ? `· ${app}` : app}</span>}
          </Link>
        );
      })}
      <span className="bar-rule bar-rule-tall" aria-hidden="true" />
      <Link className="bar-room" to="/" aria-label="Open the room">
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <rect x="3" y="3" width="7" height="7" rx="2" />
          <rect x="14" y="3" width="7" height="7" rx="2" />
          <rect x="3" y="14" width="7" height="7" rx="2" />
          <rect x="14" y="14" width="7" height="7" rx="2" />
        </svg>
      </Link>
    </nav>
  );
}
