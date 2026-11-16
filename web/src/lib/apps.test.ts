import { expect, it } from "vitest";
import { buildAppRows, chooseTimeUnit, formatAxisTick, shortenAppName } from "@/lib/apps";

it("switches the axis to hours only once the longest bar passes 2 h", () => {
  expect(chooseTimeUnit([])).toBe("minutes");
  expect(chooseTimeUnit([{ app: "Xcode", total_seconds: 7200 }])).toBe("minutes");
  expect(chooseTimeUnit([{ app: "Xcode", total_seconds: 1800 }, { app: "Slack", total_seconds: 7230 }])).toBe("hours");
});

it("labels ticks in the axis unit", () => {
  expect(formatAxisTick(30, "minutes")).toBe("30m");
  expect(formatAxisTick(1.5, "hours")).toBe("1.5h");
  expect(formatAxisTick(2, "hours")).toBe("2h");
});

it("cuts long names with an ellipsis and keeps short ones", () => {
  expect(shortenAppName("Xcode")).toBe("Xcode");
  expect(shortenAppName("Visual Studio Code Insiders")).toBe("Visual Studi…");
});

it("splits a browser into two pieces and keeps the API order", () => {
  const rows = buildAppRows(
    [
      { app: "Chrome", total_seconds: 5400, youtube_seconds: 1800, other_sites_seconds: 3600 },
      { app: "Xcode", total_seconds: 600 },
    ],
    "minutes",
  );
  expect(rows.map((row) => row.app)).toEqual(["Chrome", "Xcode"]);
  expect(rows[0]).toMatchObject({ isBrowser: true, youtube: 30, sites: 60, solid: null, totalSeconds: 5400 });
  expect(rows[1]).toMatchObject({ isBrowser: false, youtube: null, sites: null, solid: 10 });
});
