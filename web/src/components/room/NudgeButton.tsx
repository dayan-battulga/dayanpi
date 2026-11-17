import { Bell } from "lucide-react";
import type { Nudger } from "@/hooks/useNudge";
import { isNudgeable } from "@/lib/room";
import type { Seat } from "@/lib/types";

interface NudgeButtonProps {
  seat: Seat;
  username: string | undefined; // yours: you can't nudge yourself
  nudger: Nudger;
  elapsed: number; // seconds since the snapshot the seat came in
  now: number;
  kind: "bell" | "text"; // the seat's round bell, or the peek's and their desk's "Nudge Sam"
}

// Nudge, on someone who's been on their phone 5+ minutes and takes nudges. While the 10 minutes since the last one run
// down it stays, greyed, and says how long is left.
export function NudgeButton({ seat, username, nudger, elapsed, now, kind }: NudgeButtonProps) {
  const mine = nudger.sent[seat.username];
  // The page's clock can be a tick behind the reply that set `at`.
  const wait = Math.max(0, (seat.nudge?.wait_s ?? 0) - elapsed, mine == null ? 0 : mine.wait_s - Math.max(0, now - mine.at));
  const minutes = Math.ceil(wait / 60);
  const waiting = wait > 0;
  const label = waiting ? `Nudge ${seat.name} again in ${minutes}m` : `Nudge ${seat.name}`;
  return (
    isNudgeable(seat, username) && (
      <button
        type="button"
        className={kind === "bell" ? "nudge-bell" : "nudge-button"}
        data-waiting={waiting ? "" : undefined}
        aria-label={kind === "bell" ? label : undefined}
        title={kind === "bell" ? label : undefined}
        disabled={waiting || nudger.sending === seat.username}
        onClick={() => void nudger.nudge(seat)}
      >
        <Bell size={kind === "bell" ? 18 : 16} strokeWidth={kind === "bell" ? 1.8 : 2} aria-hidden="true" />
        {kind === "text" && (waiting ? `Nudge again in ${minutes}m` : `Nudge ${seat.name}`)}
      </button>
    )
  );
}

// Room's nudge toast: the bell in the phone color, the words, and "just now" muted.
export function NudgeToast({ text, meta }: { text: string; meta: string | null }) {
  return (
    <span className="toast-nudge">
      <Bell size={16} strokeWidth={2} aria-hidden="true" />
      {text}
      {meta != null && <span className="toast-meta">{meta}</span>}
    </span>
  );
}
