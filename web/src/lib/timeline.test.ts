import { describe, expect, it } from "vitest";
import { buildTodayItems, describePhoneFree, layoutTimeline, mergeKnownSegments, readLocalMidnight } from "@/lib/timeline";
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
    expect(layout.hours.map((entry) => entry.hour)).toEqual([6, 9, 12, 15, 18, 21, 24]);
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
    expect(layout.hours[0]).toEqual({ hour: 4, left: 0 });
    expect(layout.pieces[1].width).toBe(0.4);
  });
});

describe("buildTodayItems", () => {
  it("lists the last five changes newest first, saying what kind of change each was", () => {
    const known: Segment[] = [
      { state: "working", start: at(9), end: at(10) },
      { state: "phone", start: at(10), end: at(10, 5) },
      { state: "working", start: at(10, 5), end: at(11) },
      { state: "away", start: at(11), end: at(12) },
      { state: "working", start: at(12), end: at(13) },
      { state: "phone", start: at(13), end: null },
    ];
    const titles = buildTodayItems(known).map((item) => item.title);
    expect(titles).toEqual(["Picked up your phone", "Back at the desk", "Stepped away", "Back to work", "Picked up your phone"]);
  });
});

describe("describePhoneFree", () => {
  const focus = { state: "working", today: { first_seen: at(9) } } as FocusStatus;
  it("counts from the last pickup, or says all day without one", () => {
    expect(describePhoneFree(focus, [{ state: "phone", start: at(10), end: at(10, 5) }], at(11, 5))).toBe("1h 00m");
    expect(describePhoneFree(focus, [], at(11))).toBe("all day");
    expect(describePhoneFree({ ...focus, state: "phone" }, [], at(11))).toBe("on it now");
  });
});

it("finds local midnight", () => {
  expect(readLocalMidnight(at(15, 30))).toBe(MIDNIGHT);
});
