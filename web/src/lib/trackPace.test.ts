import { expect, it } from "vitest";
import { BUSY_INTERVAL_MS, CheckPacer, IDLE_INTERVAL_MS, NORMAL_INTERVAL_MS } from "@/lib/trackPace";

// Checks one after another from `from`, each taking ms and seeing someone or not; returns the pace after the last one.
function runChecks(pacer: CheckPacer, from: number, count: number, ms: number, sawPerson: boolean) {
  let at = from;
  let pace = pacer.pace(at);
  for (let index = 0; index < count; index++) {
    pacer.record(at, ms, sawPerson);
    pace = pacer.pace(at + ms);
    at += Math.max(pace.intervalMs, ms);
  }
  return { pace, at };
}

it("checks once a second while someone's there", () => {
  const pacer = new CheckPacer(0);
  expect(runChecks(pacer, 0, 30, 150, true).pace).toEqual({ intervalMs: NORMAL_INTERVAL_MS, reason: "normal" });
});

it("backs off to every 3 s once nobody's been seen for 10 s, and comes back on the first check that sees someone", () => {
  const pacer = new CheckPacer(0);
  const seen = runChecks(pacer, 0, 5, 150, true);
  const nine = runChecks(pacer, seen.at, 9, 150, false);
  expect(nine.pace.reason).toBe("normal");
  const gone = runChecks(pacer, nine.at, 2, 150, false);
  expect(gone.pace).toEqual({ intervalMs: IDLE_INTERVAL_MS, reason: "idle" });
  expect(runChecks(pacer, gone.at, 1, 150, true).pace).toEqual({ intervalMs: NORMAL_INTERVAL_MS, reason: "normal" });
});

it("slows to every 2 s after a minute of slow checks, and goes back after a minute of good ones", () => {
  const pacer = new CheckPacer(0);
  const slow = runChecks(pacer, 0, 61, 700, true);
  expect(slow.pace).toEqual({ intervalMs: BUSY_INTERVAL_MS, reason: "busy" });
  const better = runChecks(pacer, slow.at, 20, 200, true);
  expect(better.pace.reason).toBe("busy");
  expect(runChecks(pacer, better.at, 20, 200, true).pace.reason).toBe("normal");
});

it("counts checks that start late as bad too", () => {
  const pacer = new CheckPacer(0);
  let at = 0;
  for (let index = 0; index < 50; index++) {
    pacer.record(at, 200, true);
    pacer.pace(at);
    at += 1600;
  }
  expect(pacer.pace(at).reason).toBe("busy");
});

it("a short spell of slow checks doesn't slow it down", () => {
  const pacer = new CheckPacer(0);
  const fine = runChecks(pacer, 0, 40, 200, true);
  const spike = runChecks(pacer, fine.at, 10, 700, true);
  expect(runChecks(pacer, spike.at, 30, 200, true).pace.reason).toBe("normal");
});

it("slows down on a low battery and says so, but nobody there still wins", () => {
  const pacer = new CheckPacer(0);
  pacer.setLowBattery(true);
  expect(pacer.pace(0)).toEqual({ intervalMs: BUSY_INTERVAL_MS, reason: "battery" });
  expect(pacer.pace(10_000)).toEqual({ intervalMs: IDLE_INTERVAL_MS, reason: "idle" });
  pacer.setLowBattery(false);
  pacer.record(10_000, 150, true);
  expect(pacer.pace(10_200).reason).toBe("normal");
});
