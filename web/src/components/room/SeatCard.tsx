import { Plus } from "lucide-react";
import { Link } from "react-router";
import { formatClock, formatDuration } from "@/lib/format";
import { SEAT_WORDS, describeSeatLine, findDoneShare, readInitial } from "@/lib/room";
import type { Seat } from "@/lib/types";

interface SeatCardProps {
  seat: Seat;
  mine: boolean;
  seconds: number | null; // the live time in their state; null while they're offline
}

// One person's seat (SeatsInfo.dc.html): the lamp in their state color, their initial until video comes, today's total,
// their name and timer, the current to-do and app, and the to-dos-done bar. Each detail only if they share it.
export function SeatCard({ seat, mine, seconds }: SeatCardProps) {
  const line = describeSeatLine(seat);
  const done = findDoneShare(seat);
  return (
    <article className="seat" data-state={seat.state} aria-label={`${seat.name}, ${mine ? "you" : SEAT_WORDS[seat.state]}`}>
      <span className="seat-initial" aria-hidden="true">
        {readInitial(seat.name)}
      </span>
      {seat.focus_seconds != null && (
        <span className="seat-chip">
          {formatDuration(seat.focus_seconds)}
          <span className="seat-chip-today"> today</span>
        </span>
      )}
      <div className="seat-foot">
        <div className="seat-row">
          <span className="seat-name">{mine ? "You" : seat.name}</span>
          <span className="seat-timer">{seconds == null ? "offline" : formatClock(seconds)}</span>
        </div>
        {(line.todo != null || line.app != null) && (
          <p className="seat-line">
            {line.todo}
            {line.app != null && <span className="seat-app">{`${line.todo != null ? " · " : ""}${line.app}`}</span>}
          </p>
        )}
      </div>
      {done != null && seat.todos != null && (
        <div className="seat-bar">
          <span className="sr-only">{`${seat.todos.done} of ${seat.todos.total} to-dos done`}</span>
          <span className="seat-bar-fill" style={{ width: `${done}%` }} aria-hidden="true" />
        </div>
      )}
    </article>
  );
}

// A seat nobody has yet. Only the owner can invite, so only the owner's says so.
export function EmptySeat({ owner }: { owner: boolean }) {
  return (
    <article className="seat seat-empty" aria-label="Open seat">
      {owner && (
        <Link className="seat-invite" to="/settings" state={{ section: "room" }}>
          <Plus strokeWidth={1.8} aria-hidden="true" />
          Invite
        </Link>
      )}
    </article>
  );
}

// Room's "just you" moment: nobody else has an account yet.
export function AloneSeat({ owner }: { owner: boolean }) {
  return (
    <article className="seat seat-empty seat-alone" aria-label="Nobody else here">
      <p className="seat-alone-title">Just you for now</p>
      {owner && (
        <Link className="button button-line" to="/settings" state={{ section: "room" }}>
          Invite someone
        </Link>
      )}
    </article>
  );
}
