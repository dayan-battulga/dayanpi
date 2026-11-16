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
  expect(screen.getByRole("button", { name: "Start block" })).toBeEnabled();
  expect(document.querySelector(".reading[data-key=person] .reading-value")).toHaveTextContent("0.92");
  expect(document.getElementById("check-ms")).toHaveTextContent("~186 ms each");
  expect(document.querySelector(".box.is-person .box-label")).toHaveTextContent("person 0.92");
  expect(screen.getByText("finish the report")).toBeInTheDocument();
  expect(screen.getByText("12m")).toBeInTheDocument();
  expect(document.getElementById("sign-page")).toHaveTextContent("Now");
  expect(document.getElementById("sign-image")).toHaveAttribute("src", "/api/sign.png?v=4");
  expect(document.getElementById("pi-summary")).toHaveTextContent("Running smooth");
  expect(document.getElementById("temp")).toHaveTextContent("48.2");
  expect(document.getElementById("cpu-cores")?.children).toHaveLength(4);
  expect(document.getElementById("net")).toHaveTextContent("↓ 120 kb/s · ↑ 1.5 Mb/s");
  expect(document.getElementById("sign-mode")).toHaveTextContent("preview");
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

it("shows the browser's site next to the Mac app", () => {
  render(<App />);
  FakeEventSource.latest?.send(makeSnapshot(makeFocus({ app: "Google Chrome", site: "youtube.com" })));
  expect(document.getElementById("mac")).toHaveTextContent("Google Chrome · youtube.com");
});

it("offers Show pose only with the pose model, and draws the skeleton over the front feed", async () => {
  const user = userEvent.setup();
  window.localStorage.removeItem("dayanpi.pose");
  render(<App />);
  FakeEventSource.latest?.send(makeSnapshot());
  expect(screen.queryByRole("button", { name: "Show pose" })).toBeNull();

  const focus = makeFocus();
  const pose = Array.from({ length: 17 }, (_, index): [number, number, number] => [0.3 + index / 50, 0.2 + index / 30, 0.9]);
  FakeEventSource.latest?.send(makeSnapshot({ ...focus, overlay: focus.overlay && { ...focus.overlay, pose } }));
  await user.click(screen.getByRole("button", { name: "Show pose" }));

  expect(screen.getByRole("button", { name: "Hide pose" })).toHaveAttribute("aria-pressed", "true");
  expect(document.querySelectorAll(".feed-frame svg.pose line")).toHaveLength(19);
  expect(document.querySelectorAll(".feed-frame svg.pose circle")).toHaveLength(17);
  expect(window.localStorage.getItem("dayanpi.pose")).toBe("1");
});
