import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AppsCard, readPieceSeconds } from "@/components/apps/AppsCard";
import { ChartContainer, ChartTooltipContent } from "@/components/ui/chart";
import { buildAppRows } from "@/lib/apps";

const NOW = new Date(2026, 10, 15, 12, 0).getTime() / 1000;
const TODAY = {
  range: "today",
  apps: [
    { app: "Google Chrome", total_seconds: 5400, youtube_seconds: 1800, other_sites_seconds: 3600 },
    { app: "Xcode", total_seconds: 3000 },
    { app: "Visual Studio Code Insiders", total_seconds: 600 },
    { app: "Other apps", total_seconds: 120 },
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

function readTickLabels(container: HTMLElement): string[] {
  const labels = [...container.querySelectorAll(".recharts-yAxis-tick-labels .recharts-cartesian-axis-tick-value")].map((node) => node.textContent ?? "");
  return labels;
}

function readTotals(container: HTMLElement): string[] {
  const totals = [...container.querySelectorAll(".recharts-label-list text")].map((node) => node.textContent ?? "");
  return totals;
}

function countBars(container: HTMLElement, color: string): number {
  const count = container.querySelectorAll(`.recharts-bar-rectangle path[fill="${color}"]`).length;
  return count;
}

beforeEach(() => {
  // jsdom measures every element as 0x0 and recharts draws nothing into that; only its outer box needs a size.
  const measure = (element: Element) => {
    const size = element.classList.contains("recharts-responsive-container") ? { width: 480, height: 200 } : { width: 0, height: 0 };
    return { ...size, x: 0, y: 0, top: 0, left: 0, right: size.width, bottom: size.height, toJSON: () => ({}) };
  };
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    return measure(this);
  });
  requests = [];
  window.localStorage.clear();
  stubApps({ "/api/apps?range=today": TODAY, "/api/apps?range=week": WEEK });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("draws the bars in the API order and cuts long names", async () => {
  const { container } = render(<AppsCard now={NOW} />);
  await screen.findByText("Xcode");
  expect(readTickLabels(container)).toEqual(["Google Chrome", "Xcode", "Visual Studi…", "Other apps"]);
  expect(screen.getByRole("list")).toHaveTextContent("Visual Studio Code Insiders, 10m"); // the full name stays for screen readers
  expect(requests).toEqual(["/api/apps?range=today"]);
});

it("splits a browser into YouTube and Other sites, and every other app is one bar", async () => {
  const { container } = render(<AppsCard now={NOW} />);
  await screen.findByText("Xcode");
  expect(countBars(container, "var(--color-youtube)")).toBe(1);
  expect(countBars(container, "var(--color-sites)")).toBe(1);
  expect(countBars(container, "var(--color-solid)")).toBe(3);
  expect(screen.getByText("YouTube")).toBeInTheDocument(); // legend
  expect(screen.getByText("Other sites")).toBeInTheDocument();
  await screen.findByText("1h 30m");
  expect(readTotals(container)).toEqual(["1h 30m", "50m", "10m", "2m"]); // each bar's total at its right end
});

it("labels a browser used only on YouTube and names the chart", async () => {
  stubApps({ "/api/apps?range=today": { range: "today", apps: [{ app: "Safari", total_seconds: 600, youtube_seconds: 600, other_sites_seconds: 0 }, { app: "Xcode", total_seconds: 90 }] } });
  const { container } = render(<AppsCard now={NOW} />);
  await screen.findByText("Xcode");
  await screen.findByText("10m");
  expect(readTotals(container)).toEqual(["10m", "1m"]);
  expect(screen.getByRole("img", { name: "Time in front per Mac app" })).toBeInTheDocument();
});

it("shows the exact time of each piece in the tooltip", () => {
  const [browser, plain] = buildAppRows([TODAY.apps[0], TODAY.apps[1]], "minutes");
  const config = { youtube: { label: "YouTube" }, sites: { label: "Other sites" }, solid: { label: "Time" } };
  const tooltip = (row: typeof browser, keys: string[]) => (
    <ChartContainer config={config}>
      <ChartTooltipContent
        active
        label="x"
        payload={keys.map((key) => ({ dataKey: key, name: key, value: 1, payload: row as unknown as Record<string, unknown> }))}
        labelFormatter={(_label, payload) => String(payload[0]?.payload?.app)}
        formatter={(_value, _name, item) => `${readPieceSeconds(item.dataKey, row)}`}
      />
    </ChartContainer>
  );
  const { rerender } = render(tooltip(browser, ["youtube", "sites"]));
  expect(screen.getByText("Google Chrome")).toBeInTheDocument();
  expect(screen.getByText("YouTube").nextSibling).toHaveTextContent("1800");
  expect(screen.getByText("Other sites").nextSibling).toHaveTextContent("3600");
  rerender(tooltip(plain, ["solid"]));
  expect(screen.getByText("Time").nextSibling).toHaveTextContent("3000");
});

it("switches to this week, remembers it, and fetches the week", async () => {
  const user = userEvent.setup();
  render(<AppsCard now={NOW} />);
  expect(screen.getByRole("button", { name: "Today" })).toHaveAttribute("aria-pressed", "true");
  await screen.findByText("Xcode");
  await user.click(screen.getByRole("button", { name: "This week" }));
  expect(await screen.findByText("Slack")).toBeInTheDocument();
  expect(requests).toContain("/api/apps?range=week");
  expect(screen.getByRole("button", { name: "This week" })).toHaveAttribute("aria-pressed", "true");
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
  await user.click(screen.getByRole("button", { name: "This week" }));
  expect(await screen.findByText("Slack")).toBeInTheDocument();
});

it("says so quietly when there is nothing, and for the week too", async () => {
  stubApps({ "/api/apps?range=today": { range: "today", apps: [] }, "/api/apps?range=week": { range: "week", apps: [] } });
  const user = userEvent.setup();
  render(<AppsCard now={NOW} />);
  expect(await screen.findByText("Nothing from the Mac yet today")).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "This week" }));
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
