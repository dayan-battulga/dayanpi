import * as ort from "onnxruntime-web";
import { readRgba, type Picture } from "@/lib/vision/image";
import { loadModel, MODEL_NAMES } from "@/lib/vision/models";
import type { VisionModels } from "@/lib/vision/worker";

// What the camera test's workers and the tracker's worker share. Only workers import this, so ORT never lands in a
// page's own download.

export type ExecutionProvider = "webgpu" | "wasm";

// The camera's newest frame. It sends ~30 a second and only the newest is kept, and like the Pi's frame_after, a
// frame already scanned is never scanned again, so a frozen camera means "no frame".
export class FrameKeeper {
  private latest: VideoFrame | null = null;
  private isFresh = false;
  private readonly canvas = new OffscreenCanvas(1, 1);
  private readonly context = this.canvas.getContext("2d", { willReadFrequently: true }) as OffscreenCanvasRenderingContext2D;

  constructor(frames: ReadableStream<VideoFrame>) {
    void this.readFrames(frames);
  }

  grab(): Picture | null {
    let picture: Picture | null = null;
    if (this.isFresh && this.latest !== null) {
      this.isFresh = false;
      this.canvas.width = this.latest.displayWidth;
      this.canvas.height = this.latest.displayHeight;
      this.context.drawImage(this.latest, 0, 0);
      picture = readRgba(this.context.getImageData(0, 0, this.canvas.width, this.canvas.height).data, this.canvas.width, this.canvas.height);
    }
    return picture;
  }

  private async readFrames(frames: ReadableStream<VideoFrame>): Promise<void> {
    const reader = frames.getReader();
    for (let read = await reader.read(); !read.done; read = await reader.read()) {
      this.latest?.close();
      this.latest = read.value;
      this.isFresh = true;
    }
  }
}

function makeRunner(session: ort.InferenceSession) {
  const run = async (input: Float32Array, dims: number[]) => {
    const results = await session.run({ [session.inputNames[0]]: new ort.Tensor("float32", input, dims) });
    return session.outputNames.map((name) => results[name].data as Float32Array);
  };
  return run;
}

// One session per model, made once. ORT fixes its thread count when it starts, so a worker only ever asks for one.
export async function openModels(provider: ExecutionProvider, threads: number): Promise<VisionModels> {
  ort.env.wasm.numThreads = threads;
  // Otherwise every session logs, as a console error, that ORT put its shape ops on the CPU on purpose. The session's
  // own logger only listens to its logSeverityLevel (3 = errors).
  ort.env.logLevel = "error";
  const options = { executionProviders: [provider], logSeverityLevel: 3 as const };
  const sessions: ort.InferenceSession[] = [];
  for (const name of [MODEL_NAMES.objects, MODEL_NAMES.palm, MODEL_NAMES.hand]) {
    sessions.push(await ort.InferenceSession.create(new Uint8Array(await loadModel(name)), options));
  }
  const [objects, palm, hand] = sessions.map(makeRunner);
  const models = { objects, hands: { palm, hand } };
  return models;
}
