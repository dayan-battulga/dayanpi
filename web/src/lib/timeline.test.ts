import { describe, expect, it } from "vitest";
import { describeProblems, describeStartHour, isWaitingForTracker, layoutTimeline, mergeKnownSegments, readLocalMidnight } from "@/lib/timeline";
import type { FocusStatus, Segment } from "@/lib/types";

const MIDNIGHT = new Date(2026, 10, 15).getTime() / 1000;
const at = (hours: number, minutes = 0) => MIDNIGHT + hours * 3600 + minutes * 60;

describe("mergeKnownSegments", () => {
  it("drops unknown stretches, joins gaps up to a minute, and keeps longer holes", () => {
    const segments: Segment[] = [
      { state: "working", start: at(9), end: at(10) },
      { state: "unknown", start: at(10), end: at(10, 0) + 30 },
      { state: "working", start: at(10, 0) + 30, end: at(11) },
      { state: "unknown", start: at(11), end: at(12) },
      { state: "working", start: at(12), end: null },
    ];
    expect(mergeKnownSegments(segments, MIDNIGHT)).toEqual([
      { state: "working", start: at(9), end: at(11) },
      { state: "working", start: at(12), end: null },
    ]);
  });

  it("cuts off whatever happened before midnight", () => {
    const segments: Segment[] = [{ state: "working", start: MIDNIGHT - 600, end: at(0, 30) }];
    expect(mergeKnownSegments(segments, MIDNIGHT)).toEqual([{ state: "working", start: MIDNIGHT, end: at(0, 30) }]);
  });
});

describe("layoutTimeline", () => {
  it("runs 6 am to midnight, with the open segment and the cursor reaching now", () => {
    const now = at(15);
    const layout = layoutTimeline([{ state: "working", start: at(9), end: null }], now, MIDNIGHT);
    expect(layout.startHour).toBe(6);
    expect(describeStartHour(layout.startHour)).toBe("6 am");
    expect(layout.pieces[0].left).toBeCloseTo((3 / 18) * 100);
    expect(layout.pieces[0].width).toBeCloseTo((6 / 18) * 100);
    expect(layout.pieces[0].live).toBe(true);
    expect(layout.cursorLeft).toBeCloseTo((9 / 18) * 100);
  });

  it("starts earlier when the day did, and keeps a one-minute pickup visible", () => {
    const known: Segment[] = [
      { state: "working", start: at(4, 30), end: at(5) },
      { state: "phone", start: at(5), end: at(5, 1) },
    ];
    const layout = layoutTimeline(known, at(6), MIDNIGHT);
    expect(layout.startHour).toBe(4);
    expect(describeStartHour(layout.startHour)).toBe("4 am");
    expect(describeStartHour(0)).toBe("12 am");
    expect(layout.pieces[0].left).toBeCloseTo(((4.5 - 4) / 20) * 100);
    expect(layout.pieces[1].width).toBe(0.4);
  });

  it("starts at the current hour before 6 am with nothing yet, so the now marker stays on the track", () => {
    const layout = layoutTimeline([], at(2, 30), MIDNIGHT);
    expect(layout.startHour).toBe(2);
    expect(layout.cursorLeft).toBeCloseTo((0.5 / 22) * 100);
  });
});

describe("describeProblems", () => {
  const fine = { enabled: true, camera_ok: true, voice: { enabled: true, backend: "piper", problem: null } } as FocusStatus;
  it("says nothing when all is well, and joins what's wrong into one line", () => {
    expect(describeProblems(fine)).toBe("");
    expect(describeProblems({ ...fine, camera_ok: false })).toBe("No camera frames, so time isn't counted");
    expect(describeProblems({ ...fine, enabled: false, camera_ok: false, voice: { enabled: true, backend: "piper", problem: "aplay isn't installed" } })).toBe(
      "The detector isn't running on the Pi · The voice is off: aplay isn't installed",
    );
  });

  it("leaves a quiet browser camera to the tracker link, and says when it's paused", () => {
    const browser = { ...fine, camera_source: "browser", camera_ok: false, voice: null } as FocusStatus;
    expect(describeProblems(browser)).toBe("");
    expect(isWaitingForTracker(browser)).toBe(true);
    expect(describeProblems({ ...browser, camera_paused: true })).toBe("Tracking is paused on the tracker page");
    expect(isWaitingForTracker({ ...browser, camera_paused: true })).toBe(false);
    expect(isWaitingForTracker({ ...browser, camera_ok: true })).toBe(false);
    expect(isWaitingForTracker({ ...fine, camera_source: "pi", camera_ok: false } as FocusStatus)).toBe(false);
  });
});

it("finds local midnight", () => {
  expect(readLocalMidnight(at(15, 30))).toBe(MIDNIGHT);
});
