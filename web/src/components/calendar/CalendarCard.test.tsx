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
// A newer page: a goal partway, ten apps with a browser's YouTube part, and one under a minute.
const BUSY_PAGE = [
  "---",
  "focus_minutes: 163",
  "goal_minutes: 240",
  "---",
  "",
  "## Totals",
  "- Focus: 2h43",
  "- Goal: 4h",
  "",
  "## Apps",
  "- Google Chrome: 1h41 (YouTube 22m)",
  "- Claude: 53m",
  "- Cursor: 51m",
  "- Docker: 8m",
  "- Finder: 4m",
  "- Postman: 3m",
  "- Messages: 2m",
  "- Calendar: 1m",
  "- Clock: 40s",
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
        "/api/days/2026-11-14": { day: "2026-11-14", today: false, markdown: PAGE },
        "/api/days/2026-11-13": {
          day: "2026-11-13",
          today: false,
          markdown: BUSY_PAGE,
          studied_with: [
            { username: "sam", name: "Sam", lamp: "pink", minutes: 130 },
            { username: "alex", name: "Alex", lamp: "teal", minutes: 45 },
          ],
        },
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
  const done = within(within(dialog).getByText("Done").nextElementSibling as HTMLElement).getAllByRole("listitem").map((row) => [...row.children].map((part) => part.textContent));
  expect(done).toEqual([
    ["Read: chapter 7", "1h 40m"],
    ["Email the TA", "10m"],
  ]);
  // A page from before the goal and the YouTube part still reads: rows, no goal box, nobody studied with.
  expect(readAppRows(dialog)).toEqual([
    ["Code", "2h 05m"],
    ["Google Chrome", "1h 10m"],
  ]);
  expect(dialog.querySelector(".day-goal, .app-bar-youtube, .day-more")).toBeNull();
  expect(within(dialog).queryByText("Studied with")).toBeNull();
  expect(within(dialog).getByText("Mac tracking was paused for 20m, so that time isn't counted.")).toBeInTheDocument();
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

function readAppRows(dialog: HTMLElement): string[][] {
  const rows = [...dialog.querySelectorAll(".day-apps li")].map((row) => [...row.querySelectorAll(".app-name, .app-time")].map((part) => part.textContent ?? ""));
  return rows;
}

it("lays out a day's goal, who you studied with, and the top five apps with their bars, the rest folded", async () => {
  const user = userEvent.setup();
  render(<CalendarCard todayFocusSeconds={0} now={NOW} />);
  await user.click(screen.getByRole("button", { name: "November 13" }));
  const dialog = await screen.findByRole("dialog", { name: "Friday, November 13" });
  const goal = await within(dialog).findByText("2h 43m of 4h");
  expect(goal.nextElementSibling).toHaveTextContent("1h 17m to go");

  const mates = within(within(dialog).getByText("Studied with").nextElementSibling as HTMLElement).getAllByRole("listitem");
  expect(mates.map((mate) => mate.textContent)).toEqual(["SSam 2h 10m", "AAlex 45m"]); // the overlap, not their total
  expect(mates.map((mate) => mate.getAttribute("data-lamp"))).toEqual(["pink", "teal"]);

  expect(readAppRows(dialog)).toEqual([
    ["Google Chrome", "1h 41m"],
    ["Claude", "53m"],
    ["Cursor", "51m"],
    ["Docker", "8m"],
    ["Finder", "4m"],
  ]);
  const bars = [...dialog.querySelectorAll<HTMLElement>(".day-apps .app-bar")].map((bar) => parseFloat(bar.style.width));
  expect(bars[0]).toBe(100);
  expect(bars[1]).toBeCloseTo((53 / 101) * 100);
  const youtube = dialog.querySelectorAll<HTMLElement>(".app-bar-youtube");
  expect(youtube).toHaveLength(1);
  expect(parseFloat(youtube[0].style.width)).toBeCloseTo((22 / 101) * 100, 1); // of Chrome's own bar

  const more = within(dialog).getByRole("button", { name: "+3 more" }); // Clock's 40 s is left out
  expect(more).toHaveAttribute("aria-expanded", "false");
  await user.click(more);
  expect(readAppRows(dialog).map(([name]) => name)).toEqual(["Google Chrome", "Claude", "Cursor", "Docker", "Finder", "Postman", "Messages", "Calendar"]);
  await user.click(within(dialog).getByRole("button", { name: "Show less", expanded: true }));
  await waitFor(() => expect(readAppRows(dialog)).toHaveLength(5));
  expect(within(dialog).getByRole("button", { name: "+3 more" })).toBeInTheDocument();
});

it("says a goal was reached", async () => {
  const user = userEvent.setup();
  vi.mocked(fetch).mockImplementation(async () => ({ ok: true, json: async () => ({ day: "2026-11-13", today: false, markdown: BUSY_PAGE.replace("focus_minutes: 163", "focus_minutes: 250") }) }) as Response);
  render(<CalendarCard todayFocusSeconds={0} now={NOW} />);
  await user.click(screen.getByRole("button", { name: "November 13" }));
  const dialog = await screen.findByRole("dialog", { name: "Friday, November 13" });
  expect((await within(dialog).findByText("Goal reached")).nextElementSibling).toHaveTextContent("4h 10m of 4h");
});
