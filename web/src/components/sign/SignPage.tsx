import { StateTimer } from "@/components/focus/FocusNow";
import { Wordmark } from "@/components/shared/Wordmark";
import { useMe } from "@/hooks/useMe";
import { useNow } from "@/hooks/useNow";
import { useSnapshot } from "@/hooks/useSnapshot";
import { useTabIcon } from "@/hooks/useTabIcon";
import { useWakeLock } from "@/hooks/useWakeLock";
import { ROOM_SIZE } from "@/lib/account";
import { formatDuration } from "@/lib/format";
import { SEAT_WORDS, orderSeats, summarizeRoom } from "@/lib/room";
import { STATE_COPY } from "@/lib/timeline";
import type { FocusStatus } from "@/lib/types";

// The current to-do's words, or null without one.
function findCurrentTodo(focus: FocusStatus): string | null {
  const todos = focus.todos;
  const current = todos?.open.find((item) => item.id === todos.current)?.text ?? null;
  return current;
}

// /sign (Sign.dc.html): a full-screen desk sign for an old iPad propped on the desk. Your state, how long you've been in
// it and your current to-do, big, with the room's lamps along the bottom and the slow glow. It's outside the frame, so
// it opens its own stream and /api/me, and it keeps the screen awake while it's showing.
export function SignPage() {
  const { snapshot, connection, receivedAt } = useSnapshot();
  const { user } = useMe();
  const now = useNow();
  useWakeLock();
  const lamp = useTabIcon(snapshot?.focus?.state);
  const focus = snapshot?.focus;
  const seats = orderSeats(snapshot?.room?.seats ?? [], user?.username);
  const summary = summarizeRoom(seats);
  const state = focus?.state ?? "unknown";
  const todo = focus == null ? null : findCurrentTodo(focus);
  const open = Math.max(0, ROOM_SIZE - seats.length);
  return (
    <main className="sign" data-state={state} data-connection={connection}>
      <div className="sign-glow" aria-hidden="true" />
      <div className="sign-top">
        <Wordmark state={lamp} />
        {seats.length > 0 && <span>{`${formatDuration(summary.focusSeconds)} ${summary.here.length > 1 ? "together" : "today"}`}</span>}
      </div>
      <div className="sign-middle">
        {focus != null && (
          <div>
            <p className="sign-state">
              <span className="sign-dot" aria-hidden="true" />
              {STATE_COPY[state].label}
            </p>
            <StateTimer seconds={focus.seconds_in_state + Math.max(0, now - receivedAt)} className="sign-timer" />
            {todo != null && <p className="sign-todo">{todo}</p>}
          </div>
        )}
      </div>
      <ul className="sign-room" aria-label="The room">
        {seats.map((seat) => (
          <li key={seat.username} data-state={seat.state} data-mine={seat.username === user?.username ? "" : undefined}>
            <span className="sign-lamp" aria-hidden="true" />
            {seat.username === user?.username ? "You" : seat.name}
            <span className="sr-only">{`, ${SEAT_WORDS[seat.state]}`}</span>
          </li>
        ))}
        {Array.from({ length: open }, (_, index) => (
          <li key={`open-${index}`} data-state="open">
            <span className="sign-lamp" aria-hidden="true" />
            Open
          </li>
        ))}
      </ul>
    </main>
  );
}
