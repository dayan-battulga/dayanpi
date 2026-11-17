import { describe, expect, it } from "vitest";
import { formatClock, formatDuration } from "@/lib/format";
import { readUptime } from "@/lib/pi";

describe("formatDuration", () => {
  it.each([
    [0, "0s"],
    [59.4, "59s"],
    [60, "1m"],
    [3599, "59m"],
    [3600 + 5 * 60, "1h 05m"],
    [-3, "0s"],
  ])("%s seconds is %s", (seconds, text) => {
    expect(formatDuration(seconds)).toBe(text);
  });
});

describe("formatClock", () => {
  it.each([
    [0, "00:00"],
    [65.9, "01:05"],
    [3600 + 2 * 60 + 5, "1:02:05"],
  ])("%s seconds is %s", (seconds, text) => {
    expect(formatClock(seconds)).toBe(text);
  });
});

it("splits uptime into days and hours, or hours and minutes under a day", () => {
  expect(readUptime(6 * 86400 + 4 * 3600 + 59 * 60)).toEqual({ first: 6, firstUnit: "d", second: 4, secondUnit: "h" });
  expect(readUptime(4 * 3600 + 12 * 60 + 59)).toEqual({ first: 4, firstUnit: "h", second: 12, secondUnit: "m" });
});
