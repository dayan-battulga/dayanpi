import { ChevronLeft, ChevronRight } from "lucide-react";
import { useEffect, useState } from "react";
import { DayPage } from "@/components/calendar/DayPage";
import { riseDelay } from "@/components/shared/rise";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { WEEKDAYS, buildMonthWeeks, formatCompactMinutes, formatDayKey, formatMonthLabel, readShade, shiftMonth } from "@/lib/calendar";
import { fetchJson } from "@/lib/http";
import type { DayPageReply, MonthDays } from "@/lib/types";

const MONTH_REFRESH_S = 300; // also how soon yesterday's page shows up after midnight
const TODAY_REFRESH_S = 60;
const SHADE_CLASSES = ["", "bg-work/10", "bg-work/25", "bg-work/40", "bg-work/60"];

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
  const [page, setPage] = useState<{ day: string; markdown: string | null } | null>(null);
  const monthRefresh = Math.floor(now / MONTH_REFRESH_S);
  const pageRefresh = picked === today ? Math.floor(now / TODAY_REFRESH_S) : 0;

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

  useEffect(() => {
    let current = true;
    if (picked != null) {
      fetchJson<DayPageReply>(`/api/days/${picked}`).then((reply) => {
        if (current) {
          setPage({ day: picked, markdown: reply?.markdown ?? null });
        }
      });
    }
    return () => {
      current = false;
    };
  }, [picked, pageRefresh]);

  const shownDays = monthDays?.month === month ? monthDays.days : {};
  // Today's number comes from the live stream; the rest from the pages.
  const readMinutes = (day: string) => (day === today && todayFocusSeconds != null ? Math.round(todayFocusSeconds / 60) : shownDays[day]?.focus_minutes);
  const weeks = buildMonthWeeks(month);
  const monthMinutes = weeks.flat().reduce((sum, cell) => sum + (cell.inMonth ? (readMinutes(cell.day) ?? 0) : 0), 0);

  return (
    <Card id="calendar" className="card rise gap-0 p-5" style={riseDelay(4)} aria-label="Calendar">
      <div className="card-head">
        <div className="card-title">
          <h2 className="label">Calendar</h2>
          <span className="mono muted small">{monthMinutes > 0 ? `${formatCompactMinutes(monthMinutes)} focused` : ""}</span>
        </div>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon-sm" aria-label="Previous month" onClick={() => setMonth(shiftMonth(month, -1))}>
            <ChevronLeft />
          </Button>
          <span className="min-w-36 text-center text-sm font-medium">{formatMonthLabel(month)}</span>
          <Button variant="ghost" size="icon-sm" aria-label="Next month" disabled={month >= thisMonth} onClick={() => setMonth(shiftMonth(month, 1))}>
            <ChevronRight />
          </Button>
        </div>
      </div>
      <table className="w-full table-fixed text-center">
        <thead>
          <tr>
            {WEEKDAYS.map((weekday) => (
              <th key={weekday} scope="col" className="pb-1.5 text-[11px] font-medium tracking-wide text-muted-foreground uppercase">
                {weekday}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {weeks.map((week) => (
            <tr key={week[0].day}>
              {week.map((cell) => {
                const minutes = readMinutes(cell.day);
                const ring = picked === cell.day ? "ring-2 ring-foreground" : cell.day === today ? "ring-1 ring-foreground/50" : "";
                return (
                  <td key={cell.day} className="p-0.5">
                    {cell.inMonth ? (
                      <button
                        type="button"
                        disabled={cell.day > today}
                        aria-pressed={picked === cell.day}
                        aria-label={minutes ? `${cell.day}, ${formatCompactMinutes(minutes)} focused` : cell.day}
                        onClick={() => setPicked(picked === cell.day ? null : cell.day)}
                        className={`flex h-14 w-full flex-col items-center justify-center gap-0.5 rounded-md text-sm transition-colors hover:bg-accent disabled:pointer-events-none disabled:opacity-40 ${SHADE_CLASSES[readShade(minutes ?? 0)]} ${ring} ${cell.day === today ? "font-semibold" : ""}`}
                      >
                        <span>{cell.date}</span>
                        <span className="mono text-[11px] leading-none text-foreground/70">{minutes ? formatCompactMinutes(minutes) : ""}</span>
                      </button>
                    ) : (
                      <span className="flex h-14 items-center justify-center text-sm text-muted-foreground/40">{cell.date}</span>
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {picked != null && (
        <div className="mt-4 border-t pt-4" aria-live="polite">
          {page?.day !== picked ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : page.markdown == null ? (
            <p className="text-sm text-muted-foreground">No page for this day.</p>
          ) : (
            <DayPage markdown={page.markdown} />
          )}
        </div>
      )}
    </Card>
  );
}
