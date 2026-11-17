import * as ort from "onnxruntime-web";
import { findBestConfidence } from "@/lib/vision/detector";
import { GestureTracker, readSign } from "@/lib/vision/gestures";
import { readRgba, type Picture } from "@/lib/vision/image";
import { loadModel, MODEL_NAMES } from "@/lib/vision/models";
import { readFrame, type VisionModels } from "@/lib/vision/worker";
import { CHECK_INTERVAL_MS, startLoop, type StartRequest, type WorkerReply, type WorkerRequest } from "@/lib/trackTest";

// One backend's checks for the camera test: its own ORT (the thread count is fixed once ORT starts, which is why
// each backend gets its own worker), the camera's frames, and the Pi's pipeline once a second, on this worker's
// timer or on the page's ticks.

let latestFrame: VideoFrame | null = null;
let isFresh = false;
let models: VisionModels | null = null;
const signs = new GestureTracker();
const canvas = new OffscreenCanvas(1, 1);
const context = canvas.getContext("2d", { willReadFrequently: true }) as OffscreenCanvasRenderingContext2D;

function reply(message: WorkerReply): void {
  self.postMessage(message);
}

// The camera sends ~30 frames a second; only the newest is kept.
async function readFrames(frames: ReadableStream<VideoFrame>): Promise<void> {
  const reader = frames.getReader();
  for (let read = await reader.read(); !read.done; read = await reader.read()) {
    latestFrame?.close();
    latestFrame = read.value;
    isFresh = true;
  }
}

// Like the Pi's frame_after: a frame already scanned is never scanned again, so a frozen camera means "no frame".
function grabPicture(): Picture | null {
  let picture: Picture | null = null;
  if (isFresh && latestFrame !== null) {
    isFresh = false;
    canvas.width = latestFrame.displayWidth;
    canvas.height = latestFrame.displayHeight;
    context.drawImage(latestFrame, 0, 0);
    picture = readRgba(context.getImageData(0, 0, canvas.width, canvas.height).data, canvas.width, canvas.height);
  }
  return picture;
}

async function runCheck(): Promise<void> {
  const started = performance.now();
  try {
    const picture = grabPicture();
    const reading = picture === null || models === null ? null : await readFrame(picture, models);
    const at = performance.timeOrigin + started;
    reply({
      type: "check",
      at,
      ms: performance.now() - started,
      fresh: reading !== null,
      person: reading === null ? 0 : findBestConfidence(reading.people),
      phone: reading === null ? 0 : findBestConfidence(reading.phones),
      sign: signs.hold(reading === null ? null : readSign(reading.hands), at / 1000),
      handsFailed: reading?.handsFailed ?? false,
    });
  } catch (error) {
    reply({ type: "failed", message: String(error) });
  }
}

function makeRunner(session: ort.InferenceSession) {
  const run = async (input: Float32Array, dims: number[]) => {
    const results = await session.run({ [session.inputNames[0]]: new ort.Tensor("float32", input, dims) });
    return session.outputNames.map((name) => results[name].data as Float32Array);
  };
  return run;
}

async function start(request: StartRequest): Promise<void> {
  try {
    const loadStarted = performance.now();
    ort.env.wasm.numThreads = request.threads;
    // Otherwise every session logs, as a console error, that ORT put its shape ops on the CPU on purpose.
    ort.env.logLevel = "error";
    const options = { executionProviders: [request.backend === "webgpu" ? "webgpu" : "wasm"] };
    const sessions: ort.InferenceSession[] = [];
    for (const name of [MODEL_NAMES.objects, MODEL_NAMES.palm, MODEL_NAMES.hand]) {
      sessions.push(await ort.InferenceSession.create(new Uint8Array(await loadModel(name)), options));
    }
    const [objects, palm, hand] = sessions.map(makeRunner);
    models = { objects, hands: { palm, hand } };
    void readFrames(request.frames);
    reply({ type: "ready", loadMs: performance.now() - loadStarted });
    if (request.loop === "worker") {
      startLoop(runCheck, CHECK_INTERVAL_MS);
    }
  } catch (error) {
    reply({ type: "failed", message: String(error) });
  }
}

function handleRequest(event: MessageEvent<WorkerRequest>): void {
  const request = event.data;
  if (request.type === "start") {
    void start(request);
  } else {
    void runCheck();
  }
}

// ORT's threads start this same script as their own workers, named em-pthread; their messages are ORT's.
if (!self.name.startsWith("em-pthread")) {
  self.onmessage = handleRequest;
}
