import { X } from "lucide-react";
import { AnimatePresence, m } from "motion/react";
import { Dialog } from "radix-ui";
import { Fragment, useEffect, useState } from "react";
import { toPercent } from "@/components/apps/AppsCard";
import { GoalRing, formatGoalProgress } from "@/components/shared/GoalRing";
import { formatDayLabel } from "@/lib/calendar";
import { formatDuration } from "@/lib/format";
import { fetchJson } from "@/lib/http";
import { readDayPage, type AppTime, type DayGoal, type DayPageParts, type NamedTime } from "@/lib/markdown";
import { SPRINGS } from "@/lib/motion";
import { readInitial } from "@/lib/room";
import type { DayPageReply, StudiedWith } from "@/lib/types";

const TODAY_REFRESH_S = 60;
const TOP_APPS = 5; // the rest fold into "+N more"
const APP_MIN_S = 60; // apps under a minute are left out
const ROW_HIDDEN = { opacity: 0 };
const ROW_SHOWN = { opacity: 1 };
const TOTALS = [
  { name: "Focus", label: "focused" },
  { name: "Phone", label: "phone" },
  { name: "Away", label: "away" },
];

function DayTotals({ totals }: { totals: NamedTime[] }) {
  const shown = TOTALS.map((total) => ({ ...total, time: totals.find((entry) => entry.name === total.name)?.time })).filter((total) => total.time != null);
  return (
    shown.length > 0 && (
      <p className="day-totals">
        {shown.map((total, index) => (
          <Fragment key={total.name}>
            {index > 0 && " · "}
            <span>{total.time}</span> {total.label}
          </Fragment>
        ))}
      </p>
    )
  );
}

// DayPopup's goal box: the ring, then "Goal reached" or how far along it got.
function DayGoalBox({ goal }: { goal: DayGoal }) {
  const progress = formatGoalProgress(goal.focusMinutes * 60, goal.minutes);
  const reached = goal.focusMinutes >= goal.minutes;
  return (
    <div className="day-goal">
      <GoalRing seconds={goal.focusMinutes * 60} goalMinutes={goal.minutes} size="large" />
      <div>
        <p className="day-goal-title">{reached ? "Goal reached" : progress}</p>
        <p className="day-goal-sub">{reached ? progress : `${formatDuration((goal.minutes - goal.focusMinutes) * 60)} to go`}</p>
      </div>
    </div>
  );
}

// Everyone you were focused at the same time as, each in a ring of their lamp color, with the minutes you overlapped.
function DayStudiedWith({ people }: { people: StudiedWith[] }) {
  return (
    people.length > 0 && (
      <>
        <h3 className="day-label">Studied with</h3>
        <ul className="day-mates">
          {people.map((person) => (
            <li key={person.username} data-lamp={person.lamp}>
              <span className="day-mate-face" aria-hidden="true">
                {readInitial(person.name)}
              </span>
              {person.name} <span className="day-time">{formatDuration(person.minutes * 60)}</span>
            </li>
          ))}
        </ul>
      </>
    )
  );
}

// One row per app like Done above it, each with its share of the top app as a thin bar, a browser's YouTube part first.
// The top five show; the rest open in place under them.
function DayApps({ apps }: { apps: AppTime[] }) {
  const [open, setOpen] = useState(false);
  const counted = apps.filter((app) => app.seconds >= APP_MIN_S);
  const longest = Math.max(0, ...counted.map((app) => app.seconds));
  const shown = open ? counted : counted.slice(0, TOP_APPS);
  return (
    counted.length > 0 && (
      <>
        <h3 className="day-label day-label-apps">Apps</h3>
        <ul className="day-apps">
          <AnimatePresence mode="popLayout" initial={false}>
            {shown.map((app) => (
              <m.li key={app.name} layout="position" initial={ROW_HIDDEN} animate={ROW_SHOWN} exit={ROW_HIDDEN} transition={SPRINGS.layout}>
                <div className="app-line">
                  <span className="app-name">{app.name}</span>
                  <span className="app-time">{app.time}</span>
                </div>
                <div className="app-track" aria-hidden="true">
                  <span className="app-bar" style={{ width: toPercent(app.seconds, longest) }}>
                    {app.youtubeSeconds > 0 && <span className="app-bar-youtube" style={{ width: toPercent(app.youtubeSeconds, app.seconds) }} />}
                  </span>
                </div>
              </m.li>
            ))}
          </AnimatePresence>
        </ul>
        {counted.length > TOP_APPS && (
          <m.button type="button" layout="position" transition={SPRINGS.layout} className="day-more" aria-expanded={open} onClick={() => setOpen(!open)}>
            {open ? "Show less" : `+${counted.length - TOP_APPS} more`}
          </m.button>
        )}
      </>
    )
  );
}

function DayParts({ parts, studiedWith }: { parts: DayPageParts; studiedWith: StudiedWith[] }) {
  return (
    <>
      <DayTotals totals={parts.totals} />
      {parts.notes.map((note) => (
        <p key={note} className="day-note">
          {note}
        </p>
      ))}
      {parts.goal != null && <DayGoalBox goal={parts.goal} />}
      <DayStudiedWith people={studiedWith} />
      {parts.todos.length > 0 && (
        <>
          <h3 className="day-label">Done</h3>
          <ul className="day-todos">
            {parts.todos.map((todo, index) => (
              <li key={index}>
                <span>{todo.name}</span>
                <span className="day-time">{todo.time}</span>
              </li>
            ))}
          </ul>
        </>
      )}
      <DayApps apps={parts.apps} />
    </>
  );
}

interface DayPageProps {
  day: string; // YYYY-MM-DD
  isToday: boolean; // built live, so it refreshes every minute
  now: number;
}

// What goes in the day dialog: the day's page from /api/days/<day>, laid out like the mockup's.
export function DayPage({ day, isToday, now }: DayPageProps) {
  const [page, setPage] = useState<{ day: string; markdown: string | null; studiedWith: StudiedWith[] } | null>(null);
  const refresh = isToday ? Math.floor(now / TODAY_REFRESH_S) : 0;

  useEffect(() => {
    let current = true;
    fetchJson<DayPageReply>(`/api/days/${day}`).then((reply) => {
      if (current) {
        setPage({ day, markdown: reply?.markdown ?? null, studiedWith: reply?.studied_with ?? [] });
      }
    });
    return () => {
      current = false;
    };
  }, [day, refresh]);

  return (
    <>
      <div className="day-head">
        <Dialog.Title className="day-title">{formatDayLabel(day, { weekday: "long", month: "long", day: "numeric" })}</Dialog.Title>
        <Dialog.Close className="day-close" aria-label="Close">
          <X size={18} strokeWidth={1.8} aria-hidden="true" />
        </Dialog.Close>
      </div>
      <div aria-live="polite">
        {page?.day !== day ? (
          <p className="day-note">Loading…</p>
        ) : page.markdown == null ? (
          <p className="day-note">No page for this day.</p>
        ) : (
          <DayParts parts={readDayPage(page.markdown)} studiedWith={page.studiedWith} />
        )}
      </div>
    </>
  );
}
