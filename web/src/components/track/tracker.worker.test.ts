import { afterEach, expect, it, vi } from "vitest";

// The worker's models and frames, so nothing here needs a GPU or a camera.
const { openModels } = vi.hoisted(() => ({ openModels: vi.fn() }));
vi.mock("@/components/track/workerKit", () => ({
  openModels,
  FrameKeeper: class {
    shrinkToPicture = async () => "SlBFRw==";
  },
}));

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("loads no models for a picture-only camera, and sends the picture alone once a second when the Pi asks for it", async () => {
  vi.useFakeTimers();
  const replies = vi.spyOn(window, "postMessage").mockImplementation(() => {});
  const fetch = vi.fn(async (_path: string, _init: RequestInit) => new Response(JSON.stringify({ state: "working", send_picture: true })));
  vi.stubGlobal("fetch", fetch);
  await import("@/components/track/tracker.worker");

  window.dispatchEvent(new MessageEvent("message", { data: { type: "start", frames: {}, lowBattery: false, pictureOnly: true } }));
  await vi.advanceTimersByTimeAsync(0);
  await vi.advanceTimersByTimeAsync(1000);

  expect(openModels).not.toHaveBeenCalled();
  expect(replies).toHaveBeenCalledWith({ type: "ready", backend: null, loadMs: 0 });
  expect(fetch.mock.calls.map(([path, init]) => [path, JSON.parse(String(init.body))])).toEqual([
    ["/api/track/picture", { picture: null }], // asks first, like a reading
    ["/api/track/picture", { picture: "SlBFRw==" }],
  ]);
});
