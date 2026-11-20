import type { NumberFlowElement } from "@number-flow/react";
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { toast } from "sonner";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "@/App";
import type { FocusStatus, Segment, User } from "@/lib/types";
import { answer, serveApi, type Route } from "@/test/fakeApi";
import { FakeEventSource } from "@/test/fakeStream";
import { MEMBER, OWNER, makeFocus, makeSnapshot } from "@/test/fixtures";

vi.mock("@/lib/navigation", () => ({ loadPage: vi.fn() }));

const HOUR = 3600;

// Today from 9 am: working, a pickup, away, and working again right now.
function makeDay(): Segment[] {
  const midnight = new Date().setHours(0, 0, 0, 0) / 1000;
  const segments: Segment[] = [
    { state: "working", start: midnight + 9 * HOUR, end: midnight + 10 * HOUR },
    { state: "phone", start: midnight + 10 * HOUR, end: midnight + 10.1 * HOUR },
    { state: "away", start: midnight + 10.1 * HOUR, end: midnight + 11 * HOUR },
    { state: "working", start: midnight + 11 * HOUR, end: null },
  ];
  return segments;
}

function serveDesk(me: User = OWNER, extra: Record<string, Route> = {}) {
  const sent = serveApi({ "GET /api/me": answer({ user: me }), "GET /api/focus": answer({ segments: makeDay() }), ...extra });
  return sent;
}

function openDesk(focus: Partial<FocusStatus> = {}) {
  render(
    <MemoryRouter initialEntries={["/me"]}>
      <App />
    </MemoryRouter>,
  );
  FakeEventSource.latest?.send(makeSnapshot(makeFocus(focus)));
}

function sendFocus(focus: Partial<FocusStatus>) {
  FakeEventSource.latest?.send(makeSnapshot(makeFocus(focus)));
}

const readWord = () => screen.getByRole("heading", { level: 1 }).textContent;
const readStats = () => document.querySelector("#focus-stats .sr-only")?.textContent;
const readMacLine = () => document.getElementById("mac-line")?.textContent;

beforeEach(() => {
  vi.stubGlobal("EventSource", FakeEventSource);
  serveDesk();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  toast.dismiss();
});

it.each([
  ["working", "Focused"],
  ["phone", "On your phone"],
  ["away", "Away"],
  ["unknown", "Waiting"],
] as const)("says %s in the big state word as %s", (state, word) => {
  openDesk({ state });
  expect(readWord()).toBe(word);
  expect(screen.getByRole("region", { name: "Focus" })).toHaveAttribute("data-state", state);
});

it("says Waiting before the first snapshot, with no timer or stats yet", () => {
  render(
    <MemoryRouter initialEntries={["/me"]}>
      <App />
    </MemoryRouter>,
  );
  expect(readWord()).toBe("Waiting");
  expect(screen.queryByRole("timer")).toBeNull();
  expect(readStats()).toBeUndefined();
});

it("rolls the timer every second and starts it over when the state changes", async () => {
  vi.useFakeTimers();
  openDesk({ seconds_in_state: 125 });
  expect(screen.getByRole("timer")).toHaveAccessibleName("02:05");

  await act(() => vi.advanceTimersByTimeAsync(2000));
  expect(screen.getByRole("timer")).toHaveAccessibleName("02:07");

  sendFocus({ state: "phone", seconds_in_state: 0 });
  expect(screen.getByRole("timer")).toHaveAccessibleName("00:00");
  expect(readWord()).toBe("On your phone");
});

it("caps the tens digit of the timer's minutes and seconds at 5, and adds the hours past one", () => {
  openDesk({ seconds_in_state: HOUR + 2 * 60 + 5 });
  const timer = screen.getByRole("timer");
  expect(timer).toHaveAccessibleName("1:02:05");
  const flows = Array.from(timer.querySelectorAll<NumberFlowElement>("number-flow-react"));
  expect(flows.map((flow) => flow.digits)).toEqual([undefined, { 1: { max: 5 } }, { 1: { max: 5 } }]);
});

it("draws today 6 am to midnight: the segments, the live end in the state color, and the now marker", async () => {
  vi.useFakeTimers({ toFake: ["Date"] }); // 7:12 pm, after the day's segments, whenever the tests run
  vi.setSystemTime(new Date(2026, 10, 16, 19, 12));
  serveDesk();
  openDesk();
  const timeline = screen.getByRole("img", { name: "Today, 6 am to midnight" });
  await waitFor(() => expect(timeline.querySelectorAll(".segment")).toHaveLength(4));
  const segments = Array.from(timeline.querySelectorAll(".segment"));
  expect(segments.map((segment) => segment.className.replace(" grow", ""))).toEqual([
    "segment is-working is-first",
    "segment is-phone",
    "segment is-away",
    "segment is-working is-live",
  ]);
  expect((segments[0] as HTMLElement).style.left).toMatch(/^16\.66/); // 9 am is 3 of the 18 hours in
  const midnight = new Date().setHours(0, 0, 0, 0) / 1000;
  const nowShare = ((Date.now() / 1000 - midnight - 6 * HOUR) / (18 * HOUR)) * 100;
  expect(parseFloat((timeline.querySelector(".now-cursor") as HTMLElement).style.left)).toBeCloseTo(Math.max(0, Math.min(100, nowShare)), 0);
  expect(document.querySelector(".timeline-ends")).toHaveTextContent("6 ammidnight");
});

it("sums up today in one line, numbers rolling, one pickup said as one", () => {
  openDesk();
  expect(readStats()).toBe("1h 05m focused, 5m on your phone, 3 pickups");
  expect(document.querySelectorAll("#focus-stats .focus-stat number-flow-react")).toHaveLength(4); // 1, 05, 5, 3

  sendFocus({ today: { working_seconds: 40, phone_seconds: 0, pickups: 1, longest_streak_seconds: 40, first_seen: null } });
  expect(readStats()).toBe("40s focused, 0s on your phone, 1 pickup");
});

it("mentions what's wrong in one quiet line under the stats, and nothing when all is well", () => {
  openDesk();
  expect(document.querySelector(".focus-note")).toBeNull();
  sendFocus({ camera_ok: false, voice: { enabled: true, backend: "piper", problem: "aplay isn't installed" } });
  expect(document.querySelector(".focus-note")).toHaveTextContent("No camera frames, so time isn't counted · The voice is off: aplay isn't installed");
});

it.each([
  ["an app", { app: "Code" }, "On the Mac ·Code", "Pause"],
  ["a site", { app: "Google Chrome", site: "youtube.com" }, "On the Mac ·youtube.comin Google Chrome", "Pause"],
  ["tracking paused", { app: null, mac_tracking: false }, "Mac tracking paused", "Resume"],
  ["no app", { app: null }, "The Mac isn't reporting", null],
] as const)("puts the Mac line at the right of the stats with %s", async (_, focus, line, action) => {
  openDesk(focus);
  await screen.findByRole("button", { name: "Account: Dayan" });
  expect(readMacLine()).toBe(`${line}${action ?? ""}`);
  const button = within(document.getElementById("mac-line") as HTMLElement).queryByRole("button");
  expect(button?.getAttribute("aria-label") ?? null).toBe(action && `${action} Mac tracking`);
});

it("pauses from the Mac line right away, and a late snapshot can't flip it back", async () => {
  const user = userEvent.setup();
  const sent = serveDesk(OWNER, { "POST /api/mac/tracking": answer({ enabled: false }) });
  openDesk({ mac_tracking: true });

  await user.click(await screen.findByRole("button", { name: "Pause Mac tracking" }));

  expect(sent.filter((request) => request.path === "/api/mac/tracking").map((request) => request.body)).toEqual([{ enabled: false }]);
  expect(readMacLine()).toBe("Mac tracking pausedResume");
  sendFocus({ mac_tracking: true }); // built before the Pi got the POST
  expect(readMacLine()).toBe("Mac tracking pausedResume");
});

it("resumes from the Mac line", async () => {
  const user = userEvent.setup();
  const sent = serveDesk(OWNER, { "POST /api/mac/tracking": answer({ enabled: true }) });
  openDesk({ app: null, mac_tracking: false });
  await user.click(await screen.findByRole("button", { name: "Resume Mac tracking" }));
  expect(sent.filter((request) => request.path === "/api/mac/tracking").map((request) => request.body)).toEqual([{ enabled: true }]);
});

it("puts the line back and says so when the Pi doesn't take the pause", async () => {
  const user = userEvent.setup();
  serveDesk(OWNER, {
    "POST /api/mac/tracking": () => {
      throw new TypeError("Failed to fetch");
    },
  });
  openDesk({ mac_tracking: true });
  await user.click(await screen.findByRole("button", { name: "Pause Mac tracking" }));
  await waitFor(() => expect(readMacLine()).toBe("On the Mac ·CodePause"));
  expect(await screen.findByText("Couldn't pause Mac tracking")).toBeInTheDocument();
});

it("gives a member Pause/Resume for their own desk's Mac tracking", async () => {
  serveDesk(MEMBER);
  openDesk({ mac_tracking: false, app: null, camera_access: "owner_only" });
  await screen.findByRole("button", { name: "Account: Sam" });
  expect(readMacLine()).toBe("Mac tracking pausedResume");
  expect(screen.getByRole("button", { name: "Resume Mac tracking" })).toBeInTheDocument();
});

it("offers Turn on camera to a desk on a browser's camera while nothing's coming in, instead of a broken detector", async () => {
  serveDesk(MEMBER);
  openDesk({ state: "unknown", enabled: true, camera_ok: false, last_check: null, voice: null, camera_access: "owner_only", camera_source: "browser", camera_paused: false });
  await screen.findByRole("button", { name: "Account: Sam" });
  const line = screen.getByText("No camera yet, so time isn't counted.");
  expect(within(line).getByRole("button", { name: "Turn on camera" })).toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /tracker/ })).toBeNull();
  expect(screen.queryByText(/detector/)).toBeNull();
});

it("says a camera that was turned off is off, with Turn on camera", async () => {
  serveDesk(MEMBER);
  openDesk({ state: "unknown", enabled: true, camera_ok: false, last_check: null, voice: null, camera_access: "owner_only", camera_source: "browser", camera_paused: true });
  await screen.findByRole("button", { name: "Account: Sam" });
  const line = screen.getByText("Your camera is off, so time isn't counted.");
  expect(within(line).getByRole("button", { name: "Turn on camera" })).toBeInTheDocument();
  expect(screen.queryByText(/paused on the tracker page/)).toBeNull();
});

it("starts the stats line with the goal's ring and how far along you are, and leaves both out with no goal", () => {
  openDesk({ goal_minutes: 240 });
  expect(readStats()).toBe("1h 05m focused of your 4h goal, 5m on your phone, 3 pickups");
  expect(document.querySelector("#focus-stats")).toHaveTextContent(/05m of 4h · .*on your phone/);
  const ring = document.querySelector("#focus-stats .goal-ring-fill");
  expect(ring?.getAttribute("stroke-dasharray")).toBe(`${((3900 / 14400) * 2 * Math.PI * 14).toFixed(1)} ${(2 * Math.PI * 14).toFixed(1)}`);

  sendFocus({ goal_minutes: null });
  expect(readStats()).toBe("1h 05m focused, 5m on your phone, 3 pickups");
  expect(document.querySelector("#focus-stats .goal-ring")).toBeNull();
});
