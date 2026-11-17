import { formatDuration, formatTimeOfDay } from "@/lib/format";
import type { FocusState, FocusStatus, Segment } from "@/lib/types";

export const DAY_SECONDS = 86400;
export const DAY_START_HOUR = 6;
export const MIN_SEGMENT_SHARE = 0.4; // % of the bar, so a one-minute pickup still shows
export const MERGE_GAP_S = 60;

// chip: the short name in a segment's tooltip. label: the Desk's big state word.
export const STATE_COPY: Record<FocusState, { chip: string; label: string }> = {
  working: { chip: "Working", label: "Focused" },
  phone: { chip: "On phone", label: "On your phone" },
  away: { chip: "Away", label: "Away" },
  unknown: { chip: "Unknown", label: "Waiting" },
};

export interface TimelinePiece {
  state: FocusState;
  start: number;
  left: number;
  width: number;
  live: boolean;
  title: string;
}

export interface TimelineLayout {
  startHour: number;
  pieces: TimelinePiece[];
  cursorLeft: number;
}

export function readLocalMidnight(now: number): number {
  const midnight = new Date(now * 1000);
  midnight.setHours(0, 0, 0, 0);
  const seconds = midnight.getTime() / 1000;
  return seconds;
}

// Drops the unknown stretches and joins short gaps, so a camera blip doesn't split a streak
// but a Pi that was off for an hour still shows as a hole.
export function mergeKnownSegments(segments: Segment[], midnight: number): Segment[] {
  const merged: Segment[] = [];
  for (const segment of segments) {
    const ends = segment.end ?? Infinity;
    if (segment.state !== "unknown" && ends > midnight) {
      const start = Math.max(segment.start, midnight);
      const previous = merged[merged.length - 1];
      if (previous != null && previous.state === segment.state && previous.end != null && start - previous.end <= MERGE_GAP_S) {
        previous.end = segment.end;
      } else {
        merged.push({ state: segment.state, start, end: segment.end });
      }
    }
  }
  return merged;
}

export function layoutTimeline(known: Segment[], now: number, midnight: number): TimelineLayout {
  const firstHour = known.length > 0 ? Math.floor((known[0].start - midnight) / 3600) : DAY_START_HOUR;
  // Starts earlier when the day did, or when it's still before 6 am, so the now marker never falls off the left end.
  const nowHour = Math.floor((now - midnight) / 3600);
  const startHour = Math.max(0, Math.min(DAY_START_HOUR, firstHour, nowHour));
  const windowStart = midnight + startHour * 3600;
  const windowSpan = DAY_SECONDS - startHour * 3600;
  const shareOf = (seconds: number) => (seconds / windowSpan) * 100;

  const layout: TimelineLayout = {
    startHour,
    pieces: known.map((segment) => {
      const end = segment.end ?? now;
      return {
        state: segment.state,
        start: segment.start,
        left: shareOf(segment.start - windowStart),
        width: Math.max(shareOf(end - segment.start), MIN_SEGMENT_SHARE),
        live: segment.end == null,
        title: `${STATE_COPY[segment.state].chip} · ${formatTimeOfDay(segment.start)} · ${formatDuration(end - segment.start)}`,
      };
    }),
    cursorLeft: Math.min(100, shareOf(now - windowStart)),
  };
  return layout;
}

// The timeline's left end: "6 am", or earlier on a day that started before it.
export function describeStartHour(hour: number): string {
  return `${hour % 12 || 12} ${hour < 12 ? "am" : "pm"}`;
}

// What's wrong that the Desk should mention under its stats, quietly; "" when nothing is.
export function describeProblems(focus: FocusStatus): string {
  const problems: string[] = [];
  // Only the owner's desk has the Pi's cameras for now; everyone else's says so instead of looking broken.
  if (focus.camera_access === "owner_only") {
    problems.push("No camera on your desk yet, so time isn't counted");
  } else if (!focus.enabled) {
    problems.push("The detector isn't running on the Pi");
  } else if (!focus.camera_ok) {
    problems.push("No camera frames, so time isn't counted");
  }
  if (focus.voice?.problem) {
    problems.push(`The voice is off: ${focus.voice.problem}`);
  }
  return problems.join(" · ");
}
