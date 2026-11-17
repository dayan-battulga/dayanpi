import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { DayPage } from "@/components/calendar/DayPage";
import { riseDelay } from "@/components/shared/rise";
import { PopDialog } from "@/components/ui/dialog";
import { WEEKDAYS, buildMonthWeeks, formatCompactMinutes, formatDayKey, formatDayLabel, formatMonthLabel, readShade, shiftMonth } from "@/lib/calendar";
import { fetchJson } from "@/lib/http";
import type { MonthDays } from "@/lib/types";

const MONTH_REFRESH_S = 300; // also how soon yesterday's page shows up after midnight

interface CalendarCardProps {
  todayFocusSeconds: number | undefined;
  now: number;
}

export function CalendarCard({ todayFocusSeconds, now }: CalendarCardProps) {
  const today = formatDayKey(new Date(now * 1000));
  const thisMonth = today.slice(0, 7);
  const [month, setMonth] = useState(thisMonth);
  const [monthDays, setMonthDays] = useState<MonthDays | null>(null);
  const [picked, setPicked] = useState<string | null>(null);
  const opener = useRef<HTMLButtonElement | null>(null);
  const monthRefresh = Math.floor(now / MONTH_REFRESH_S);

  useEffect(() => {
    let current = true;
    fetchJson<MonthDays>(`/api/days?month=${month}`).then((reply) => {
      if (current && reply?.days != null) {
        setMonthDays(reply);
      }
    });
    return () => {
      current = false;
    };
  }, [month, monthRefresh]);

  const shownDays = monthDays?.month === month ? monthDays.days : {};
  // Today's number comes from the live stream; the rest from the pages.
  const readMinutes = (day: string) => (day === today && todayFocusSeconds != null ? Math.round(todayFocusSeconds / 60) : (shownDays[day]?.focus_minutes ?? 0));
  const weeks = buildMonthWeeks(month);
  const monthMinutes = weeks.flat().reduce((sum, cell) => sum + (cell.inMonth ? readMinutes(cell.day) : 0), 0);
  // No Dialog.Trigger for 31 buttons, so the focus goes back to the day by hand.
  const returnFocus = (event: Event) => {
    event.preventDefault();
    opener.current?.focus();
  };

  return (
    <section className="calendar rise" style={riseDelay(4)} aria-labelledby="calendar-title">
      <div className="calendar-head">
        <div className="calendar-title">
          <h2 id="calendar-title" className="section-title">
            {formatMonthLabel(month, thisMonth)}
          </h2>
          {monthMinutes > 0 && <span className="calendar-total">{formatCompactMinutes(monthMinutes)} focused</span>}
        </div>
        <div className="calendar-nav">
          <button type="button" aria-label="Previous month" onClick={() => setMonth(shiftMonth(month, -1))}>
            <ChevronLeft size={18} strokeWidth={1.8} aria-hidden="true" />
          </button>
          <button type="button" aria-label="Next month" disabled={month >= thisMonth} onClick={() => setMonth(shiftMonth(month, 1))}>
            <ChevronRight size={18} strokeWidth={1.8} aria-hidden="true" />
          </button>
        </div>
      </div>
      <div className="calendar-grid">
        {WEEKDAYS.map((weekday) => (
          <span key={weekday} className="calendar-weekday" aria-hidden="true">
            {weekday}
          </span>
        ))}
        {weeks.flat().map((cell) => {
          const minutes = readMinutes(cell.day);
          const name = formatDayLabel(cell.day, { month: "long", day: "numeric" });
          return cell.inMonth ? (
            <button
              key={cell.day}
              type="button"
              className="day"
              data-shade={readShade(minutes)}
              data-today={cell.day === today || undefined}
              data-picked={cell.day === picked || undefined}
              disabled={cell.day > today}
              aria-haspopup="dialog"
              aria-label={minutes > 0 ? `${name}, ${formatCompactMinutes(minutes)} focused` : name}
              onClick={(event) => {
                opener.current = event.currentTarget;
                setPicked(cell.day);
              }}
            >
              <span>{cell.date}</span>
              <span className="day-minutes">{minutes > 0 ? formatCompactMinutes(minutes) : ""}</span>
            </button>
          ) : (
            <span key={cell.day} className="day day-outside" aria-hidden="true">
              {cell.date}
            </span>
          );
        })}
      </div>
      <PopDialog open={picked != null} onOpenChange={(open) => !open && setPicked(null)} className="day-dialog" onCloseAutoFocus={returnFocus}>
        {picked != null && <DayPage day={picked} isToday={picked === today} now={now} />}
      </PopDialog>
    </section>
  );
}
