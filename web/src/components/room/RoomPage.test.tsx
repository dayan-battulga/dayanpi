import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "@/App";
import type { FocusStatus, Seat, User } from "@/lib/types";
import { answer, serveApi } from "@/test/fakeApi";
import { FakeEventSource } from "@/test/fakeStream";
import { MEMBER, OWNER, makeFocus, makeSeat, makeSnapshot } from "@/test/fixtures";

vi.mock("@/lib/navigation", () => ({ loadPage: vi.fn() }));

const ME = makeSeat({ focus_seconds: 11538, app: "Code" });
const SAM = makeSeat({ username: "sam", name: "Sam", state: "phone", seconds_in_state: 365, focus_seconds: 6480, todos: { current: "Read chapter 7", current_seconds: 1440, done: 1, total: 4 }, app: "Chrome" });
// Alex shares nothing but the status, which always shows: no focus time, no to-dos, no apps.
const ALEX: Seat = { username: "alex", name: "Alex", here: true, state: "away", seconds_in_state: 760, shares: [], hidden: false, lamp: "teal" };

function ShowPath() {
  return <output aria-label="Path">{useLocation().pathname}</output>;
}

function openRoom(me: User, seats: Seat[], path = "/", focus: Partial<FocusStatus> = {}) {
  serveApi({ "GET /api/me": answer({ user: me }), "GET /api/tokens": answer({ tokens: [] }), "GET /api/invites": answer({ invites: [] }), "GET /api/accounts": answer({ accounts: [] }) });
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
      <ShowPath />
    </MemoryRouter>,
  );
  FakeEventSource.latest?.send({ ...makeSnapshot(makeFocus(focus)), room: { seats } });
  const user = userEvent.setup();
  return user;
}

const seatNames = () => within(screen.getByRole("region", { name: "Seats" })).getAllByRole("article").map((seat) => seat.getAttribute("aria-label"));

beforeEach(() => {
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

it("is what / shows, with the Room tab current", async () => {
  openRoom(OWNER, [ME, SAM, ALEX]);
  expect(await screen.findByRole("region", { name: "Seats" })).toBeInTheDocument();
  expect(screen.getByRole("status", { name: "Path" })).toHaveTextContent(/^\/$/);
  const tabs = within(screen.getByRole("navigation", { name: "Pages" }));
  expect(await tabs.findByRole("link", { name: "Pi" })).toBeInTheDocument();
  expect(tabs.getAllByRole("link").map((link) => link.textContent)).toEqual(["Room", "Desk", "Pi"]);
  expect(tabs.getByRole("link", { name: "Room" })).toHaveAttribute("aria-current", "page");
});

it("sends an unknown address to the room", async () => {
  openRoom(OWNER, [ME], "/nowhere");
  await waitFor(() => expect(screen.getByRole("status", { name: "Path" })).toHaveTextContent(/^\/$/));
});

it("adds up the focus of everyone here who shares it, and says who's here", async () => {
  openRoom(OWNER, [SAM, ALEX, ME]);
  expect(await screen.findByRole("heading", { level: 1 })).toHaveTextContent("5h 00m"); // Alex keeps theirs private
  expect(screen.getByText("3 here · focused together today")).toBeInTheDocument();
  expect(screen.getByText("Here now: Dayan, Sam, and Alex")).toBeInTheDocument();
  expect(Array.from(document.querySelectorAll(".here-face"), (face) => [face.textContent, face.getAttribute("data-state")])).toEqual([
    ["D", "working"],
    ["S", "phone"],
    ["A", "away"],
  ]);
});

it("hints to keep your camera on after the caption while your desk tracks with this browser's camera", async () => {
  openRoom(MEMBER, [makeSeat({ username: "sam", name: "Sam" })], "/", { camera_source: "browser" });
  const caption = await screen.findByText(/^focused today/);
  expect(caption).toHaveTextContent(/^focused today · keep your camera on to count your focus$/);
  expect(within(caption).getByText("· keep your camera on to count your focus")).toHaveClass("room-hint"); // its own, quieter span
});

it("puts the hint after the together caption", async () => {
  openRoom(OWNER, [SAM, ALEX, ME], "/", { camera_source: "browser" });
  expect(await screen.findByText(/^3 here/)).toHaveTextContent(/^3 here · focused together today · keep your camera on to count your focus$/);
});

it("leaves the hint out while the Pi's cameras track your desk", async () => {
  openRoom(OWNER, [ME], "/", { camera_source: "pi", picture_source: "browser" });
  expect(await screen.findByText("focused today")).toBeInTheDocument();
  expect(document.querySelector(".room-hint")).toBeNull();
});

it("draws each seat with only what that person shares, yours first and called You", async () => {
  openRoom(OWNER, [SAM, ALEX, ME]);
  await screen.findByRole("region", { name: "Seats" });
  expect(seatNames()).toEqual(["Dayan, you", "Sam, on the phone", "Alex, away", "Open seat"]);

  const mine = within(screen.getByRole("article", { name: "Dayan, you" }));
  expect(mine.getByText("You")).toBeInTheDocument();
  expect(mine.getByText("3h 12m")).toHaveClass("seat-chip");
  expect(mine.getByText("finish the report")).toBeInTheDocument();
  expect(mine.getByText("· Code")).toHaveClass("seat-app");
  expect(mine.getByText("1 of 4 to-dos done")).toBeInTheDocument();

  const sam = within(screen.getByRole("article", { name: "Sam, on the phone" }));
  expect(sam.getByText("06:05")).toHaveClass("seat-timer");
  // On the phone, so the to-do isn't counting: "· paused" goes with the app, in its dim color, like SeatsInfo's.
  expect(sam.getByText("Read chapter 7").closest(".seat-line")).toHaveTextContent(/^Read chapter 7 · paused · Chrome$/);
  expect(sam.getByText("· paused")).toHaveClass("seat-paused");

  const alex = screen.getByRole("article", { name: "Alex, away" });
  expect(alex.querySelector(".seat-chip, .seat-line, .seat-bar")).toBeNull();
  expect(within(alex).getByText("A")).toHaveClass("seat-initial");
  expect(alex).toHaveAttribute("data-state", "away");
});

it("shows someone who isn't here as offline, without a timer", async () => {
  openRoom(OWNER, [ME, { ...ALEX, here: false, state: "offline", seconds_in_state: null }]);
  const alex = await screen.findByRole("article", { name: "Alex, offline" });
  expect(within(alex).getByText("offline")).toHaveClass("seat-timer");
  expect(screen.getByText("focused today")).toBeInTheDocument(); // just you here
});

it("gives the owner Invite on each open seat, which opens Settings → Room and invites", async () => {
  const user = openRoom(OWNER, [ME, SAM]);
  const open = await screen.findAllByRole("article", { name: "Open seat" });
  expect(open).toHaveLength(2);
  await user.click(within(open[0]).getByRole("link", { name: "Invite" }));
  expect(await screen.findByRole("region", { name: "Room and invites" })).toBeInTheDocument();
  expect(screen.getByRole("status", { name: "Path" })).toHaveTextContent("/settings");
});

it("leaves a member's open seats empty, since only the owner can invite", async () => {
  openRoom(MEMBER, [ME, { ...SAM, state: "working" }]);
  const open = await screen.findAllByRole("article", { name: "Open seat" });
  expect(open.map((seat) => seat.textContent)).toEqual(["", ""]);
  expect(seatNames()[0]).toBe("Sam, you");
});

it("says it's just you when nobody else has joined", async () => {
  openRoom(OWNER, [ME]);
  const alone = await screen.findByRole("article", { name: "Nobody else here" });
  expect(within(alone).getByText("Just you for now")).toBeInTheDocument();
  expect(within(alone).getByRole("link", { name: "Invite someone" })).toHaveAttribute("href", "/settings");
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("3h 12m");
  expect(screen.getByText("focused today")).toBeInTheDocument();
  expect(screen.queryByRole("article", { name: "Open seat" })).toBeNull();
});
