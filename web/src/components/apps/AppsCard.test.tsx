import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AppsCard } from "@/components/apps/AppsCard";

const NOW = new Date(2026, 10, 15, 12, 0).getTime() / 1000;
const TODAY = {
  range: "today",
  apps: [
    { app: "Xcode", total_seconds: 6000 },
    { app: "Google Chrome", total_seconds: 3000, youtube_seconds: 600, other_sites_seconds: 2400 },
    { app: "Visual Studio Code Insiders", total_seconds: 600 },
    { app: "Other apps", total_seconds: 1200 },
  ],
};
const WEEK = { range: "week", apps: [{ app: "Slack", total_seconds: 9000 }] };

let requests: string[] = [];

function stubApps(replies: Record<string, object | null>) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => {
      requests.push(path);
      const reply = replies[path] ?? null;
      return { ok: reply != null, json: async () => reply };
    }),
  );
}

function readRows(container: HTMLElement) {
  const rows = [...container.querySelectorAll(".app-list li")].map((row) => ({
    name: row.querySelector(".app-name")?.textContent,
    time: row.querySelector(".app-time")?.textContent,
    bar: (row.querySelector(".app-bar") as HTMLElement).style.width,
    youtube: (row.querySelector(".app-bar-youtube") as HTMLElement | null)?.style.width ?? null,
  }));
  return rows;
}

beforeEach(() => {
  requests = [];
  window.localStorage.clear();
  stubApps({ "/api/apps?range=today": TODAY, "/api/apps?range=week": WEEK });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("keeps the API's order with Other apps last, each bar its share of the longest", async () => {
  const { container } = render(<AppsCard now={NOW} />);
  await screen.findByText("Xcode");
  expect(readRows(container)).toEqual([
    { name: "Xcode", time: "1h 40m", bar: "100%", youtube: null },
    { name: "Google Chrome", time: "50m · 10m YouTube", bar: "50%", youtube: "20%" },
    { name: "Visual Studio Code Insiders", time: "10m", bar: "10%", youtube: null }, // CSS cuts a long name, the text stays whole
    { name: "Other apps", time: "20m", bar: "20%", youtube: null },
  ]);
  expect(screen.getByText("· 10m YouTube")).toHaveClass("app-youtube");
  expect(requests).toEqual(["/api/apps?range=today"]);
});

it("scales to the biggest row even when that's Other apps, and leaves out a browser's zero YouTube", async () => {
  stubApps({ "/api/apps?range=today": { range: "today", apps: [{ app: "Safari", total_seconds: 600, youtube_seconds: 0, other_sites_seconds: 600 }, { app: "Other apps", total_seconds: 1200 }] } });
  const { container } = render(<AppsCard now={NOW} />);
  await screen.findByText("Safari");
  expect(readRows(container)).toEqual([
    { name: "Safari", time: "10m", bar: "50%", youtube: null },
    { name: "Other apps", time: "20m", bar: "100%", youtube: null },
  ]);
});

it("switches to the week, remembers it, and fetches the week", async () => {
  const user = userEvent.setup();
  render(<AppsCard now={NOW} />);
  expect(screen.getByRole("button", { name: "Today" })).toHaveAttribute("aria-pressed", "true");
  await screen.findByText("Xcode");
  await user.click(screen.getByRole("button", { name: "Week" }));
  expect(await screen.findByText("Slack")).toBeInTheDocument();
  expect(screen.queryByText("Xcode")).toBeNull();
  expect(requests).toContain("/api/apps?range=week");
  expect(screen.getByRole("button", { name: "Week" })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: "Today" })).toHaveAttribute("aria-pressed", "false");
  expect(window.localStorage.getItem("dayanpi.apps-range")).toBe("week");
});

it("starts on the saved choice", async () => {
  window.localStorage.setItem("dayanpi.apps-range", "week");
  render(<AppsCard now={NOW} />);
  expect(await screen.findByText("Slack")).toBeInTheDocument();
  expect(requests).toEqual(["/api/apps?range=week"]);
});

it("still toggles when localStorage throws", async () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("blocked");
  });
  const user = userEvent.setup();
  render(<AppsCard now={NOW} />);
  await screen.findByText("Xcode");
  await user.click(screen.getByRole("button", { name: "Week" }));
  expect(await screen.findByText("Slack")).toBeInTheDocument();
});

it("says so quietly when there is nothing, and for the week too", async () => {
  stubApps({ "/api/apps?range=today": { range: "today", apps: [] }, "/api/apps?range=week": { range: "week", apps: [] } });
  const user = userEvent.setup();
  render(<AppsCard now={NOW} />);
  expect(await screen.findByText("Nothing from the Mac yet today")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Week" }));
  expect(await screen.findByText("Nothing from the Mac yet this week")).toBeInTheDocument();
});

it("shows the empty state when the fetch fails", async () => {
  stubApps({});
  render(<AppsCard now={NOW} />);
  expect(await screen.findByText("Nothing from the Mac yet today")).toBeInTheDocument();
});

it("refetches every minute", async () => {
  const { rerender } = render(<AppsCard now={NOW} />);
  await screen.findByText("Xcode");
  rerender(<AppsCard now={NOW + 30} />);
  rerender(<AppsCard now={NOW + 61} />);
  await waitFor(() => expect(requests.length).toBe(2));
});
