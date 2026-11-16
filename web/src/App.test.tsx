import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "@/App";
import { makeFocus, makeSnapshot } from "@/test/fixtures";

class FakeEventSource {
  static latest: FakeEventSource | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(public url: string) {
    FakeEventSource.latest = this;
  }

  close() {}

  send(data: object) {
    act(() => this.onmessage?.({ data: JSON.stringify(data) }));
  }
}

beforeEach(() => {
  const start = Date.now() / 1000 - 3600;
  const segments = [{ state: "working", start, end: null }];
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ segments }) })));
});

afterEach(() => {
  vi.unstubAllGlobals();
});

it("draws every card from one stream", async () => {
  render(<App />);
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
  render(<App />);
  FakeEventSource.latest?.send(makeSnapshot());
  expect(document.querySelectorAll(".box:not(.is-leaving)")).toHaveLength(1);

  const stale = makeFocus();
  FakeEventSource.latest?.send(makeSnapshot({ ...stale, overlay: stale.overlay && { ...stale.overlay, age_s: 3.5 } }));

  expect(document.querySelectorAll(".box:not(.is-leaving)")).toHaveLength(0);
});

it("shows the flip button only with a side camera, and only one feed at a time", () => {
  render(<App />);
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
  render(<App />);
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ gesture: { name: "peace", age_s: 0.6 } })));
  expect(screen.getByRole("status")).toHaveTextContent("Peace sign: reading your to-dos");

  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ gesture: { name: "peace", age_s: 4.5 } })));

  expect(screen.getByRole("status")).toBeEmptyDOMElement();
});

it("puts what's in front on the Mac at the top, the site big when it's a browser", () => {
  render(<App />);
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
  const posts: string[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string, init?: RequestInit) => {
      if (path === "/api/mac/tracking") posts.push(String(init?.body));
      return { ok: true, json: async () => ({ segments: [], enabled: false }) };
    }),
  );
  render(<App />);
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ mac_tracking: true })));
  const toggle = screen.getByRole("switch", { name: "Mac tracking" });
  expect(toggle).toHaveAttribute("aria-checked", "true");

  await user.click(toggle);

  expect(posts).toEqual(['{"enabled":false}']);
  expect(screen.getByRole("switch", { name: "Mac tracking" })).toHaveAttribute("aria-checked", "false");
  expect(document.getElementById("mac")).toHaveTextContent("Paused");
});

it("puts the switch back when the Pi doesn't take it", async () => {
  const user = userEvent.setup();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (path: string) => {
      if (path === "/api/mac/tracking") throw new TypeError("Failed to fetch");
      return { ok: true, json: async () => ({ segments: [] }) };
    }),
  );
  render(<App />);
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ mac_tracking: true })));
  await user.click(screen.getByRole("switch", { name: "Mac tracking" }));
  await waitFor(() => expect(screen.getByRole("switch", { name: "Mac tracking" })).toHaveAttribute("aria-checked", "true"));
  expect(document.getElementById("mac")).toHaveTextContent(/^Code$/);
});

it("says Paused when the Pi says the switch is off", () => {
  render(<App />);
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ mac_tracking: false })));
  expect(screen.getByRole("switch", { name: "Mac tracking" })).toHaveAttribute("aria-checked", "false");
  expect(document.getElementById("mac")).toHaveTextContent("Paused");
});
