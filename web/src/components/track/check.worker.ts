import { FrameKeeper, openModels } from "@/components/track/workerKit";
import { findBestConfidence } from "@/lib/vision/detector";
import { GestureTracker, readSign } from "@/lib/vision/gestures";
import { readFrame, type VisionModels } from "@/lib/vision/worker";
import { CHECK_INTERVAL_MS, startLoop, type StartRequest, type WorkerReply, type WorkerRequest } from "@/lib/trackTest";

// One backend's checks for the camera test: its own ORT (the thread count is fixed once ORT starts, which is why
// each backend gets its own worker), the camera's frames, and the Pi's pipeline once a second, on this worker's
// timer or on the page's ticks.

let frames: FrameKeeper | null = null;
let models: VisionModels | null = null;
const signs = new GestureTracker();

function reply(message: WorkerReply): void {
  self.postMessage(message);
}

async function runCheck(): Promise<void> {
  const started = performance.now();
  try {
    const picture = frames?.grab() ?? null;
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

async function start(request: StartRequest): Promise<void> {
  try {
    const loadStarted = performance.now();
    models = await openModels(request.backend === "webgpu" ? "webgpu" : "wasm", request.threads);
    frames = new FrameKeeper(request.frames);
    reply({ type: "ready", loadMs: performance.now() - loadStarted });
    if (request.loop === "worker") {
      startLoop(runCheck, () => CHECK_INTERVAL_MS);
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
