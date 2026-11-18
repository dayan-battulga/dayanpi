import { act, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "@/App";
import { answer, serveApi } from "@/test/fakeApi";
import { FakeEventSource } from "@/test/fakeStream";
import { OWNER, makeFocus, makeSeat, makeSnapshot } from "@/test/fixtures";

const ROOM = {
  seats: [
    makeSeat({ focus_seconds: 11538 }),
    makeSeat({ username: "sam", name: "Sam", state: "phone", seconds_in_state: 365, focus_seconds: 6480 }),
    makeSeat({ username: "alex", name: "Alex", state: "away", seconds_in_state: 760, focus_seconds: 7500 }),
  ],
};
const PROBLEM_SET = { current: "t1", open: [{ id: "t1", text: "Problem set 3", seconds: 2280, done_at: null }], done: [] };

// The page's visibility, which the tests flip; jsdom never hides a page by itself.
let visibility: DocumentVisibilityState = "visible";

function openSign() {
  serveApi({ "GET /api/me": answer({ user: OWNER }) });
  const shown = render(
    <MemoryRouter initialEntries={["/sign"]}>
      <App />
    </MemoryRouter>,
  );
  return shown;
}

function sendFocus(changes: Parameters<typeof makeFocus>[0]) {
  FakeEventSource.latest?.send({ ...makeSnapshot(makeFocus(changes)), room: ROOM });
}

function giveWakeLock(request: (type: string) => Promise<unknown>) {
  Object.defineProperty(navigator, "wakeLock", { value: { request }, configurable: true });
}

async function showPage(state: DocumentVisibilityState) {
  visibility = state;
  await act(async () => {
    document.dispatchEvent(new Event("visibilitychange"));
  });
}

beforeEach(() => {
  vi.stubGlobal("EventSource", FakeEventSource);
  visibility = "visible";
  vi.spyOn(document, "visibilityState", "get").mockImplementation(() => visibility);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  Reflect.deleteProperty(navigator, "wakeLock");
});

it("shows my state, its timer, my current to-do and the room's lamps", async () => {
  openSign();
  expect(await screen.findByRole("list", { name: "The room" })).toBeInTheDocument();
  sendFocus({ state: "working", seconds_in_state: 2538, todos: PROBLEM_SET });
  expect(await screen.findByText("Focused")).toBeInTheDocument();
  expect(screen.getByRole("timer")).toHaveAttribute("aria-label", expect.stringMatching(/^42:1[89]$/));
  expect(screen.getByText("Problem set 3")).toBeInTheDocument();
  expect(screen.getByText("7h 05m together")).toBeInTheDocument();
  expect(await screen.findByText(/^You/)).toBeInTheDocument();
  const lamps = within(screen.getByRole("list", { name: "The room" })).getAllByRole("listitem");
  expect(lamps.map((lamp) => lamp.textContent)).toEqual(["You, focused", "Sam, on the phone", "Alex, away", "Open"]);
  expect(document.querySelector(".sign")).toHaveAttribute("data-state", "working");
});

it("follows a new state, and shows no to-do when nothing is current", async () => {
  openSign();
  sendFocus({ state: "working", seconds_in_state: 2538, todos: PROBLEM_SET });
  expect(await screen.findByText("Problem set 3")).toBeInTheDocument();
  sendFocus({ state: "phone", seconds_in_state: 192, todos: { ...PROBLEM_SET, current: null } });
  expect(await screen.findByText("On your phone")).toBeInTheDocument();
  expect(screen.getByRole("timer")).toHaveAttribute("aria-label", expect.stringMatching(/^03:1[23]$/));
  expect(screen.queryByText("Problem set 3")).not.toBeInTheDocument();
  expect(document.querySelector(".sign")).toHaveAttribute("data-state", "phone");
});

it("keeps the screen awake, and asks again each time the page comes back into view", async () => {
  const release = vi.fn(async () => undefined);
  const request = vi.fn(async () => ({ release }));
  giveWakeLock(request);
  const shown = openSign();
  await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(1));
  expect(request).toHaveBeenCalledWith("screen");
  await showPage("hidden");
  expect(request).toHaveBeenCalledTimes(1); // the browser let go when it hid; there's nothing to ask for until it's back
  await showPage("visible");
  await vi.waitFor(() => expect(request).toHaveBeenCalledTimes(2));
  shown.unmount();
  expect(release).toHaveBeenCalled();
});

it("does without a wake lock quietly: a refusal, or none at all", async () => {
  const refused = vi.fn(async () => {
    throw new DOMException("not allowed", "NotAllowedError");
  });
  giveWakeLock(refused);
  const first = openSign();
  sendFocus({ state: "away", seconds_in_state: 520 });
  expect(await screen.findByText("Away")).toBeInTheDocument();
  await vi.waitFor(() => expect(refused).toHaveBeenCalled());
  await showPage("visible");
  expect(screen.getByText("Away")).toBeInTheDocument();
  first.unmount();

  Reflect.deleteProperty(navigator, "wakeLock");
  openSign();
  sendFocus({ state: "working", seconds_in_state: 60 });
  expect(await screen.findByText("Focused")).toBeInTheDocument();
});
