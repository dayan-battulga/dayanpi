import { afterEach, expect, it, vi } from "vitest";
import { findMedian, splitSegments, startLoop, summarizeChecks, WARMUP_CHECKS, type CheckRecord, type GapRecord } from "@/lib/trackTest";

const check = (at: number, ms = 100, changes: Partial<CheckRecord> = {}): CheckRecord => ({
  at,
  ms,
  fresh: true,
  person: 0.9,
  phone: 0,
  sign: null,
  handsFailed: false,
  ...changes,
});

afterEach(() => {
  vi.useRealTimers();
});

it("leaves out the warm-up, and counts a check late when it starts over 1.25 s after the one before", () => {
  const warmup = [check(0, 900), check(1000, 800), check(2000, 700)];
  const counted = [check(3000, 100), check(4000, 300), check(5300, 120, { person: 0.2 }), check(6300, 0, { fresh: false }), check(7300, 200)];
  const summary = summarizeChecks([...warmup, ...counted]);
  expect(warmup).toHaveLength(WARMUP_CHECKS);
  expect(summary).toEqual({ checks: 5, medianMs: 160, slowestMs: 300, late: 1, noFrame: 1, personShare: 0.75, handFailures: 0 });
});

it("splits each loop's gaps by where the page was", () => {
  const records: GapRecord[] = [
    { loop: "worker", place: "visible", at: 0, fresh: true },
    { loop: "page", place: "visible", at: 10, fresh: true },
    { loop: "worker", place: "visible", at: 1000, fresh: true },
    { loop: "page", place: "visible", at: 1010, fresh: true },
    { loop: "worker", place: "hidden", at: 2000, fresh: true },
    { loop: "page", place: "hidden", at: 3010, fresh: false },
    { loop: "worker", place: "hidden", at: 3000, fresh: true },
    { loop: "page", place: "hidden", at: 63010, fresh: true },
  ];
  const segments = splitSegments(records).map(({ loop, place, checks, medianGapMs, longestGapMs, late, noFrame }) => ({ loop, place, checks, medianGapMs, longestGapMs, late, noFrame }));
  expect(segments).toEqual([
    { loop: "worker", place: "visible", checks: 2, medianGapMs: 1000, longestGapMs: 1000, late: 0, noFrame: 0 },
    { loop: "page", place: "visible", checks: 2, medianGapMs: 1000, longestGapMs: 1000, late: 0, noFrame: 0 },
    { loop: "worker", place: "hidden", checks: 2, medianGapMs: 1000, longestGapMs: 1000, late: 0, noFrame: 0 },
    { loop: "page", place: "hidden", checks: 2, medianGapMs: 31000, longestGapMs: 60000, late: 2, noFrame: 1 },
  ]);
});

it("finds the median of odd and even counts", () => {
  expect([findMedian([3, 1, 2]), findMedian([4, 1, 3, 2]), findMedian([])]).toEqual([2, 2.5, 0]);
});

it("asks for the wait again after every check", async () => {
  vi.useFakeTimers();
  const starts: number[] = [];
  const waits = [3000, 1000, 2000];
  const stop = startLoop(
    async () => {
      starts.push(performance.now());
    },
    () => waits[starts.length - 1] ?? 1000,
  );
  await vi.advanceTimersByTimeAsync(6500);
  stop();
  const gaps = starts.slice(1).map((start, index) => start - starts[index]);
  expect(gaps).toEqual([3000, 1000, 2000]);
});

it("starts a check every second from each start, waits out a slow one, and stops", async () => {
  vi.useFakeTimers();
  const starts: number[] = [];
  const stop = startLoop(async () => {
    starts.push(performance.now());
    await new Promise((resolve) => setTimeout(resolve, starts.length === 2 ? 1500 : 200));
  }, () => 1000);
  await vi.advanceTimersByTimeAsync(4200);
  stop();
  await vi.advanceTimersByTimeAsync(3000);
  const gaps = starts.slice(1).map((start, index) => start - starts[index]);
  // A zero wait is a 1 ms timer under fake timers.
  expect(gaps).toEqual([1000, expect.closeTo(1500, -1), 1000]);
});
