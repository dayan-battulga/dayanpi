import { formatDuration, formatTimeOfDay } from "@/lib/format";
import type { FocusState, FocusStatus, Segment } from "@/lib/types";

export const DAY_SECONDS = 86400;
export const DAY_START_HOUR = 6;
export const HOUR_LABEL_STEP = 3;
export const TODAY_LIST_LENGTH = 5;
export const MIN_SEGMENT_SHARE = 0.4; // % of the bar, so a one-minute pickup still shows
export const MERGE_GAP_S = 60;

export const STATE_COPY: Record<FocusState, { chip: string; label: string }> = {
  working: { chip: "Working", label: "Focused" },
  phone: { chip: "On phone", label: "Phone up" },
  away: { chip: "Away", label: "Stepped away" },
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
  hours: { hour: number; left: number }[];
  pieces: TimelinePiece[];
  cursorLeft: number;
}

export interface TodayItem {
  key: string;
  at: number;
  kind: FocusState;
  title: string;
  segment: Segment;
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
  const startHour = Math.max(0, Math.min(DAY_START_HOUR, firstHour));
  const windowStart = midnight + startHour * 3600;
  const windowSpan = DAY_SECONDS - startHour * 3600;
  const shareOf = (seconds: number) => (seconds / windowSpan) * 100;

  const labelled = [startHour];
  for (let hour = Math.ceil((startHour + 1) / HOUR_LABEL_STEP) * HOUR_LABEL_STEP; hour < 24; hour += HOUR_LABEL_STEP) {
    labelled.push(hour);
  }
  labelled.push(24);

  const layout: TimelineLayout = {
    startHour,
    hours: labelled.map((hour) => ({ hour, left: ((hour - startHour) / (24 - startHour)) * 100 })),
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

export function describeSegment(segment: Segment, previous: Segment | undefined): string {
  let title = "Stepped away";
  if (segment.state === "phone") {
    title = "Picked up your phone";
  } else if (segment.state === "working" && previous?.state === "away") {
    title = "Back at the desk";
  } else if (segment.state === "working" && previous?.state === "phone") {
    title = "Back to work";
  } else if (segment.state === "working") {
    title = "Sat down to work";
  }
  return title;
}

export function describeLength(segment: Segment, now: number): string {
  const length = formatDuration((segment.end ?? now) - segment.start);
  const text = segment.end == null ? `now · ${length}` : length;
  return text;
}

// State changes, newest first.
export function buildTodayItems(known: Segment[]): TodayItem[] {
  const items = known.map((segment, index) => ({
    key: `${segment.state}@${segment.start}:${segment.end == null}`,
    at: segment.start,
    kind: segment.state,
    title: describeSegment(segment, known[index - 1]),
    segment,
  }));
  items.sort((first, second) => second.at - first.at);
  const recent = items.slice(0, TODAY_LIST_LENGTH);
  return recent;
}

export function describePhoneFree(focus: FocusStatus, segments: Segment[], now: number): string {
  const phoneEnds = segments.filter((segment) => segment.state === "phone" && segment.end != null).map((segment) => segment.end as number);
  let text = "--";
  if (focus.state === "phone") {
    text = "on it now";
  } else if (phoneEnds.length > 0) {
    text = formatDuration(now - Math.max(...phoneEnds));
  } else if (focus.today.first_seen != null) {
    text = "all day";
  }
  return text;
}

export function describeCaption(focus: FocusStatus): string {
  let caption = "Working out what you're up to";
  if (!focus.enabled) {
    caption = "The detector isn't running on the Pi";
  } else if (!focus.camera_ok) {
    caption = "No camera frames · time isn't counted";
  } else if (focus.state === "working") {
    caption = `Current streak · since ${formatTimeOfDay(focus.since)}`;
  } else if (focus.state === "phone") {
    caption = "Counting toward today's phone time";
  } else if (focus.state === "away") {
    caption = `Away since ${formatTimeOfDay(focus.since)}`;
  }
  return caption;
}
