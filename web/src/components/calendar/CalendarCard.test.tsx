import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CalendarCard } from "@/components/calendar/CalendarCard";

const NOW = new Date(2026, 10, 15, 12, 0).getTime() / 1000; // Sunday, Nov 15 2026, noon
const PAGE = [
  "---",
  "focus_minutes: 140",
  "---",
  "",
  "# Saturday, November 14, 2026",
  "",
  "## Totals",
  "- Focus: 2h20",
  "- Phone: 12m",
  "- Away: 1h05",
  "- Pickups: 1",
  "",
  "## To-dos done",
  "- Read: chapter 7 (1h40)",
  "- Email the TA (10m)",
  "",
  "## Apps",
  "Mac tracking was paused for 20m, so that time isn't counted.",
  "- Code: 2h05",
  "- Google Chrome: 1h10",
  "",
].join("\n");
const TODAY_PAGE = "---\n---\n\n# Sunday, November 15, 2026\n\n## Totals\n- Focus: 1h05\n\n## To-dos done\n- None\n\n## Apps\n- None\n";

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
        "/api/days/2026-11-14": { day: "2026-11-14", today: false, markdown: PAGE, others: [{ name: "Sam", focus_minutes: 108 }, { name: "Alex", focus_minutes: 125 }] },
        "/api/days/2026-11-15": { day: "2026-11-15", today: true, markdown: TODAY_PAGE },
      };
      const reply = replies[path];
      return { ok: reply != null, json: async () => reply };
    }),
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

it("names the month with its total, shades each day, and outlines today with the live number", async () => {
  render(<CalendarCard todayFocusSeconds={3900} now={NOW} />);
  const past = await screen.findByRole("button", { name: "November 14, 2h 20m focused" });
  expect(past).toHaveAttribute("data-shade", "3");
  expect(past).not.toHaveAttribute("data-today");
  const today = screen.getByRole("button", { name: "November 15, 1h 5m focused" }); // the stream's 65 min, not the page's 50
  expect(today).toHaveAttribute("data-today");
  expect(today).toHaveAttribute("data-shade", "2");
  expect(screen.getByRole("button", { name: "November 3" })).toHaveAttribute("data-shade", "0");
  expect(screen.getByRole("button", { name: "November 20" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: /December/ })).toBeNull(); // the next month's days are only shown
  expect(screen.getByRole("heading", { name: "November" })).toBeInTheDocument();
  expect(screen.getByText("3h 25m focused")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Next month" })).toBeDisabled();
});

it("goes back a month and forward again", async () => {
  const user = userEvent.setup();
  render(<CalendarCard todayFocusSeconds={0} now={NOW} />);
  await user.click(screen.getByRole("button", { name: "Previous month" }));
  expect(await screen.findByRole("button", { name: "October 30, 30m focused" })).toBeEnabled();
  expect(screen.getByRole("heading", { name: "October" })).toBeInTheDocument();
  expect(screen.getByText("30m focused")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Next month" })).toBeEnabled();
  await waitFor(() => expect(requests).toContain("/api/days?month=2026-10"));
  await user.click(screen.getByRole("button", { name: "Next month" }));
  expect(await screen.findByRole("button", { name: "November 14, 2h 20m focused" })).toBeEnabled();
  await act(async () => {});
});

it("opens a day's page in a dialog and closes it with Esc, back on the day", async () => {
  const user = userEvent.setup();
  render(<CalendarCard todayFocusSeconds={0} now={NOW} />);
  const day = await screen.findByRole("button", { name: "November 14, 2h 20m focused" });
  await user.click(day);
  const dialog = await screen.findByRole("dialog", { name: "Saturday, November 14" });
  expect((await within(dialog).findAllByText("focused", { exact: false }))[0]).toHaveTextContent("2h 20m focused · 12m phone · 1h 05m away");
  const done = within(dialog).getAllByRole("listitem").map((row) => [...row.children].map((part) => part.textContent));
  expect(done).toEqual([
    ["Read: chapter 7", "1h 40m"],
    ["Email the TA", "10m"],
  ]);
  expect(within(dialog).getByText("Apps").nextElementSibling).toHaveTextContent("Code 2h 05m · Google Chrome 1h 10m");
  expect(within(dialog).getByText("Mac tracking was paused for 20m, so that time isn't counted.")).toBeInTheDocument();
  expect(within(dialog).getByText(/^Also focused/)).toHaveTextContent("Also focused: Sam 1h 48m · Alex 2h 5m"); // the group calendar
  expect(day).toHaveAttribute("data-picked");

  await user.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  await waitFor(() => expect(day).toHaveFocus());
  expect(day).not.toHaveAttribute("data-picked");
});

it("closes on the scrim and on the ×", async () => {
  const user = userEvent.setup();
  render(<CalendarCard todayFocusSeconds={0} now={NOW} />);
  await user.click(await screen.findByRole("button", { name: "November 14, 2h 20m focused" }));
  await screen.findByRole("dialog");
  await user.click(document.querySelector(".scrim") as HTMLElement);
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

  await user.click(screen.getByRole("button", { name: "November 14, 2h 20m focused" }));
  await user.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Close" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

it("says when a day has no page", async () => {
  const user = userEvent.setup();
  render(<CalendarCard todayFocusSeconds={0} now={NOW} />);
  await user.click(screen.getByRole("button", { name: "November 3" }));
  const dialog = await screen.findByRole("dialog", { name: "Tuesday, November 3" });
  expect(await within(dialog).findByText("No page for this day.")).toBeInTheDocument();
  expect(requests).toContain("/api/days/2026-11-03");
});

it("opens today, built live, and refreshes it every minute while it's open", async () => {
  const user = userEvent.setup();
  const { rerender } = render(<CalendarCard todayFocusSeconds={3900} now={NOW} />);
  await user.click(await screen.findByRole("button", { name: "November 15, 1h 5m focused" }));
  const dialog = await screen.findByRole("dialog", { name: "Sunday, November 15" });
  expect(await within(dialog).findByText("focused", { exact: false })).toHaveTextContent("1h 05m focused");
  expect(within(dialog).queryByText("Done")).toBeNull(); // "- None" lists leave their section out
  expect(within(dialog).queryByText("Apps")).toBeNull();
  rerender(<CalendarCard todayFocusSeconds={3900} now={NOW + 61} />);
  await waitFor(() => expect(requests.filter((path) => path === "/api/days/2026-11-15")).toHaveLength(2));
});
