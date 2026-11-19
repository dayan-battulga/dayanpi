import { ChevronLeft } from "lucide-react";
import { AnimatePresence, m } from "motion/react";
import type { ReactNode } from "react";
import { Link, Navigate, useParams } from "react-router";
import { useFrame } from "@/components/frame/Frame";
import { AppBars, DayBar, TheirTodoList, describeDone } from "@/components/people/TheirPieces";
import { NudgeButton } from "@/components/room/NudgeButton";
import { SeatPicture } from "@/components/room/SeatPicture";
import { useNudge } from "@/hooks/useNudge";
import { useTheirDesk } from "@/hooks/useTheirDesk";
import { WEEKDAYS, buildMonthWeeks, formatCompactMinutes, formatDayKey, formatMonthLabel, readShade } from "@/lib/calendar";
import { formatClock, formatDuration, formatShortDate, formatTimeOfDay } from "@/lib/format";
import { SPRINGS } from "@/lib/motion";
import { describeSeatState, describeShares, readInitial } from "@/lib/room";
import type { Seat, TheirDesk } from "@/lib/types";

const APPS_SHOWN = 5;
const PIECE_SHOWN = { opacity: 1, transition: SPRINGS.enter };
const PIECE_GONE = { opacity: 0, transition: SPRINGS.exit };

const isYoutube = (site: string) => site === "youtube.com" || site.endsWith(".youtube.com");

// One card of their desk. It fades in or out when they share or stop sharing it, and the rest slide into the space.
function Piece({ name, className, children }: { name: string; className: string; children: ReactNode }) {
  return (
    <m.section aria-label={name} className={`their-piece ${className}`} layout transition={{ layout: SPRINGS.layout }} initial={{ opacity: 0 }} animate={PIECE_SHOWN} exit={PIECE_GONE}>
      {children}
    </m.section>
  );
}

function HistoryPiece({ desk, history }: { desk: TheirDesk; history: NonNullable<TheirDesk["history"]> }) {
  const joined = formatDayKey(new Date(history.joined_at * 1000));
  return (
    <Piece name={`${desk.name}’s history`} className="their-history">
      <div className="their-piece-head">
        <h2 className="their-piece-title">{formatMonthLabel(history.month, history.today.slice(0, 7))}</h2>
        <span className="their-piece-meta">
          {formatDuration(history.total_minutes * 60)} focused since joining {formatShortDate(history.joined_at)}
        </span>
      </div>
      <div className="their-weekdays" aria-hidden="true">
        {WEEKDAYS.map((weekday) => (
          <span key={weekday}>{weekday}</span>
        ))}
      </div>
      {buildMonthWeeks(history.month).map((week) => (
        <div key={week[0].day} className="their-week">
          {week.map((cell) => {
            const minutes = cell.inMonth ? (history.days[cell.day] ?? 0) : 0;
            const quiet = cell.inMonth && (cell.day < joined || cell.day > history.today);
            return (
              <span
                key={cell.day}
                className="their-day"
                data-out={cell.inMonth ? undefined : ""}
                data-quiet={quiet ? "" : undefined}
                data-today={cell.day === history.today ? "" : undefined}
                data-shade={quiet || !cell.inMonth ? undefined : readShade(minutes)}
              >
                <span>{cell.date}</span>
                {minutes > 0 && <span className="their-day-minutes">{formatCompactMinutes(minutes)}</span>}
              </span>
            );
          })}
        </div>
      ))}
    </Piece>
  );
}

// Each piece they share, in TheirDesk's order; the ones they don't simply aren't there and the rest fill the row.
function Pieces({ desk, now }: { desk: TheirDesk; now: number }) {
  const shared = desk.today != null || desk.todo_list != null || desk.apps != null || desk.sites != null || desk.history != null;
  return (
    <AnimatePresence mode="popLayout" initial={false}>
      {desk.today != null && (
        <Piece key="today" name={`${desk.name}’s day`} className="their-today">
          <div className="their-piece-head">
            <h2 className="their-piece-title">Today</h2>
            <p className="their-piece-meta">
              <span className="their-num">{formatDuration(desk.focus_seconds ?? desk.today.working_seconds)}</span> focused ·{" "}
              <span className="their-num">{formatDuration(desk.today.phone_seconds)}</span> on the phone · <span className="their-num">{desk.today.pickups}</span>{" "}
              {desk.today.pickups === 1 ? "pickup" : "pickups"}
            </p>
          </div>
          <div className="their-today-bar">
            <DayBar segments={desk.today.segments} now={now} />
          </div>
        </Piece>
      )}
      {desk.todo_list != null && (
        <Piece key="todos" name={`${desk.name}’s to-dos`} className="their-card">
          <div className="their-piece-head">
            <h2 className="their-piece-title">To-do</h2>
            <span className="their-piece-meta">{describeDone(desk.todo_list)}</span>
          </div>
          <TheirTodoList todos={desk.todo_list} />
        </Piece>
      )}
      {desk.apps != null && (
        <Piece key="apps" name={`${desk.name}’s apps`} className="their-card their-apps">
          <h2 className="their-piece-title">Apps</h2>
          {desk.apps.length > 0 ? <AppBars desk={desk} limit={APPS_SHOWN} /> : <p className="their-piece-meta their-empty">Nothing from the Mac today.</p>}
        </Piece>
      )}
      {desk.sites != null && (
        <Piece key="sites" name={`${desk.name}’s sites`} className="their-card">
          <h2 className="their-piece-title">Sites</h2>
          <ul className="their-sites">
            {desk.sites.map((row) => (
              <li key={row.site} className="their-site">
                <span data-hot={isYoutube(row.site) ? "" : undefined}>{row.site}</span>
                <span className="their-todo-time">{formatDuration(row.seconds)}</span>
              </li>
            ))}
          </ul>
        </Piece>
      )}
      {desk.history != null && <HistoryPiece key="history" desk={desk} history={desk.history} />}
      {!shared && (
        <m.p key="nothing" className="their-nothing" layout initial={{ opacity: 0 }} animate={PIECE_SHOWN} exit={PIECE_GONE}>
          {desk.name} keeps the rest private.
        </m.p>
      )}
    </AnimatePresence>
  );
}

// At /people/<username> (TheirDesk.dc.html): someone's desk, read-only, built from what they share. The state and timer
// are live off the room stream; the pieces come from /api/people/<username>, asked again when what they share changes.
export function TheirDeskPage() {
  const username = useParams().username ?? "";
  const { snapshot, user, now, receivedAt } = useFrame();
  const live = snapshot?.room?.seats.find((entry) => entry.username === username);
  // Not until /api/me says who you are: your own name goes to /me instead.
  const { desk, missing } = useTheirDesk(user == null || user.username === username ? null : username, live?.shares.join() ?? "", now);
  const nudger = useNudge();
  const elapsed = Math.max(0, now - receivedAt);
  const seat: Seat | null = live ?? desk;
  const seconds = seat?.seconds_in_state == null ? null : seat.seconds_in_state + elapsed;

  const back = (
    <Link className="their-back" to="/">
      <ChevronLeft size={16} strokeWidth={1.8} aria-hidden="true" />
      Room
    </Link>
  );
  let page: ReactNode = null;
  if (user != null && user.username === username) {
    page = <Navigate to="/me" replace />;
  } else if (missing) {
    page = (
      <div className="their-desk">
        <div className="their-top">{back}</div>
        <p className="their-nothing">Nobody here goes by that name.</p>
      </div>
    );
  } else if (seat != null && desk != null) {
    page = (
      <div className="their-desk live" data-state={seat.state} data-lamp={seat.lamp}>
        <div className="their-top">
          {back}
          <p className="their-shares">{describeShares(seat)}</p>
        </div>
        <div className="their-head">
          <section aria-labelledby="their-state" className="their-now">
            <div className="their-who">
              <span className="their-face" aria-hidden="true">
                {readInitial(seat.name)}
              </span>
              <div>
                <p className="their-name">{seat.name}’s desk</p>
                {seat.here && desk.here_since != null && <p className="their-since">here since {formatTimeOfDay(desk.here_since)}</p>}
              </div>
            </div>
            <div className="their-state-row">
              <h1 id="their-state" className="their-state">
                {describeSeatState(seat.state)}
              </h1>
              {seconds != null && (
                <p className="their-timer" role="timer" aria-label={formatClock(seconds)}>
                  {formatClock(seconds)}
                </p>
              )}
            </div>
            {seat.todos?.current != null && (
              <p className="their-working">
                Working on <span className="their-num">{seat.todos.current}</span>
                {seat.state !== "working" && " · paused"}
              </p>
            )}
            <div className="their-nudge">
              <NudgeButton seat={seat} username={user?.username} nudger={nudger} elapsed={elapsed} now={now} kind="text" />
            </div>
          </section>
          <AnimatePresence initial={false}>
            {desk.video != null && (
              <m.section key="video" aria-label={`${seat.name}’s camera`} className="their-video" layout initial={{ opacity: 0 }} animate={PIECE_SHOWN} exit={PIECE_GONE}>
                {/* Their once-a-second picture, or their initial while there's none (away, or nothing fresh). */}
                <div className="their-video-tile">
                  <span className="seat-initial" aria-hidden="true">
                    {readInitial(seat.name)}
                  </span>
                  {seat.picture != null && <SeatPicture username={seat.username} at={seat.picture.at} />}
                </div>
              </m.section>
            )}
          </AnimatePresence>
        </div>
        <div className="their-pieces">
          <Pieces desk={{ ...desk, ...seat }} now={now} />
        </div>
      </div>
    );
  }
  return page;
}
