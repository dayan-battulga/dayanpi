import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "@/App";
import { ME_RETRY_MS } from "@/hooks/useMe";
import { STREAM_RETRY_MS } from "@/hooks/useSnapshot";
import { loadPage } from "@/lib/navigation";
import type { User } from "@/lib/types";
import { answer, serveApi, type Route } from "@/test/fakeApi";
import { MEMBER, OWNER, makeFocus, makeSnapshot } from "@/test/fixtures";

vi.mock("@/lib/navigation", () => ({ loadPage: vi.fn() }));

class FakeEventSource {
  static readonly CLOSED = 2;
  static latest: FakeEventSource | null = null;
  readyState = 1;
  closed = false;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(public url: string) {
    FakeEventSource.latest = this;
  }

  close() {
    this.closed = true;
  }

  send(data: object) {
    act(() => this.onmessage?.({ data: JSON.stringify(data) }));
  }

  // A dropped connection the browser retries (0, connecting), or a non-200 answer it gives up on (2, closed).
  fail(readyState = 0) {
    this.readyState = readyState;
    act(() => this.onerror?.());
  }
}

// The Pi's answers the dashboard asks for on load: who you are, and today's segments.
function servePi(me: User = OWNER, extra: Record<string, Route> = {}) {
  const start = Date.now() / 1000 - 3600;
  const sent = serveApi({
    "GET /api/me": answer({ user: me }),
    "GET /api/focus": answer({ segments: [{ state: "working", start, end: null }] }),
    ...extra,
  });
  return sent;
}

function renderApp() {
  render(
    <MemoryRouter>
      <App />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.stubGlobal("EventSource", FakeEventSource);
  servePi();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.mocked(loadPage).mockClear();
  window.localStorage.clear();
});

it("draws every card from one stream", async () => {
  renderApp();
  expect(screen.getByText("Offline")).toBeInTheDocument();
  expect(FakeEventSource.latest?.url).toBe("/api/stream");

  FakeEventSource.latest?.send(makeSnapshot());

  expect(screen.getByText("Live")).toBeInTheDocument();
  expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Focused");
  expect(document.getElementById("focus-state")).toHaveTextContent("Working");
  expect(document.getElementById("focus-timer")).toHaveTextContent("2:05");
  expect(document.getElementById("focus-working")).toHaveTextContent("1h 05m");
  expect(document.getElementById("focus-pickups")).toHaveTextContent("3");
  expect(document.querySelector(".reading[data-key=person] .reading-value")).toHaveTextContent("0.92");
  expect(document.getElementById("check-ms")).toHaveTextContent("~186 ms each");
  expect(document.querySelector(".box.is-person .box-label")).toHaveTextContent("person 0.92");
  expect(screen.getByText("finish the report")).toBeInTheDocument();
  expect(screen.getByText("12m")).toBeInTheDocument();
  expect(document.getElementById("pi-summary")).toHaveTextContent("Running smooth");
  expect(document.getElementById("temp")).toHaveTextContent("48.2");
  expect(document.getElementById("cpu-cores")?.children).toHaveLength(4);
  expect(document.getElementById("net")).toHaveTextContent("↓ 120 kb/s · ↑ 1.5 Mb/s");
  expect(document.getElementById("mac")).toHaveTextContent(/^Code$/);

  await waitFor(() => expect(document.querySelector(".segment.is-working.is-live")).not.toBeNull());
  expect(screen.getByText("Sat down to work")).toBeInTheDocument();
});

it("drops the boxes once the overlay is more than 3 s old", () => {
  renderApp();
  FakeEventSource.latest?.send(makeSnapshot());
  expect(document.querySelectorAll(".box:not(.is-leaving)")).toHaveLength(1);

  const stale = makeFocus();
  FakeEventSource.latest?.send(makeSnapshot({ ...stale, overlay: stale.overlay && { ...stale.overlay, age_s: 3.5 } }));

  expect(document.querySelectorAll(".box:not(.is-leaving)")).toHaveLength(0);
});

it("shows the flip button only with a side camera, and only one feed at a time", () => {
  renderApp();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ side_camera: true })));
  const flip = screen.getByRole("button", { name: "Show the side camera" });
  const [front, side] = Array.from(document.querySelectorAll(".feed-frame"));
  expect(front).toBeVisible();
  expect(side).not.toBeVisible();

  act(() => flip.click());

  expect(front).not.toBeVisible();
  expect(side).toBeVisible();
  expect(screen.getByRole("button", { name: "Show the front camera" })).toBeInTheDocument();
});

it("shows the last gesture or hand sign for a few seconds", () => {
  renderApp();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ gesture: { name: "peace", age_s: 0.6 } })));
  expect(screen.getByRole("status")).toHaveTextContent("Peace sign: reading your to-dos");

  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ gesture: { name: "peace", age_s: 4.5 } })));

  expect(screen.getByRole("status")).toBeEmptyDOMElement();
});

it("puts what's in front on the Mac at the top, the site big when it's a browser", () => {
  renderApp();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ app: "Google Chrome", site: "youtube.com" })));
  const card = screen.getByRole("region", { name: "On the Mac" });
  expect(document.getElementById("mac")).toHaveTextContent(/^youtube\.com$/);
  expect(card).toHaveTextContent("in Google Chrome");
  expect(card.compareDocumentPosition(document.getElementById("focus-card")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(document.querySelector("#pi dt")?.parentElement?.parentElement).not.toHaveTextContent(/Mac/);

  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ app: null })));
  expect(document.getElementById("mac")).toHaveTextContent("Not reporting");
});

it("pauses the Mac tracker from its switch, flipping right away", async () => {
  const user = userEvent.setup();
  const sent = servePi(OWNER, { "POST /api/mac/tracking": answer({ enabled: false }) });
  renderApp();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ mac_tracking: true })));
  const toggle = await screen.findByRole("switch", { name: "Mac tracking" });
  expect(toggle).toHaveAttribute("aria-checked", "true");

  await user.click(toggle);

  expect(sent.filter((request) => request.path === "/api/mac/tracking").map((request) => request.body)).toEqual([{ enabled: false }]);
  expect(screen.getByRole("switch", { name: "Mac tracking" })).toHaveAttribute("aria-checked", "false");
  expect(document.getElementById("mac")).toHaveTextContent("Paused");
});

it("puts the switch back when the Pi doesn't take it", async () => {
  const user = userEvent.setup();
  servePi(OWNER, {
    "POST /api/mac/tracking": () => {
      throw new TypeError("Failed to fetch");
    },
  });
  renderApp();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ mac_tracking: true })));
  await user.click(await screen.findByRole("switch", { name: "Mac tracking" }));
  await waitFor(() => expect(screen.getByRole("switch", { name: "Mac tracking" })).toHaveAttribute("aria-checked", "true"));
  expect(document.getElementById("mac")).toHaveTextContent(/^Code$/);
});

it("says Paused when the Pi says the switch is off", async () => {
  renderApp();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ mac_tracking: false })));
  expect(await screen.findByRole("switch", { name: "Mac tracking" })).toHaveAttribute("aria-checked", "false");
  expect(document.getElementById("mac")).toHaveTextContent("Paused");
});

it("shows a member the dashboard without the owner's controls or the Pi's numbers", async () => {
  servePi(MEMBER);
  renderApp();
  FakeEventSource.latest?.send({ focus: makeFocus({ camera_access: "owner_only" }) });

  expect(await screen.findByRole("button", { name: "Sam" })).toBeInTheDocument();
  expect(screen.getByText("finish the report")).toBeInTheDocument();
  expect(screen.queryByRole("textbox", { name: "New to-do" })).toBeNull();
  expect(screen.queryByRole("checkbox", { name: "Done: finish the report" })).toBeNull();
  expect(screen.queryByRole("switch", { name: "Mac tracking" })).toBeNull();
  expect(document.getElementById("mac")).toHaveTextContent(/^Code$/);
  expect(document.getElementById("pi")).toBeNull();
  expect(screen.queryByRole("link", { name: "Pi" })).toBeNull();
  expect(document.getElementById("power-alert")).not.toBeVisible();
});

it.each([
  ["tailscale_only", "Tailscale only", "Open the dashboard on one of your own Tailscale devices to see the camera."],
  ["owner_only", "The camera is private", "The readings next to it still update."],
] as const)("never opens /video when the camera is %s, and says why", async (access, title, text) => {
  window.localStorage.setItem("dayanpi.peek", "1");
  renderApp();
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ camera_access: access, side_camera: true, overlay: null })));
  const camera = screen.getByRole("region", { name: "Camera" });
  expect(camera.querySelector(".veil")).toHaveTextContent(title);
  expect(camera.querySelector(".veil")).toHaveTextContent(text);
  expect(camera.querySelector("img")).toBeNull();
  expect(camera).not.toHaveClass("is-peeking");
  expect(document.getElementById("peek-toggle")).not.toBeVisible();
  expect(document.getElementById("camera-flip")).not.toBeVisible();
  await screen.findByRole("button", { name: "Dayan" });
});

it("opens the feed as before when the camera is open, or the Pi doesn't say", () => {
  window.localStorage.setItem("dayanpi.peek", "1");
  renderApp();
  expect(document.querySelector("#camera img")?.getAttribute("src")).toMatch(/^data:/); // nothing opened before the first status
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ camera_access: "open" })));
  expect(document.querySelector("#camera img")?.getAttribute("src")).toMatch(/^\/video\?t=/);
  FakeEventSource.latest?.send(makeSnapshot(makeFocus()));
  expect(document.querySelector("#camera img")?.getAttribute("src")).toMatch(/^\/video\?t=/);
});

it("asks /api/me when the stream drops, and goes to /login on a 401", async () => {
  renderApp();
  await screen.findByRole("button", { name: "Dayan" });
  servePi(OWNER, { "GET /api/me": answer({ detail: "sign in first" }, 401) });
  window.history.pushState({}, "", "/?x=1");

  FakeEventSource.latest?.fail();

  expect(screen.getByText("Reconnecting")).toBeInTheDocument();
  await waitFor(() => expect(loadPage).toHaveBeenCalledWith("/login?next=%2F%3Fx%3D1"));
});

it("asks /api/me again when it got no answer, so the owner isn't stuck read-only", async () => {
  vi.useFakeTimers();
  servePi(OWNER, { "GET /api/me": answer({ detail: "Pi restarting" }, 503) });
  renderApp();
  await act(() => vi.advanceTimersByTimeAsync(0));
  expect(screen.queryByRole("button", { name: "Dayan" })).not.toBeInTheDocument();

  servePi();
  await act(() => vi.advanceTimersByTimeAsync(ME_RETRY_MS));

  expect(screen.getByRole("button", { name: "Dayan" })).toBeInTheDocument();
});

it("reopens the stream a few seconds after the Pi turns it away with a 502 or 503", async () => {
  renderApp();
  await screen.findByRole("button", { name: "Dayan" });
  const first = FakeEventSource.latest;
  vi.useFakeTimers();

  first?.fail(FakeEventSource.CLOSED);

  expect(screen.getByText("Reconnecting")).toBeInTheDocument();
  expect(first?.closed).toBe(true);
  act(() => vi.advanceTimersByTime(STREAM_RETRY_MS));
  expect(FakeEventSource.latest).not.toBe(first);
  FakeEventSource.latest?.send(makeSnapshot());
  expect(screen.getByText("Live")).toBeInTheDocument();
});
