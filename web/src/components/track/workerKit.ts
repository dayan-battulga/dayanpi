import * as ort from "onnxruntime-web";
import { PICTURE_HEIGHT, PICTURE_MAX_BYTES, PICTURE_QUALITY, PICTURE_WIDTH, encodeBase64, findPictureCrop } from "@/lib/track";
import { INPUT_HEIGHT, INPUT_WIDTH } from "@/lib/vision/detector";
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
  private readonly pictureCanvas = new OffscreenCanvas(PICTURE_WIDTH, PICTURE_HEIGHT);

  constructor(frames: ReadableStream<VideoFrame>) {
    void this.readFrames(frames);
  }

  // At most the detector's 640x480: a 1280x720 camera is there for the seat's picture, so its frames are shrunk on the
  // way in, by createImageBitmap (1.5 ms; drawing it whole into this canvas took 3.2 ms, a 640x360 frame 1.7 ms).
  async grab(): Promise<Picture | null> {
    let picture: Picture | null = null;
    const frame = this.latest;
    if (this.isFresh && frame !== null) {
      this.isFresh = false;
      const scale = Math.min(1, INPUT_WIDTH / frame.displayWidth, INPUT_HEIGHT / frame.displayHeight);
      this.canvas.width = Math.round(frame.displayWidth * scale);
      this.canvas.height = Math.round(frame.displayHeight * scale);
      if (scale < 1) {
        const small = await createImageBitmap(frame, { resizeWidth: this.canvas.width, resizeHeight: this.canvas.height, resizeQuality: "low" });
        this.context.drawImage(small, 0, 0);
        small.close();
      } else {
        this.context.drawImage(frame, 0, 0);
      }
      picture = readRgba(this.context.getImageData(0, 0, this.canvas.width, this.canvas.height).data, this.canvas.width, this.canvas.height);
    }
    return picture;
  }

  // The seat's picture of the newest frame, from the camera's full size, as base64 JPEG; null before the first frame,
  // or for one over the Pi's limit, which would turn the whole reading away.
  async shrinkToPicture(): Promise<string | null> {
    let picture: string | null = null;
    const frame = this.latest;
    if (frame !== null) {
      const crop = findPictureCrop(frame.displayWidth, frame.displayHeight);
      // Drawn before the await, while this frame is still open: the reader closes it once a newer one comes.
      this.pictureCanvas.getContext("2d")?.drawImage(frame, crop.x, crop.y, crop.width, crop.height, 0, 0, PICTURE_WIDTH, PICTURE_HEIGHT);
      const blob = await this.pictureCanvas.convertToBlob({ type: "image/jpeg", quality: PICTURE_QUALITY });
      picture = blob.size <= PICTURE_MAX_BYTES ? encodeBase64(new Uint8Array(await blob.arrayBuffer())) : null;
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
