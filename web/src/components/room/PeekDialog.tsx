import { X } from "lucide-react";
import { Dialog } from "radix-ui";
import { Link } from "react-router";
import { AppBars, DayBar, TheirTodoList, describeDone } from "@/components/people/TheirPieces";
import { NudgeButton } from "@/components/room/NudgeButton";
import { PopDialog } from "@/components/ui/dialog";
import type { Nudger } from "@/hooks/useNudge";
import { useTheirDesk } from "@/hooks/useTheirDesk";
import { formatClock, formatDuration } from "@/lib/format";
import { describeSeatState, describeTaskMeta, isNudgeable, readInitial } from "@/lib/room";
import type { Seat } from "@/lib/types";

const PEEK_APPS = 3;

interface PeekDialogProps {
  seat: Seat | null; // who's being peeked at, live from the room; null when closed
  username: string | undefined;
  nudger: Nudger;
  now: number;
  elapsed: number;
  onClose: () => void;
}

// What the footer says when there's no Nudge: "Away for 12 minutes".
function describeFor(seat: Seat, elapsed: number): string {
  const minutes = Math.max(1, Math.floor(((seat.seconds_in_state ?? 0) + elapsed) / 60));
  return seat.seconds_in_state == null ? describeSeatState(seat.state) : `${describeSeatState(seat.state)} for ${minutes} minute${minutes === 1 ? "" : "s"}`;
}

// The quick peek when you tap someone's seat (PersonPanel.dc.html): what they're on, their day, to-dos and apps, each only
// if they share it, Nudge, and the way to their whole desk.
function PeekCard({ seat, username, nudger, now, elapsed }: Omit<PeekDialogProps, "onClose"> & { seat: Seat }) {
  const { desk } = useTheirDesk(seat.username, seat.shares.join(), now);
  const seconds = seat.seconds_in_state == null ? null : seat.seconds_in_state + elapsed;
  const meta = describeTaskMeta(seat);
  return (
    <>
      <div className="peek-head">
        <span className="peek-face" aria-hidden="true">
          {readInitial(seat.name)}
        </span>
        <div className="peek-who">
          <Dialog.Title className="peek-name">{seat.name}</Dialog.Title>
          <p className="peek-state">
            {describeSeatState(seat.state)}
            {seconds != null && (
              <>
                {" · "}
                <span className="mono">{formatClock(seconds)}</span>
              </>
            )}
          </p>
        </div>
        <Dialog.Close className="day-close" aria-label="Close">
          <X size={18} strokeWidth={1.8} aria-hidden="true" />
        </Dialog.Close>
      </div>
      {seat.todos?.current != null && (
        <>
          <p className="peek-label">Working on</p>
          <p className="peek-task">{seat.todos.current}</p>
          {meta && <p className="peek-meta">{meta}</p>}
        </>
      )}
      {desk?.today != null && (
        <div className="peek-day">
          <DayBar segments={desk.today.segments} now={now} middle={`${formatDuration(seat.focus_seconds ?? desk.today.working_seconds)} focused`} />
        </div>
      )}
      {(desk?.todo_list != null || (desk?.apps?.length ?? 0) > 0) && (
        <div className="peek-columns">
          {desk?.todo_list != null && (
            <div className="peek-todos">
              <p className="peek-label">To-do · {describeDone(desk.todo_list)}</p>
              <TheirTodoList todos={desk.todo_list} />
            </div>
          )}
          {desk != null && (desk.apps?.length ?? 0) > 0 && (
            <div className="peek-apps">
              <p className="peek-label">Apps today</p>
              <AppBars desk={desk} limit={PEEK_APPS} />
            </div>
          )}
        </div>
      )}
      <div className="peek-foot">
        <Link className="peek-open" to={`/people/${encodeURIComponent(seat.username)}`}>
          Open {seat.name}’s desk →
        </Link>
        {isNudgeable(seat, username) ? <NudgeButton seat={seat} username={username} nudger={nudger} elapsed={elapsed} now={now} kind="text" /> : <p className="peek-meta">{describeFor(seat, elapsed)}</p>}
      </div>
    </>
  );
}

export function PeekDialog({ seat, onClose, ...rest }: PeekDialogProps) {
  return (
    <PopDialog open={seat != null} onOpenChange={(open) => !open && onClose()} className="peek">
      {seat != null && (
        <div className="peek-inner" data-state={seat.state}>
          <PeekCard seat={seat} {...rest} />
        </div>
      )}
    </PopDialog>
  );
}
