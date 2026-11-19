import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, useLocation, useNavigate } from "react-router";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { App } from "@/App";
import { CameraTracker } from "@/components/track/cameraTracker";
import type { TrackerReply } from "@/lib/track";
import type { FocusStatus } from "@/lib/types";
import { answer, serveApi } from "@/test/fakeApi";
import { FakeEventSource } from "@/test/fakeStream";
import { MEMBER, makeFocus, makeSeat, makeSnapshot } from "@/test/fixtures";

vi.mock("@/lib/navigation", () => ({ loadPage: vi.fn() }));

const REMEMBERED = "dayanpi.camera";
const ASKED = { video: { width: { ideal: 1280 }, height: { ideal: 720 } }, audio: false };
// A member's desk is always on the browser's camera; this one hears nothing yet.
const NO_CAMERA: Partial<FocusStatus> = { state: "unknown", camera_source: "browser", camera_ok: false, camera_paused: false, last_check: null, camera_access: "owner_only" };

// The tracker's worker, as the page sees it: what it was sent, and a way to answer.
class FakeWorker {
  static all: FakeWorker[] = [];
  sent: unknown[] = [];
  terminated = false;
  onmessage: ((event: MessageEvent<TrackerReply>) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor() {
    FakeWorker.all.push(this);
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

// Web Locks for one browser: one holder at a time, the rest in line, ifAvailable and leaving the line by AbortSignal.
class FakeLocks {
  private held = false;
  private line: (() => void)[] = [];

  async request(name: string, options: LockOptions, callback: (lock: Lock | null) => Promise<unknown>): Promise<unknown> {
    if (this.held && options.ifAvailable) {
      return callback(null);
    }
    if (this.held) {
      await new Promise<void>((resolve, reject) => {
        this.line.push(resolve);
        options.signal?.addEventListener("abort", () => {
          this.line = this.line.filter((waiting) => waiting !== resolve);
          reject(new DOMException("left the line", "AbortError"));
        });
      });
    }
    this.held = true;
    try {
      return await callback({ name, mode: "exclusive" } as Lock);
    } finally {
      this.held = false;
      this.line.shift()?.();
    }
  }
}

interface Chrome {
  camera?: "works" | DOMException | null;
  permission?: PermissionState;
  processor?: boolean;
}

// Chrome's frame reader, a camera (or one that fails with this error), the camera permission and Web Locks.
function pretendChrome({ camera = "works", permission = "prompt", processor = true }: Chrome = {}) {
  if (processor) {
    vi.stubGlobal("MediaStreamTrackProcessor", class {
      readable = {};
    });
  }
  vi.stubGlobal("Worker", FakeWorker);
  const tracks: { stop: ReturnType<typeof vi.fn> }[] = [];
  const makeTrack = (): object => {
    const track = { stop: vi.fn(), getSettings: () => ({ width: 1280, height: 720 }), clone: makeTrack };
    tracks.push(track);
    return track;
  };
  const getUserMedia = vi.fn(() => {
    const track = makeTrack();
    return camera === "works" ? Promise.resolve({ getVideoTracks: () => [track], getTracks: () => [track] }) : Promise.reject(camera);
  });
  const query = vi.fn(async () => ({ state: permission }));
  const locks = new FakeLocks();
  Object.defineProperty(navigator, "mediaDevices", { value: camera === null ? undefined : { getUserMedia }, configurable: true });
  Object.defineProperty(navigator, "permissions", { value: { query }, configurable: true });
  Object.defineProperty(navigator, "locks", { value: locks, configurable: true });
  return { getUserMedia, query, tracks, locks };
}

function ShowPath() {
  const navigate = useNavigate();
  return (
    <>
      <output aria-label="Path">{useLocation().pathname}</output>
      {["/", "/me", "/settings", "/people/dayan"].map((path) => (
        <button key={path} type="button" onClick={() => navigate(path)}>{`go ${path}`}</button>
      ))}
    </>
  );
}

function openApp(path = "/", focus: Partial<FocusStatus> = NO_CAMERA) {
  const sent = serveApi({
    "GET /api/me": answer({ user: MEMBER }),
    "GET /api/focus": answer({ segments: [] }),
    "GET /api/tokens": answer({ tokens: [] }),
    "POST /api/track/pause": answer({ state: "unknown", seconds_in_state: 0, paused: true }),
  });
  const shown = render(
    <MemoryRouter initialEntries={[path]}>
      <App />
      <ShowPath />
    </MemoryRouter>,
  );
  const seats = [makeSeat({ username: "sam", name: "Sam", state: focus.state ?? "unknown" }), makeSeat()];
  FakeEventSource.latest?.send({ ...makeSnapshot(makeFocus(focus)), room: { seats } });
  return { user: userEvent.setup(), sent, unmount: shown.unmount };
}

const mySeat = () => within(screen.getByRole("article", { name: "Sam, you" }));
// The seat is yours once /api/me has answered.
const findMySeat = async () => within(await screen.findByRole("article", { name: "Sam, you" }));
// Every promise that's ready settles: the lock, the permission, the camera.
const settle = () => act(async () => {});

async function turnOnFromSeat(user: ReturnType<typeof userEvent.setup>): Promise<FakeWorker> {
  await user.click(await (await findMySeat()).findByRole("button", { name: "Turn on camera" }));
  await waitFor(() => expect(FakeWorker.all).toHaveLength(1));
  return FakeWorker.all[0];
}

beforeEach(() => {
  vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
  for (const name of ["mediaDevices", "permissions", "locks"]) {
    Object.defineProperty(navigator, name, { value: undefined, configurable: true });
  }
  Object.defineProperty(performance, "measureUserAgentSpecificMemory", { value: undefined, configurable: true });
  FakeWorker.all = [];
  window.localStorage.clear();
});

it("asks Chrome for the camera only on a click, at 1280x720, and remembers it was on", async () => {
  const { getUserMedia } = pretendChrome({ permission: "granted" }); // allowed, but this browser never turned it on
  const { user } = openApp();
  const button = await (await findMySeat()).findByRole("button", { name: "Turn on camera" });
  await settle();
  expect(getUserMedia).not.toHaveBeenCalled();
  expect(FakeWorker.all).toHaveLength(0); // so the models and ONNX Runtime never load

  await user.click(button);

  await waitFor(() => expect(getUserMedia).toHaveBeenCalledWith(ASKED));
  expect(await (await findMySeat()).findByText("Starting…")).toBeInTheDocument();
  expect(window.localStorage.getItem(REMEMBERED)).toBe("on");
});

it("shows the seat's states: Turn on camera, Starting…, then your own camera live with Camera on and Turn off", async () => {
  pretendChrome();
  const { user } = openApp();
  expect(await (await findMySeat()).findByRole("button", { name: "Show my video" })).toBeInTheDocument();
  const worker = await turnOnFromSeat(user);
  expect(mySeat().getByRole("status")).toHaveTextContent("Starting…");
  expect(mySeat().queryByRole("button", { name: /Turn/ })).toBeNull();
  expect(worker.sent[0]).toMatchObject({ type: "start", lowBattery: false });

  worker.answer({ type: "ready", backend: "WebGPU", loadMs: 900 });

  expect(mySeat().getByRole("status")).toHaveTextContent("Camera on");
  expect(mySeat().getByRole("button", { name: "Turn off" })).toBeInTheDocument();
  expect(document.querySelector(".seat-live")).not.toBeNull(); // straight from the camera, not a picture from the Pi
  expect(mySeat().getByRole("button", { name: "Show my video" })).toBeInTheDocument(); // the sharing switch, as before
});

it.each([
  ["blocked", new DOMException("denied", "NotAllowedError"), "Camera is blocked"],
  ["missing", new DOMException("none", "NotFoundError"), "No camera found"],
  ["in use", new DOMException("busy", "NotReadableError"), "The camera is busy"],
  ["not there at all", null, "No camera found"],
])("says so on the seat when the camera is %s, with Try again", async (_, error, title) => {
  pretendChrome({ camera: error });
  const { user } = openApp();
  await user.click(await (await findMySeat()).findByRole("button", { name: "Turn on camera" }));
  expect(await (await findMySeat()).findByText(title)).toBeInTheDocument();
  expect(mySeat().getByRole("button", { name: "Try again" })).toBeInTheDocument();
  expect(FakeWorker.all).toHaveLength(0);
  expect(window.localStorage.getItem(REMEMBERED)).toBeNull();
});

it("says it needs Chrome without asking for the camera, and when the tracker stops", async () => {
  const { getUserMedia } = pretendChrome({ processor: false });
  const { user } = openApp();
  await user.click(await (await findMySeat()).findByRole("button", { name: "Turn on camera" }));
  expect(await (await findMySeat()).findByText("This needs Chrome")).toBeInTheDocument();
  expect(mySeat().queryByRole("button", { name: "Try again" })).toBeNull();
  expect(getUserMedia).not.toHaveBeenCalled();

  vi.stubGlobal("MediaStreamTrackProcessor", class {
    readable = {};
  });
  const tracker = new CameraTracker();
  tracker.attach();
  tracker.setSource("browser");
  tracker.turnOn();
  await waitFor(() => expect(FakeWorker.all).toHaveLength(1));
  FakeWorker.all[0].answer({ type: "failed", message: "out of memory" });
  expect(tracker.getView()).toMatchObject({ step: "problem", problem: "failed", preview: null });
  expect(FakeWorker.all[0].terminated).toBe(true);
  tracker.detach();
});

it("leaves your seat alone while another computer feeds your desk, and offers nothing to a desk on the Pi's cameras", async () => {
  pretendChrome();
  const fed = openApp("/", { ...NO_CAMERA, state: "working", camera_ok: true });
  expect(await (await findMySeat()).findByRole("button", { name: "Show my video" })).toBeInTheDocument();
  expect(mySeat().queryByRole("button", { name: "Turn on camera" })).toBeNull();
  fed.unmount();

  openApp("/", { ...NO_CAMERA, camera_source: "pi" });
  expect(await (await findMySeat()).findByRole("button", { name: "Show my video" })).toBeInTheDocument();
  expect(mySeat().queryByRole("button", { name: "Turn on camera" })).toBeNull();
});

it("keeps running from page to page: Room, Desk, Settings and someone's desk", async () => {
  const { getUserMedia, tracks } = pretendChrome();
  const { user } = openApp();
  const worker = await turnOnFromSeat(user);
  worker.answer({ type: "ready", backend: "WebGPU", loadMs: 900 });

  for (const path of ["/me", "/settings", "/people/dayan", "/"]) {
    await user.click(screen.getByRole("button", { name: `go ${path}` }));
    await waitFor(() => expect(screen.getByRole("status", { name: "Path" })).toHaveTextContent(new RegExp(`^${path}$`)));
  }

  expect(FakeWorker.all).toEqual([worker]);
  expect(worker.terminated).toBe(false);
  expect(tracks.every((track) => track.stop.mock.calls.length === 0)).toBe(true);
  expect(getUserMedia).toHaveBeenCalledTimes(1);
  expect(await (await findMySeat()).findByText("Camera on")).toBeInTheDocument();
});

it("comes back by itself on a reload when it was on and Chrome still allows it", async () => {
  window.localStorage.setItem(REMEMBERED, "on");
  const { getUserMedia } = pretendChrome({ permission: "granted" });
  openApp();
  await waitFor(() => expect(getUserMedia).toHaveBeenCalledWith(ASKED));
  expect(await (await findMySeat()).findByText("Starting…")).toBeInTheDocument();
});

it("shows Turn on camera again when Chrome's permission is gone, without asking", async () => {
  window.localStorage.setItem(REMEMBERED, "on");
  const { getUserMedia, query } = pretendChrome({ permission: "prompt" });
  openApp();
  await waitFor(() => expect(query).toHaveBeenCalledWith({ name: "camera" }));
  await settle();
  expect(getUserMedia).not.toHaveBeenCalled();
  expect(mySeat().getByRole("button", { name: "Turn on camera" })).toBeInTheDocument();
});

it("forgets it on Turn off: the camera and the models stop, the desk says paused, and a reload doesn't start it", async () => {
  const { getUserMedia, tracks } = pretendChrome({ permission: "granted" });
  const { user, sent, unmount } = openApp();
  const worker = await turnOnFromSeat(user);
  worker.answer({ type: "ready", backend: "WebGPU", loadMs: 900 });

  await user.click(mySeat().getByRole("button", { name: "Turn off" }));

  expect(worker.terminated).toBe(true);
  expect(tracks.length).toBeGreaterThan(0);
  expect(tracks.every((track) => track.stop.mock.calls.length === 1)).toBe(true);
  expect(window.localStorage.getItem(REMEMBERED)).toBe("off");
  await waitFor(() => expect(sent.filter((request) => request.path === "/api/track/pause").map((request) => [request.method, request.body])).toEqual([["POST", {}]]));
  expect(mySeat().getByRole("button", { name: "Turn on camera" })).toBeInTheDocument();

  unmount();
  openApp("/", { ...NO_CAMERA, camera_paused: true });
  await (await findMySeat()).findByRole("button", { name: "Turn on camera" });
  await settle();
  expect(getUserMedia).toHaveBeenCalledTimes(1);
});

it("runs in one tab at a time: the next says so, and takes over when that tab closes", async () => {
  const { getUserMedia } = pretendChrome({ permission: "granted" });
  const first = new CameraTracker();
  const second = new CameraTracker();
  for (const tab of [first, second]) {
    tab.attach();
    tab.setSource("browser");
  }
  first.turnOn();
  await waitFor(() => expect(FakeWorker.all).toHaveLength(1));
  // In a real second tab, the first one remembering it is a storage event.
  act(() => window.dispatchEvent(new StorageEvent("storage", { key: REMEMBERED })));
  await waitFor(() => expect(second.getView().step).toBe("elsewhere"));
  expect(getUserMedia).toHaveBeenCalledTimes(1);

  first.detach(); // the tab closes
  await settle();
  await waitFor(() => expect(second.getView().step).toBe("starting"));
  await waitFor(() => expect(FakeWorker.all).toHaveLength(2));
  expect(getUserMedia).toHaveBeenCalledTimes(2);
  second.detach();
});

it("doesn't take over in the next tab once the camera was turned off", async () => {
  const { getUserMedia } = pretendChrome({ permission: "granted" });
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, headers: new Headers(), json: async () => ({}) })));
  const first = new CameraTracker();
  const second = new CameraTracker();
  for (const tab of [first, second]) {
    tab.attach();
    tab.setSource("browser");
  }
  first.turnOn();
  await waitFor(() => expect(FakeWorker.all).toHaveLength(1));
  act(() => window.dispatchEvent(new StorageEvent("storage", { key: REMEMBERED })));
  await waitFor(() => expect(second.getView().step).toBe("elsewhere"));

  first.turnOff();

  await waitFor(() => expect(second.getView().step).toBe("off"));
  await settle();
  expect(getUserMedia).toHaveBeenCalledTimes(1);
  first.detach();
  second.detach();
});

it("says Camera on in another tab on your seat while another tab has it", async () => {
  window.localStorage.setItem(REMEMBERED, "on");
  const { locks, getUserMedia } = pretendChrome({ permission: "granted" });
  void locks.request("dayanpi-camera", {}, () => new Promise(() => {})); // the other tab, never closing
  openApp("/", { ...NO_CAMERA, state: "working", camera_ok: true });
  expect(await (await findMySeat()).findByText("Camera on in another tab")).toBeInTheDocument();
  expect(getUserMedia).not.toHaveBeenCalled();
});

it("puts the camera in Settings → Camera with its load line, and a problem's fix", async () => {
  pretendChrome();
  Object.defineProperty(performance, "measureUserAgentSpecificMemory", { value: async () => ({ bytes: 52e6 }), configurable: true });
  const { user } = openApp("/settings");
  await user.click(await screen.findByRole("button", { name: "Camera" }));
  const camera = within(screen.getByRole("region", { name: "Camera" }));
  expect(camera.getByRole("status")).toHaveTextContent("Camera off");

  await user.click(camera.getByRole("button", { name: "Turn on camera" }));

  expect(await camera.findByText("Starting…")).toBeInTheDocument();
  expect(camera.getByText("Loading the models")).toBeInTheDocument();
  await waitFor(() => expect(FakeWorker.all).toHaveLength(1));
  FakeWorker.all[0].answer({ type: "ready", backend: "WebGPU", loadMs: 900 });
  FakeWorker.all[0].answer({ type: "check", ms: 142.4, pace: { intervalMs: 1000, reason: "normal" } });
  expect(await camera.findByText("142 ms a check · memory 52 MB · WebGPU")).toBeInTheDocument();
  FakeWorker.all[0].answer({ type: "check", ms: 130, pace: { intervalMs: 3000, reason: "idle" } });
  expect(camera.getByText("130 ms a check · memory 52 MB · WebGPU · Nobody's here, so it checks every 3 s")).toBeInTheDocument();
  expect(camera.getByRole("button", { name: "Turn off" })).toBeInTheDocument();

  FakeWorker.all[0].answer({ type: "failed", message: "out of memory" });
  expect(camera.getByRole("status")).toHaveTextContent("The tracker stopped");
  expect(camera.getByText("The models stopped running. Try again, or reload the page.")).toBeInTheDocument();
  expect(camera.getByRole("button", { name: "Try again" })).toBeInTheDocument();
});

it("offers Turn on camera on the Desk's line", async () => {
  const { getUserMedia } = pretendChrome();
  const { user } = openApp("/me");
  const line = await screen.findByText("No camera yet, so time isn't counted.");
  await user.click(within(line).getByRole("button", { name: "Turn on camera" }));
  await waitFor(() => expect(getUserMedia).toHaveBeenCalledWith(ASKED));
  expect(await within(line).findByText("Starting…")).toBeInTheDocument();
});

it("sends /track, the old tracker page, to the room", async () => {
  pretendChrome();
  openApp("/track");
  await waitFor(() => expect(screen.getByRole("status", { name: "Path" })).toHaveTextContent(/^\/$/));
  expect(await screen.findByRole("region", { name: "Seats" })).toBeInTheDocument();
});
