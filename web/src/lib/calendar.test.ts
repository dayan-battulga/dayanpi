import { describe, expect, it } from "vitest";
import { buildMonthWeeks, formatCompactMinutes, readShade, shiftMonth } from "@/lib/calendar";
import { parseDayPage } from "@/lib/markdown";

describe("buildMonthWeeks", () => {
  it("starts on Sunday and pads with the neighbouring months", () => {
    const weeks = buildMonthWeeks("2026-11"); // Nov 1 2026 is a Sunday
    expect(weeks).toHaveLength(5);
    expect(weeks[0][0]).toEqual({ day: "2026-11-01", date: 1, inMonth: true });
    expect(weeks[4].map((cell) => cell.day)).toEqual(["2026-11-29", "2026-11-30", "2026-12-01", "2026-12-02", "2026-12-03", "2026-12-04", "2026-12-05"]);
    expect(weeks[4][2].inMonth).toBe(false);
  });

  it("fits a February that starts on Sunday in four weeks", () => {
    const weeks = buildMonthWeeks("2026-02");
    expect(weeks).toHaveLength(4);
    expect(weeks.flat().every((cell) => cell.inMonth)).toBe(true);
  });

  it("takes six weeks for a 31-day month that starts on Saturday", () => {
    const weeks = buildMonthWeeks("2026-08");
    expect(weeks).toHaveLength(6);
    expect(weeks[0].slice(5).map((cell) => cell.day)).toEqual(["2026-07-31", "2026-08-01"]);
    expect(weeks[5][1].day).toBe("2026-08-31");
  });

  it("counts a leap day", () => {
    expect(buildMonthWeeks("2028-02").flat().filter((cell) => cell.inMonth)).toHaveLength(29);
  });
});

it("shifts months across years", () => {
  expect(shiftMonth("2026-01", -1)).toBe("2025-12");
  expect(shiftMonth("2026-12", 1)).toBe("2027-01");
  expect(shiftMonth("2026-11", 0)).toBe("2026-11");
});

it("shades by focus minutes", () => {
  expect([0, 1, 59, 60, 119, 120, 239, 240, 600].map(readShade)).toEqual([0, 1, 1, 2, 2, 3, 3, 4, 4]);
});

it("keeps cell numbers short", () => {
  expect([0, 45, 60, 125].map(formatCompactMinutes)).toEqual(["0m", "45m", "1h00", "2h05"]);
});

it("reads a day page's headings, lists and lines, and skips the frontmatter", () => {
  const page = "---\ndate: 2026-11-14\nfocus_minutes: 140\n---\n\n# Saturday\n\n## Totals\n- Focus: 2h20\n- Phone: 10m\n\nNothing else.\n";
  expect(parseDayPage(page)).toEqual([
    { kind: "heading", level: 1, text: "Saturday" },
    { kind: "heading", level: 2, text: "Totals" },
    { kind: "list", items: ["Focus: 2h20", "Phone: 10m"] },
    { kind: "paragraph", text: "Nothing else." },
  ]);
  expect(parseDayPage("---\nno end")).toEqual([
    { kind: "paragraph", text: "---" },
    { kind: "paragraph", text: "no end" },
  ]);
});
