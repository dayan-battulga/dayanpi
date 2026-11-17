export const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
// Focus minutes where each shade starts: any focus, an hour, two hours, four hours.
export const SHADE_STARTS = [1, 60, 120, 240];

export interface CalendarDay {
  day: string; // YYYY-MM-DD
  date: number;
  inMonth: boolean;
}

function pad(value: number): string {
  const padded = String(value).padStart(2, "0");
  return padded;
}

function readMonthParts(month: string): { year: number; index: number } {
  const [year, monthNumber] = month.split("-").map(Number);
  const parts = { year, index: monthNumber - 1 };
  return parts;
}

export function formatDayKey(date: Date): string {
  const key = `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;
  return key;
}

export function shiftMonth(month: string, step: number): string {
  const { year, index } = readMonthParts(month);
  const shifted = new Date(year, index + step, 1);
  const key = formatDayKey(shifted).slice(0, 7);
  return key;
}

// Whole weeks, Sunday first, padded out with the days of the months on either side.
export function buildMonthWeeks(month: string): CalendarDay[][] {
  const { year, index } = readMonthParts(month);
  const offset = new Date(year, index, 1).getDay();
  const length = new Date(year, index + 1, 0).getDate();
  const cells = Math.ceil((offset + length) / 7) * 7;
  const days = Array.from({ length: cells }, (_, cell) => {
    const date = new Date(year, index, 1 - offset + cell);
    return { day: formatDayKey(date), date: date.getDate(), inMonth: date.getMonth() === index };
  });
  const weeks = Array.from({ length: cells / 7 }, (_, week) => days.slice(week * 7, week * 7 + 7));
  return weeks;
}

export function readShade(minutes: number): number {
  const shade = SHADE_STARTS.filter((start) => minutes >= start).length;
  return shade;
}

// "November", or "November 2025" for another year's.
export function formatMonthLabel(month: string, thisMonth: string): string {
  const { year, index } = readMonthParts(month);
  const options: Intl.DateTimeFormatOptions = month.slice(0, 4) === thisMonth.slice(0, 4) ? { month: "long" } : { month: "long", year: "numeric" };
  const label = new Date(year, index, 1).toLocaleDateString([], options);
  return label;
}

// A YYYY-MM-DD in words: "November 15", or "Sunday, November 15" with the weekday asked for.
export function formatDayLabel(day: string, options: Intl.DateTimeFormatOptions): string {
  const [year, month, date] = day.split("-").map(Number);
  const label = new Date(year, month - 1, date).toLocaleDateString([], options);
  return label;
}

// The calendar's durations: "45m", "3h", "1h 35m".
export function formatCompactMinutes(minutes: number): string {
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  const text = hours === 0 ? `${rest}m` : rest === 0 ? `${hours}h` : `${hours}h ${rest}m`;
  return text;
}
