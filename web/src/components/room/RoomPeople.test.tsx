import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation } from "react-router";
import { toast } from "sonner";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "@/App";
import { PHONE_QUERY, WIDE_QUERY } from "@/hooks/useMediaQuery";
import type { Seat, Spoken, User } from "@/lib/types";
import { answer, serveApi, type Route } from "@/test/fakeApi";
import { FakeEventSource } from "@/test/fakeStream";
import { MEMBER, OWNER, makeFocus, makeSeat, makeSnapshot } from "@/test/fixtures";

vi.mock("@/lib/navigation", () => ({ loadPage: vi.fn() }));

const realMatchMedia = window.matchMedia;
const ME = makeSeat();
// On the phone 6 minutes and taking nudges: the button shows.
const SAM = makeSeat({ username: "sam", name: "Sam", state: "phone", seconds_in_state: 365, shares: ["focus", "todos", "apps", "history"], app: "Chrome" });
const ALEX = makeSeat({ username: "alex", name: "Alex", state: "away", seconds_in_state: 760, shares: ["todos", "history"], focus_seconds: undefined });
const SAMS_DESK = { ...SAM, here_since: null, todo_list: { current: "a1", open: [{ id: "a1", text: "finish the report", seconds: 754, done_at: null }], done: [] }, apps: [{ app: "Chrome", total_seconds: 3120 }] };

function ShowPath() {
  return <output aria-label="Path">{useLocation().pathname}</output>;
}

function sizeWindow(query: string | null) {
  window.matchMedia = (asked: string) => ({ ...realMatchMedia(asked), matches: asked === query });
}

function openApp(path: string, seats: Seat[], options: { me?: User; focus?: object; routes?: Record<string, Route> } = {}) {
  const sent = serveApi({ "GET /api/me": answer({ user: options.me ?? OWNER }), "GET /api/focus": answer({ segments: [] }), "GET /api/people/sam": answer(SAMS_DESK), ...options.routes });
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
      <ShowPath />
    </MemoryRouter>,
  );
  FakeEventSource.latest?.send({ ...makeSnapshot(makeFocus(options.focus)), room: { seats } });
  const user = userEvent.setup();
  return { sent, user };
}

beforeEach(() => {
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
  window.matchMedia = realMatchMedia;
  window.localStorage.clear();
  toast.dismiss();
});

it("opens the quick peek from someone's seat, with their to-dos, apps, Nudge and their desk", async () => {
  const { user } = openApp("/", [ME, SAM, ALEX]);
  await user.click(await screen.findByRole("button", { name: "Peek at Sam" }));
  const peek = await screen.findByRole("dialog", { name: "Sam" });
  expect(within(peek).getByText("On the phone ·", { exact: false })).toHaveTextContent("On the phone · 06:05");
  expect(within(peek).getByText("Working on")).toBeInTheDocument();
  expect(await within(peek).findByText("To-do · 0 of 1 done")).toBeInTheDocument();
  expect(within(peek).getByText("Apps today")).toBeInTheDocument();
  expect(within(peek).getByRole("button", { name: "Nudge Sam" })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Peek at Dayan" })).toBeNull(); // not your own

  await user.click(within(peek).getByRole("link", { name: "Open Sam’s desk →" }));
  expect(await screen.findByRole("status", { name: "Path" })).toHaveTextContent("/people/sam");
});

it("says how long someone's been away instead of Nudge", async () => {
  const { user } = openApp("/", [ME, SAM, ALEX], { routes: { "GET /api/people/alex": answer({ ...ALEX, here_since: null }) } });
  await user.click(await screen.findByRole("button", { name: "Peek at Alex" }));
  const peek = await screen.findByRole("dialog", { name: "Alex" });
  expect(within(peek).getByText("Away for 12 minutes")).toBeInTheDocument();
  expect(within(peek).queryByRole("button", { name: /Nudge/ })).toBeNull();
});

it.each([
  ["on the phone under 5 minutes", { seconds_in_state: 299 }],
  ["working", { state: "working" as const }],
  ["with nudges off", { nudge: undefined }],
])("has no Nudge for someone %s", async (_, change) => {
  openApp("/", [ME, { ...SAM, ...change }, ALEX]);
  await screen.findByRole("button", { name: "Peek at Sam" });
  expect(screen.queryByRole("button", { name: /Nudge Sam/ })).toBeNull();
});

it("nudges from the seat, says so, and shows the wait right away", async () => {
  const { user, sent } = openApp("/", [ME, SAM, ALEX], { routes: { "POST /api/nudge": answer({ status: "ok", wait_s: 600 }) } });
  await user.click(await screen.findByRole("button", { name: "Nudge Sam" }));
  expect(sent.at(-1)).toMatchObject({ method: "POST", path: "/api/nudge", body: { username: "sam" } });
  expect(await screen.findByText("Nudged Sam")).toBeInTheDocument();
  expect(screen.getByText("just now")).toBeInTheDocument();
  const waiting = screen.getByRole("button", { name: "Nudge Sam again in 10m" });
  expect(waiting).toBeDisabled();
});

it("shows the 10 minutes since someone else's nudge, and the rings leaving the seat", async () => {
  openApp("/", [ME, { ...SAM, nudge: { wait_s: 420, age_s: 1 } }, ALEX]);
  expect(await screen.findByRole("button", { name: "Nudge Sam again in 7m" })).toBeDisabled();
  expect(screen.getByRole("article", { name: "Sam, on the phone" }).querySelectorAll(".seat-ripples span")).toHaveLength(2);
});

it("tells you when the Pi says it's too soon", async () => {
  const { user } = openApp("/", [ME, SAM, ALEX], { routes: { "POST /api/nudge": answer({ detail: "nudged a few minutes ago" }, 429, { "Retry-After": "300" }) } });
  await user.click(await screen.findByRole("button", { name: "Nudge Sam" }));
  expect(await screen.findByText("Sam was nudged a few minutes ago")).toBeInTheDocument();
});

it("puts a nudge you get in a toast, not the peace sign's pill", async () => {
  const spoken: Spoken = { text: "Dayan says put the phone down", at: Date.now() / 1000, age_s: 0.5, speaking: false, clip: false, kind: "nudge" };
  openApp("/me", [makeSeat({ username: "sam", name: "Sam" }), ME], { me: MEMBER, focus: { spoken } });
  expect(await screen.findByText("Dayan says put the phone down")).toBeInTheDocument();
  expect(document.querySelector(".peace-pill")).toBeNull();
});

it("shows who's here in the sidebar from 1280 px, and remembers it folded", async () => {
  sizeWindow(WIDE_QUERY);
  const { user } = openApp("/me", [ME, SAM, ALEX]);
  const rail = await screen.findByRole("complementary", { name: "In the room" });
  expect(within(rail).getAllByRole("link", { name: /^Open .*’s desk$/ }).map((link) => link.getAttribute("href"))).toEqual(["/people/sam", "/people/alex"]);
  expect(within(rail).getByText("1h 05m today")).toBeInTheDocument(); // Sam's; Alex doesn't share focus time
  expect(within(rail).getByText("12m · paused · Chrome")).toBeInTheDocument();
  expect(screen.queryByRole("navigation", { name: "The room" })).toBeNull();

  await user.click(within(rail).getByRole("button", { name: "Hide the room panel" }));
  expect(screen.getByRole("complementary", { name: "The room" })).toBeInTheDocument();
  expect(window.localStorage.getItem("dayanpi.rail")).toBe("collapsed");
});

it("shows who's here in the bottom bar below 1280 px, and no sidebar", async () => {
  sizeWindow(null);
  openApp("/settings", [ME, SAM]);
  const bar = await screen.findByRole("navigation", { name: "The room" });
  expect(within(bar).getByRole("link", { name: "Open Sam’s desk" })).toHaveTextContent("SSam06:05finish the report· Chrome");
  expect(screen.queryByRole("complementary")).toBeNull();
});

it("leaves the bottom bar off on a phone, where the dock is", async () => {
  sizeWindow(PHONE_QUERY);
  openApp("/me", [ME, SAM]);
  await screen.findByRole("navigation", { name: "Pages" });
  expect(screen.queryByRole("navigation", { name: "The room" })).toBeNull();
});

it("leaves the bottom bar off when nobody else is here", async () => {
  sizeWindow(null);
  openApp("/me", [ME, { ...SAM, here: false, state: "offline", seconds_in_state: null }]);
  await screen.findByRole("heading", { level: 1 });
  await waitFor(() => expect(screen.queryByRole("navigation", { name: "The room" })).toBeNull());
});

// jsdom has no object URLs; each blob gets a name so the test can tell frames apart and see them freed.
function stubObjectUrls() {
  let made = 0;
  const revoked: string[] = [];
  vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => `blob:frame-${++made}`, revokeObjectURL: (url: string) => revoked.push(url) }));
  return revoked;
}

it("shows a seat's picture, fading each new frame in over the last, and the initial again without one", async () => {
  const revoked = stubObjectUrls();
  const pictureRoutes = {
    "GET /api/people/sam/picture?at=1": answer("jpeg one"),
    "GET /api/people/sam/picture?at=2": answer("jpeg two"),
    "GET /api/people/sam/picture?at=3": answer("jpeg three"),
  };
  openApp("/", [ME, { ...SAM, picture: { at: 1 } }, ALEX], { routes: pictureRoutes });
  const sam = await screen.findByRole("article", { name: "Sam, on the phone" });
  const frames = () => Array.from(sam.querySelectorAll(".seat-picture-frame"), (frame) => frame.getAttribute("src"));
  await waitFor(() => expect(frames()).toEqual(["blob:frame-1"]));

  FakeEventSource.latest?.send({ ...makeSnapshot(), room: { seats: [ME, { ...SAM, picture: { at: 2 } }, ALEX] } });
  await waitFor(() => expect(frames()).toEqual(["blob:frame-1", "blob:frame-2"])); // the new one fades in on top
  FakeEventSource.latest?.send({ ...makeSnapshot(), room: { seats: [ME, { ...SAM, picture: { at: 3 } }, ALEX] } });
  await waitFor(() => expect(frames()).toEqual(["blob:frame-2", "blob:frame-3"]));
  expect(revoked).toEqual(["blob:frame-1"]);

  FakeEventSource.latest?.send({ ...makeSnapshot(), room: { seats: [ME, { ...SAM, picture: null }, ALEX] } }); // hid it, or walked away
  await waitFor(() => expect(sam.querySelector(".seat-picture")).toBeNull());
  expect(revoked).toEqual(["blob:frame-1", "blob:frame-2", "blob:frame-3"]);
  expect(within(sam).getByText("S")).toHaveClass("seat-initial");
});

it("hides and shows your video from your own seat, the same switch as Settings → Sharing → Video", async () => {
  const sharing = { focus: true, todos: true, history: true, apps: false, sites: false, video: true, nudges: true };
  const { user, sent } = openApp("/", [ME, SAM], {
    focus: { sharing },
    routes: { "POST /api/sharing": answer({ sharing: { ...sharing, video: false }, seat: { ...ME, picture: undefined } }) },
  });
  const hide = await screen.findByRole("button", { name: "Hide my video" });
  expect(hide).toHaveAttribute("aria-pressed", "true");
  expect(within(screen.getByRole("article", { name: "Sam, on the phone" })).queryByRole("button", { name: /my video/ })).toBeNull();

  await user.click(hide);

  expect(sent.at(-1)).toMatchObject({ method: "POST", path: "/api/sharing", body: { video: false } });
  expect(screen.getByRole("button", { name: "Show my video" })).toHaveAttribute("aria-pressed", "false");
});

// ----- hiding an offline seat -----

const AWAY_FOR_DAYS = makeSeat({ username: "alex", name: "Alex", here: false, state: "offline", seconds_in_state: null });
const roomSeats = () => within(screen.getByRole("region", { name: "Seats" })).getAllByRole("article").map((seat) => seat.getAttribute("aria-label"));

it("hides an offline seat for everyone with its ×, and Undo brings it back", async () => {
  const routes = { "POST /api/room/hide": answer({ username: "alex", hidden: true }), "POST /api/room/show": answer({ username: "alex", hidden: false }) };
  const { user, sent } = openApp("/", [ME, SAM, AWAY_FOR_DAYS], { routes });
  await user.click(await screen.findByRole("button", { name: "Hide Alex’s seat" }));
  expect(screen.queryByRole("button", { name: "Hide Sam’s seat" })).toBeNull(); // here
  expect(screen.queryByRole("button", { name: "Hide Dayan’s seat" })).toBeNull(); // yours

  expect(sent.at(-1)).toMatchObject({ method: "POST", path: "/api/room/hide", body: { username: "alex" } });
  expect(roomSeats()).toEqual(["Dayan, you", "Sam, on the phone", "Open seat"]); // Alex's place isn't an open seat
  expect(await screen.findByText("Hid Alex’s seat")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: "Undo" })); // jsdom has no setPointerCapture for Sonner's pointerdown
  await waitFor(() => expect(sent.at(-1)?.path).toBe("/api/room/show"));
  expect(sent.at(-1)).toMatchObject({ method: "POST", path: "/api/room/show", body: { username: "alex" } });
  expect(roomSeats()).toEqual(["Dayan, you", "Sam, on the phone", "Alex, offline", "Open seat"]);
});

it("says so and keeps the seat when the Pi turns the hide down", async () => {
  const { user } = openApp("/", [ME, SAM, AWAY_FOR_DAYS], { routes: { "POST /api/room/hide": answer({ detail: "they're here right now" }, 409) } });
  await user.click(await screen.findByRole("button", { name: "Hide Alex’s seat" }));
  expect(await screen.findByText("Couldn’t hide Alex’s seat")).toBeInTheDocument();
  expect(roomSeats()).toContain("Alex, offline");
});

it("leaves a hidden seat out of the room, the sidebar and the bottom bar until they're here, but never your own", async () => {
  sizeWindow(WIDE_QUERY);
  openApp("/me", [{ ...ME, hidden: true }, SAM, { ...AWAY_FOR_DAYS, hidden: true }]);
  const rail = await screen.findByRole("complementary", { name: "In the room" });
  expect(within(rail).getAllByRole("link", { name: /^Open .*’s desk$/ }).map((link) => link.getAttribute("href"))).toEqual(["/people/sam"]);

  cleanup();
  sizeWindow(null);
  openApp("/settings", [ME, { ...AWAY_FOR_DAYS, hidden: true }]);
  await screen.findByRole("heading", { level: 1 });
  expect(screen.queryByRole("navigation", { name: "The room" })).toBeNull();

  cleanup();
  openApp("/", [{ ...ME, hidden: true }, { ...AWAY_FOR_DAYS, hidden: true }]);
  await screen.findByRole("region", { name: "Seats" });
  expect(roomSeats()).toEqual(["Dayan, you", "Open seat", "Open seat"]); // still two accounts, so not "Just you"

  FakeEventSource.latest?.send({ ...makeSnapshot(), room: { seats: [ME, { ...AWAY_FOR_DAYS, here: true, state: "unknown", seconds_in_state: 3 }] } });
  expect(await screen.findByRole("article", { name: "Alex, here" })).toBeInTheDocument();
});
