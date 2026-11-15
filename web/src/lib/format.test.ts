import { describe, expect, it } from "vitest";
import { formatBits, formatClock, formatDuration, formatUptime } from "@/lib/format";

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
    [0, "0:00"],
    [65.9, "1:05"],
    [3600 + 2 * 60 + 5, "1:02:05"],
  ])("%s seconds is %s", (seconds, text) => {
    expect(formatClock(seconds)).toBe(text);
  });
});

it("formats uptime and network speed", () => {
  expect(formatUptime(2 * 86400 + 3 * 3600 + 4 * 60 + 59)).toBe("2d 3h 4m");
  expect(formatBits(999.6)).toBe("1000 kb/s");
  expect(formatBits(1250)).toBe("1.3 Mb/s");
});
