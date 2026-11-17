import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import { TrackPage } from "@/components/track/TrackPage";
import type { TrackerReply } from "@/lib/track";
import { answer, serveApi, type Route } from "@/test/fakeApi";
import { makeFocus } from "@/test/fixtures";

// The tracker's worker, as the page sees it: what it was sent, and a way to answer.
class FakeWorker {
  static latest: FakeWorker | null = null;
  sent: unknown[] = [];
  terminated = false;
  onmessage: ((event: MessageEvent<TrackerReply>) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor() {
    FakeWorker.latest = this;
  }

  postMessage(message: unknown) {
    this.sent.push(message);
  }

  terminate() {
    this.terminated = true;
  }

  answer(reply: TrackerReply) {
    act(() => this.onmessage?.({ data: reply } as MessageEvent<TrackerReply>));
  }
}

function makeTrack() {
  const track = { stop: vi.fn(), getSettings: () => ({ width: 640, height: 480 }), clone: () => makeTrack() };
  return track;
}

// Chrome's frame reader and a camera, or a camera that fails with this error.
function pretendChrome(camera: "works" | DOMException | null) {
  vi.stubGlobal("MediaStreamTrackProcessor", class {
    readable = {};
  });
  vi.stubGlobal("Worker", FakeWorker);
  const track = makeTrack();
  const getUserMedia = vi.fn(() => (camera === "works" ? Promise.resolve({ getVideoTracks: () => [track] }) : Promise.reject(camera)));
  Object.defineProperty(navigator, "mediaDevices", { value: camera === null ? undefined : { getUserMedia }, configurable: true });
  return { getUserMedia, track };
}

function renderTrack(routes: Record<string, Route> = {}) {
  const sent = serveApi({ "GET /api/focus": answer(makeFocus({ state: "working", seconds_in_state: 1120, camera_source: "browser" })), ...routes });
  render(
    <MemoryRouter initialEntries={["/track"]}>
      <TrackPage />
    </MemoryRouter>,
  );
  const user = userEvent.setup();
  return { user, sent };
}

afterEach(() => {
  vi.unstubAllGlobals();
  Object.defineProperty(navigator, "mediaDevices", { value: undefined, configurable: true });
  FakeWorker.latest = null;
});

it("asks before it turns the camera on", async () => {
  const { getUserMedia } = pretendChrome("works");
  const { user } = renderTrack();
  expect(screen.getByRole("heading", { name: "Turn on your camera" })).toBeInTheDocument();
  expect(screen.getByText("Your video stays on this computer. Only the numbers go to the room.")).toBeInTheDocument();
  expect(getUserMedia).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Allow camera" }));
  expect(getUserMedia).toHaveBeenCalledWith({ video: { width: { ideal: 640 }, height: { ideal: 480 } }, audio: false });
});

it.each([
  ["blocked", new DOMException("denied", "NotAllowedError"), "Camera is blocked", "Click the camera icon in the address bar, allow it, then reload."],
  ["missing", new DOMException("none", "NotFoundError"), "No camera found", "Check it's plugged in and turned on, then try again."],
  ["in use", new DOMException("busy", "NotReadableError"), "The camera is busy", "Another app is using it (Zoom, FaceTime, Photo Booth…). Close it, then try again."],
  ["not there at all", null, "No camera found", "Check it's plugged in and turned on, then try again."],
])("says so when the camera is %s, and offers Try again", async (_, error, title, text) => {
  pretendChrome(error);
  const { user } = renderTrack();
  await user.click(screen.getByRole("button", { name: "Allow camera" }));
  expect(await screen.findByRole("heading", { name: title })).toBeInTheDocument();
  expect(screen.getByText(text)).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Try again" })).toBeEnabled();
  expect(FakeWorker.latest).toBeNull();
});

it("says it needs Chrome without asking for the camera", async () => {
  const getUserMedia = vi.fn();
  Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia }, configurable: true });
  const { user } = renderTrack();
  await user.click(screen.getByRole("button", { name: "Allow camera" }));
  expect(await screen.findByRole("heading", { name: "This needs Chrome" })).toBeInTheDocument();
  expect(getUserMedia).not.toHaveBeenCalled();
});

it("runs: the preview, the desk's state and timer, the boxes, and a load line that says why it slowed down", async () => {
  pretendChrome("works");
  const { user } = renderTrack();
  await user.click(await screen.findByRole("button", { name: "Allow camera" }));
  expect(await screen.findByText("Only you see this")).toBeInTheDocument();
  expect(screen.getByText("Focused")).toBeInTheDocument();
  expect(screen.getByText(/^18:4\d$/)).toBeInTheDocument();
  expect(screen.getByText("Keep this tab open. It keeps going behind other tabs and windows.")).toBeInTheDocument();
  expect(screen.getByText("Loading the models")).toBeInTheDocument();
  const worker = FakeWorker.latest!;
  expect(worker.sent[0]).toMatchObject({ type: "start", lowBattery: false });

  worker.answer({ type: "ready", backend: "WebGPU", loadMs: 900 });
  worker.answer({ type: "check", ms: 142.4, boxes: [{ kind: "person", x: 0.3, y: 0.2, width: 0.4, height: 0.7 }], pace: { intervalMs: 1000, reason: "normal" } });
  worker.answer({ type: "tracked", state: "phone", seconds_in_state: 4, paused: false });

  expect(screen.getByText("142 ms a check · WebGPU")).toBeInTheDocument();
  expect(screen.getByText("On your phone")).toBeInTheDocument();
  expect(document.querySelectorAll(".track-box[data-kind='person']")).toHaveLength(1);
  worker.answer({ type: "check", ms: 130, boxes: [], pace: { intervalMs: 3000, reason: "idle" } });
  expect(screen.getByText("130 ms a check · WebGPU · Nobody's here, so it checks every 3 s")).toBeInTheDocument();
  expect(document.querySelectorAll(".track-box")).toHaveLength(0);
});

it("pauses: the models and the camera stop, the Pi hears it, and Resume starts again", async () => {
  const { track } = pretendChrome("works");
  const { user, sent } = renderTrack({ "POST /api/track/pause": answer({ state: "unknown", seconds_in_state: 0, paused: true }) });
  await user.click(await screen.findByRole("button", { name: "Allow camera" }));
  const worker = FakeWorker.latest!;
  await user.click(await screen.findByRole("button", { name: "Pause" }));
  expect(worker.terminated).toBe(true);
  expect(track.stop).toHaveBeenCalled();
  expect(await screen.findByRole("heading", { name: "Tracking is paused" })).toBeInTheDocument();
  await waitFor(() => expect(sent.filter((request) => request.path === "/api/track/pause").map((request) => [request.method, request.body])).toEqual([["POST", {}]]));
  await user.click(screen.getByRole("button", { name: "Resume" }));
  expect(await screen.findByText("Only you see this")).toBeInTheDocument();
  expect(FakeWorker.latest).not.toBe(worker);
});

it("opens on Resume when the desk was left paused", async () => {
  pretendChrome("works");
  renderTrack({ "GET /api/focus": answer(makeFocus({ state: "unknown", camera_source: "browser", camera_paused: true })) });
  expect(await screen.findByRole("heading", { name: "Tracking is paused" })).toBeInTheDocument();
});

it("points a desk on the Pi's cameras to Settings instead of starting", async () => {
  const { getUserMedia } = pretendChrome("works");
  renderTrack({ "GET /api/focus": answer(makeFocus({ camera_source: "pi" })) });
  expect(await screen.findByRole("heading", { name: "Your desk uses the Pi's cameras" })).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "Open Settings" })).toHaveAttribute("href", "/settings");
  expect(getUserMedia).not.toHaveBeenCalled();
});

it("stops and says so when the Pi turns the readings away, or the models stop", async () => {
  pretendChrome("works");
  const { user } = renderTrack();
  await user.click(await screen.findByRole("button", { name: "Allow camera" }));
  FakeWorker.latest!.answer({ type: "failed", message: "out of memory" });
  expect(await screen.findByRole("heading", { name: "The tracker stopped" })).toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Try again" }));
  FakeWorker.latest!.answer({ type: "refused" });
  expect(await screen.findByRole("heading", { name: "Your desk uses the Pi's cameras" })).toBeInTheDocument();
});
