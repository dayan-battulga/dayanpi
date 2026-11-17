import { X } from "lucide-react";
import { Dialog } from "radix-ui";
import { Fragment, useEffect, useState } from "react";
import { formatCompactMinutes, formatDayLabel } from "@/lib/calendar";
import { fetchJson } from "@/lib/http";
import { readDayPage, type DayPageParts, type NamedTime } from "@/lib/markdown";
import type { DayPageReply } from "@/lib/types";

const TODAY_REFRESH_S = 60;
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

function DayParts({ parts }: { parts: DayPageParts }) {
  return (
    <>
      <DayTotals totals={parts.totals} />
      {parts.notes.map((note) => (
        <p key={note} className="day-note">
          {note}
        </p>
      ))}
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
      {parts.apps.length > 0 && (
        <>
          <h3 className="day-label day-label-apps">Apps</h3>
          <p className="day-apps">
            {parts.apps.map((app, index) => (
              <Fragment key={app.name}>
                {index > 0 && <span className="day-dot"> · </span>}
                {`${app.name} ${app.time}`}
              </Fragment>
            ))}
          </p>
        </>
      )}
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
  const [page, setPage] = useState<{ day: string; markdown: string | null; others: DayPageReply["others"] } | null>(null);
  const refresh = isToday ? Math.floor(now / TODAY_REFRESH_S) : 0;

  useEffect(() => {
    let current = true;
    fetchJson<DayPageReply>(`/api/days/${day}`).then((reply) => {
      if (current) {
        setPage({ day, markdown: reply?.markdown ?? null, others: reply?.others });
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
          <DayParts parts={readDayPage(page.markdown)} />
        )}
        {/* The group calendar: everyone else who shares focus time and history, quietly. */}
        {page?.day === day && (page.others?.length ?? 0) > 0 && (
          <p className="day-others">Also focused: {page.others?.map((other) => `${other.name} ${formatCompactMinutes(other.focus_minutes)}`).join(" · ")}</p>
        )}
      </div>
    </>
  );
}
