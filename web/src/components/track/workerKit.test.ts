import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { FrameKeeper } from "@/components/track/workerKit";

vi.mock("onnxruntime-web", () => ({})); // the model sessions aren't part of this

// A 2D context that writes down everything asked of it, including anything that would flip the picture.
class FakeContext {
  calls: unknown[][] = [];
  drawImage(...args: unknown[]) {
    this.calls.push(["drawImage", ...args]);
  }
  scale(...args: unknown[]) {
    this.calls.push(["scale", ...args]);
  }
  setTransform(...args: unknown[]) {
    this.calls.push(["setTransform", ...args]);
  }
  transform(...args: unknown[]) {
    this.calls.push(["transform", ...args]);
  }
  getImageData(_x: number, _y: number, width: number, height: number) {
    return { data: new Uint8ClampedArray(width * height * 4) };
  }
}

const contexts: FakeContext[] = [];

class FakeOffscreenCanvas {
  context = new FakeContext();
  constructor(
    public width: number,
    public height: number,
  ) {
    contexts.push(this.context);
  }
  getContext() {
    return this.context;
  }
  async convertToBlob() {
    return new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xd9])], { type: "image/jpeg" });
  }
}

beforeEach(() => {
  vi.stubGlobal("OffscreenCanvas", FakeOffscreenCanvas);
  vi.stubGlobal("createImageBitmap", async () => ({ close() {} }));
});

afterEach(() => {
  vi.unstubAllGlobals();
  contexts.length = 0;
});

it("never flips the frames the models check or the picture the Pi gets: the mirror is only on screen", async () => {
  const frame = { displayWidth: 1280, displayHeight: 720, close: vi.fn() };
  const frames = new ReadableStream({
    start(controller) {
      controller.enqueue(frame);
    },
  });
  const keeper = new FrameKeeper(frames as ReadableStream<VideoFrame>);
  await new Promise((resolve) => setTimeout(resolve, 0));

  expect(await keeper.grab()).not.toBeNull();
  expect(await keeper.shrinkToPicture()).not.toBeNull();

  const asked = contexts.flatMap((context) => context.calls);
  expect(asked.map(([name]) => name)).toEqual(["drawImage", "drawImage"]); // no scale or transform anywhere
  expect(asked.every((call) => call.slice(2).every((value) => typeof value !== "number" || value >= 0))).toBe(true); // no negative widths
});
