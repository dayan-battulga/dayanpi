import { formatDuration } from "@/lib/format";
import type { Seat, SeatState, SharedPart } from "@/lib/types";

// The Pi's own rules (focus/sharing.py), so a button only shows when the nudge would go through.
export const NUDGE_AFTER_S = 5 * 60;

// The second half of a seat's name for screen readers: "Sam, on the phone".
export const SEAT_WORDS: Record<SeatState, string> = {
  working: "focused",
  phone: "on the phone",
  away: "away",
  unknown: "here",
  offline: "offline",
};

// "On the phone", for the rail, the peek and their desk.
export function describeSeatState(state: SeatState): string {
  const word = SEAT_WORDS[state];
  return word[0].toUpperCase() + word.slice(1);
}

// Yours first, then everyone else in the order they joined.
export function orderSeats(seats: Seat[], username: string | undefined): Seat[] {
  const ordered = [...seats.filter((seat) => seat.username === username), ...seats.filter((seat) => seat.username !== username)];
  return ordered;
}

export interface RoomSummary {
  here: Seat[];
  focusSeconds: number; // today, of everyone here who shares their focus time
  caption: string;
  hereLabel: string;
}

// The big number over the seats and the line under it: "7h 05m" / "3 here · focused together today".
export function summarizeRoom(seats: Seat[]): RoomSummary {
  const here = seats.filter((seat) => seat.here);
  const together = here.length > 1;
  const summary = {
    here,
    focusSeconds: here.reduce((sum, seat) => sum + (seat.focus_seconds ?? 0), 0),
    caption: together ? `${here.length} here · focused together today` : "focused today",
    hereLabel: together ? `Here now: ${new Intl.ListFormat("en", { type: "conjunction" }).format(here.map((seat) => seat.name))}` : "Here now: just you",
  };
  return summary;
}

export interface SeatLine {
  todo: string | null; // the current to-do, "· paused" while they're not working on it
  app: string | null; // "VS Code", or "Chrome, docs.google.com"
}

// What's under a seat's name; each half only if they share it.
export function describeSeatLine(seat: Seat): SeatLine {
  const current = seat.todos?.current ?? null;
  const app = seat.app ?? null;
  const line = {
    todo: current == null ? null : seat.state === "working" ? current : `${current} · paused`,
    app: app == null ? null : seat.site != null ? `${app}, ${seat.site}` : app,
  };
  return line;
}

// The to-dos-done bar along a seat's bottom, as a percent; null when there's no list to show.
export function findDoneShare(seat: Seat): number | null {
  const total = seat.todos?.total ?? 0;
  const share = total > 0 ? (100 * (seat.todos?.done ?? 0)) / total : null;
  return share;
}

export interface SharedPiece {
  key: "focus" | "todos" | "apps" | "sites";
  text: string;
}

// Settings' preview chips under your seat: each part the room gets, as the room gets it.
export function listSharedPieces(seat: Seat): SharedPiece[] {
  const pieces: (SharedPiece | null)[] = [
    seat.focus_seconds == null ? null : { key: "focus", text: `${formatDuration(seat.focus_seconds)} today` },
    seat.todos?.current == null ? null : { key: "todos", text: seat.todos.current },
    seat.app == null ? null : { key: "apps", text: seat.app },
    seat.site == null ? null : { key: "sites", text: seat.site },
  ];
  const shared = pieces.filter((piece) => piece != null);
  return shared;
}

export function readInitial(name: string): string {
  const initial = (name.trim()[0] ?? "?").toUpperCase();
  return initial;
}

// A to-do's time: "24m", or a dash before its first minute.
export function formatTodoTime(seconds: number | null | undefined): string {
  const text = seconds == null || seconds < 60 ? "—" : formatDuration(seconds);
  return text;
}

// The line under someone's current to-do: "24m · paused · Chrome, docs.google.com", each part only if they share it.
export function describeTaskMeta(seat: Seat): string {
  const parts = [
    seat.todos?.current == null ? null : formatTodoTime(seat.todos.current_seconds),
    seat.todos?.current != null && seat.state !== "working" ? "paused" : null,
    describeSeatLine(seat).app,
  ];
  const meta = parts.filter((part) => part != null).join(" · ");
  return meta;
}

// The nudge button shows on someone else who's taken nudges and been on their phone NUDGE_AFTER_S, even while it waits.
export function isNudgeable(seat: Seat, username: string | undefined): boolean {
  const nudgeable = seat.username !== username && seat.nudge != null && seat.state === "phone" && (seat.seconds_in_state ?? 0) >= NUDGE_AFTER_S;
  return nudgeable;
}

const PART_NAMES: Record<SharedPart, string> = { focus: "focus time", todos: "to-dos", apps: "apps", sites: "sites", video: "video", history: "history" };

// "Sam shares status, to-dos and history", or "Sam shares status only".
export function describeShares(seat: Seat): string {
  const shared = ["status", ...seat.shares.map((part) => PART_NAMES[part])];
  const list = shared.length === 1 ? "status only" : `${shared.slice(0, -1).join(", ")} and ${shared[shared.length - 1]}`;
  return `${seat.name} shares ${list}`;
}

// Everyone here but you, for the sidebar and the bottom bar.
export function listOthersHere(seats: Seat[], username: string | undefined): Seat[] {
  const others = seats.filter((seat) => seat.here && seat.username !== username);
  return others;
}
