import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { toast } from "sonner";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "@/App";
import { PHONE_QUERY, WIDE_QUERY } from "@/hooks/useMediaQuery";
import type { FocusStatus, Priority, Todos } from "@/lib/types";
import { answer, serveApi, type Route } from "@/test/fakeApi";
import { FakeEventSource } from "@/test/fakeStream";
import { OWNER, makeFocus, makeSeat, makeSnapshot } from "@/test/fixtures";

vi.mock("@/lib/navigation", () => ({ loadPage: vi.fn() }));

const realMatchMedia = window.matchMedia;
const NOTES: Todos = {
  current: "t1",
  open: [
    { id: "t1", text: "Problem set 3", seconds: 2280, done_at: null, priority: "none" },
    { id: "t2", text: "Lab report outline", seconds: 0, done_at: null, priority: "medium" },
    { id: "t5", text: "Read chapter 8", seconds: 0, done_at: null }, // saved before priorities
    { id: "t6", text: "CS 571 project demo", seconds: 0, done_at: null, priority: "high" },
    { id: "t7", text: "Buy a gift", seconds: 0, done_at: null, priority: "low" },
    { id: "t9", text: "Email the TA", seconds: 0, done_at: null, priority: "high" },
  ],
  done: [],
};
const SAM = makeSeat({ username: "sam", name: "Sam", todos: { current: "Read chapter 7", current_seconds: 60, done: 0, total: 3 } });
const ONLY_HIGH: Record<Priority, boolean> = { high: true, medium: false, low: false, none: false };

function sizeWindow(query: string | null) {
  window.matchMedia = (asked: string) => ({ ...realMatchMedia(asked), matches: asked === query });
}

function openRoom(focus: Partial<FocusStatus> = {}, routes: Record<string, Route> = {}, path = "/") {
  const sent = serveApi({ "GET /api/me": answer({ user: OWNER }), "GET /api/focus": answer({ segments: [] }), ...routes });
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
  FakeEventSource.latest?.send({ ...makeSnapshot(makeFocus({ todos: NOTES, ...focus })), room: { seats: [makeSeat(), SAM] } });
  const user = userEvent.setup();
  return { sent, user };
}

const rowNames = (panel: HTMLElement) => within(within(panel).getByRole("list", { name: "Your to-dos" })).queryAllByRole("listitem").map((row) => row.querySelector(".notepad-text")?.textContent);

beforeEach(() => {
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.matchMedia = realMatchMedia;
  window.localStorage.clear();
  toast.dismiss();
});

it("pins your notepad to the right edge from 1280 px: what you're working on first, then high to none", async () => {
  sizeWindow(WIDE_QUERY);
  openRoom();
  const panel = await screen.findByRole("complementary", { name: "Notepad" });
  expect(document.querySelector(".frame-column")?.contains(panel)).toBe(false); // its own column, like the room sidebar
  expect(panel).toHaveClass("rail", "rail-notepad");
  expect(within(panel).getByText(/only you see this/)).toHaveTextContent("All to-dos · only you see this · change");
  expect(within(panel).getByRole("link", { name: "change" })).toHaveAttribute("href", "/settings");
  const current = panel.querySelector(".notepad-current") as HTMLElement;
  expect(current).toHaveTextContent("Problem set 3Working");
  expect(rowNames(panel)).toEqual(["CS 571 project demo", "Email the TA", "Lab report outline", "Buy a gift", "Read chapter 8"]);
  expect(within(panel).queryByText("Read chapter 7")).toBeNull(); // Sam's to-do stays on Sam's seat
  expect(screen.queryByRole("button", { name: "Notepad" })).toBeNull(); // no sheet button when it's pinned
});

it("says Paused on what you're working on while you're not focused", async () => {
  sizeWindow(WIDE_QUERY);
  openRoom({ state: "phone" });
  const panel = await screen.findByRole("complementary", { name: "Notepad" });
  expect(panel.querySelector(".notepad-current")).toHaveTextContent("Problem set 3Paused");
});

it("folds to a strip with a count, and remembers it", async () => {
  sizeWindow(WIDE_QUERY);
  const { user } = openRoom();
  await user.click(within(await screen.findByRole("complementary", { name: "Notepad" })).getByRole("button", { name: "Fold the notepad" }));
  const strip = screen.getByRole("complementary", { name: "Notepad" });
  expect(strip).toHaveClass("rail-collapsed");
  expect(within(strip).getByRole("button", { name: "Open the notepad: 6 to-dos" })).toHaveTextContent("6");
  expect(window.localStorage.getItem("dayanpi.notepad")).toBe("collapsed");

  cleanup();
  openRoom();
  expect(within(await screen.findByRole("complementary", { name: "Notepad" })).getByRole("button", { name: "Open the notepad: 6 to-dos" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Open the notepad" }));
  expect(within(screen.getByRole("complementary", { name: "Notepad" })).getByRole("heading", { name: "Notepad" })).toBeInTheDocument();
  expect(window.localStorage.getItem("dayanpi.notepad")).toBe("open");
});

it("shows only the priorities Settings → To-dos picks, and always what you're working on", async () => {
  sizeWindow(WIDE_QUERY);
  openRoom({ notepad: ONLY_HIGH });
  const panel = await screen.findByRole("complementary", { name: "Notepad" });
  expect(rowNames(panel)).toEqual(["CS 571 project demo", "Email the TA"]);
  expect(panel.querySelector(".notepad-current")).toHaveTextContent("Problem set 3"); // no priority, still first
  expect(within(panel).getByText(/only you see this/)).toHaveTextContent(/^High priority · only you see this/);
});

it("keeps a to-do you add from the notepad on it until you give it a priority", async () => {
  sizeWindow(WIDE_QUERY);
  const added = { id: "t10", text: "Quiz review", seconds: 0, done_at: null, priority: "none" as const };
  const { sent, user } = openRoom(
    { notepad: ONLY_HIGH },
    {
      "POST /api/todos": answer({ item: added, todos: { ...NOTES, open: [...NOTES.open, added] } }),
      "PATCH /api/todos/t10": answer({ todos: { ...NOTES, open: [...NOTES.open, { ...added, priority: "low" }] } }),
    },
  );
  const panel = await screen.findByRole("complementary", { name: "Notepad" });
  await user.type(within(panel).getByRole("textbox", { name: "New to-do" }), "Quiz review{Enter}");
  expect(sent.find((request) => request.method === "POST")?.body).toEqual({ text: "Quiz review" }); // no priority
  await waitFor(() => expect(rowNames(panel)).toEqual(["CS 571 project demo", "Email the TA", "Quiz review"]));
  expect(within(panel).getByText("New to-dos start with no priority. Pick one from its menu.")).toBeInTheDocument();

  await user.click(within(panel).getByRole("button", { name: "Priority of Quiz review: No priority" }));
  await user.click(screen.getByRole("menuitemradio", { name: "Low" }));
  await waitFor(() => expect(rowNames(panel)).toEqual(["CS 571 project demo", "Email the TA"])); // Low isn't shown
  expect(sent.find((request) => request.method === "PATCH")?.body).toEqual({ priority: "low" });
});

it("checks a to-do off the notepad", async () => {
  sizeWindow(WIDE_QUERY);
  const { sent, user } = openRoom({}, { "PATCH /api/todos/t6": answer({ todos: { ...NOTES, open: NOTES.open.filter((item) => item.id !== "t6") } }) });
  const panel = await screen.findByRole("complementary", { name: "Notepad" });
  await user.click(within(panel).getByRole("checkbox", { name: "Done: CS 571 project demo" }));
  expect(sent.find((request) => request.method === "PATCH")?.body).toEqual({ done: true });
  await waitFor(() => expect(rowNames(panel)).not.toContain("CS 571 project demo"));
});

it("opens the same notepad as a sheet below 1280 px", async () => {
  sizeWindow(null);
  const { user } = openRoom();
  expect(screen.queryByRole("complementary", { name: "Notepad" })).toBeNull();
  await user.click(await screen.findByRole("button", { name: "Notepad" }));
  const sheet = await screen.findByRole("dialog", { name: "Notepad" });
  expect(sheet).toHaveClass("notepad-sheet");
  expect(rowNames(sheet)).toEqual(["CS 571 project demo", "Email the TA", "Lab report outline", "Buy a gift", "Read chapter 8"]);
  await user.click(within(sheet).getByRole("button", { name: "Close" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

it("opens it from the bottom on a phone", async () => {
  sizeWindow(PHONE_QUERY);
  const { user } = openRoom();
  await user.click(await screen.findByRole("button", { name: "Notepad" }));
  expect(await screen.findByRole("dialog", { name: "Notepad" })).toHaveTextContent("Problem set 3");
});

it("is only on your own Room: the Desk keeps the room sidebar and every to-do", async () => {
  sizeWindow(WIDE_QUERY);
  openRoom({ notepad: ONLY_HIGH }, {}, "/me");
  expect(await screen.findByRole("complementary", { name: "In the room" })).toBeInTheDocument();
  expect(screen.queryByRole("complementary", { name: "Notepad" })).toBeNull();
  const desk = within(screen.getByRole("list", { name: "To-do" })).getAllByRole("listitem");
  expect(desk).toHaveLength(6); // the Desk shows everything, whatever the notepad picks
});
