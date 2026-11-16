import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CalendarCard } from "@/components/calendar/CalendarCard";

const NOW = new Date(2026, 10, 15, 12, 0).getTime() / 1000; // Sunday, Nov 15 2026, noon
const PAGE = "---\nfocus_minutes: 140\n---\n\n# Saturday, November 14, 2026\n\n## Totals\n- Focus: 2h20\n- Pickups: 1\n";

let requests: string[] = [];

beforeEach(() => {
  requests = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => {
      requests.push(path);
      const replies: Record<string, object> = {
        "/api/days?month=2026-11": { month: "2026-11", today: "2026-11-15", days: { "2026-11-14": { focus_minutes: 140 }, "2026-11-15": { focus_minutes: 50 } } },
        "/api/days?month=2026-10": { month: "2026-10", today: "2026-11-15", days: { "2026-10-30": { focus_minutes: 30 } } },
        "/api/days/2026-11-14": { day: "2026-11-14", today: false, markdown: PAGE },
      };
      const reply = replies[path];
      return { ok: reply != null, json: async () => reply };
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

it("shows each day's minutes, shaded, with today live", async () => {
  render(<CalendarCard todayFocusSeconds={3900} now={NOW} />);
  const past = await screen.findByRole("button", { name: "2026-11-14, 2h20 focused" });
  expect(past).toHaveClass("bg-work/40");
  expect(screen.getByRole("button", { name: "2026-11-15, 1h05 focused" })).toHaveClass("ring-1"); // the stream's 65 min, not the page's 50
  expect(screen.getByRole("button", { name: "2026-11-20" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Next month" })).toBeDisabled();
  expect(screen.getByText("3h25 focused")).toBeInTheDocument();
});

it("opens a day's page and says when there isn't one", async () => {
  const user = userEvent.setup();
  render(<CalendarCard todayFocusSeconds={0} now={NOW} />);
  await user.click(await screen.findByRole("button", { name: "2026-11-14, 2h20 focused" }));
  expect(await screen.findByRole("heading", { name: "Saturday, November 14, 2026" })).toBeInTheDocument();
  expect(screen.getByText("Focus: 2h20")).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "2026-11-03" }));
  expect(await screen.findByText("No page for this day.")).toBeInTheDocument();
  expect(requests).toContain("/api/days/2026-11-03");
});

it("goes back a month", async () => {
  const user = userEvent.setup();
  render(<CalendarCard todayFocusSeconds={0} now={NOW} />);
  await user.click(screen.getByRole("button", { name: "Previous month" }));
  expect(await screen.findByRole("button", { name: "2026-10-30, 30m focused" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Next month" })).toBeEnabled();
  await waitFor(() => expect(requests).toContain("/api/days?month=2026-10"));
  await act(async () => {});
});
