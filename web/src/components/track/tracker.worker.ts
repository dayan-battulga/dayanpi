import { FrameKeeper, openModels } from "@/components/track/workerKit";
import { makeBoxes, type TrackerReply, type TrackerRequest } from "@/lib/track";
import { CheckPacer, type Pace } from "@/lib/trackPace";
import { startLoop } from "@/lib/trackTest";
import { findBestConfidence } from "@/lib/vision/detector";
import { readSign } from "@/lib/vision/gestures";
import { readFrame, type VisionModels } from "@/lib/vision/worker";

// The tracker's checks: the Pi's pipeline on this worker's own timer (part 1 showed it keeps one a second in a hidden
// tab, where the page's timer drops to one every 2 s), and each check's numbers straight to the Pi from here, so a
// throttled page can't hold them up. Only numbers leave this worker, never a picture.

const PERSON_MIN = 0.5; // the tracker's
const MAX_THREADS = 2; // light enough to run for hours; part 1 had 2 threads close to 4
const READING_MS_MAX = 60_000; // the Pi's

let frames: FrameKeeper | null = null;
let models: VisionModels | null = null;
let pacer: CheckPacer | null = null;
let pace: Pace = { intervalMs: 1000, reason: "normal" };
let isSending = false;

function reply(message: TrackerReply): void {
  self.postMessage(message);
}

// WebGPU when there's a GPU and its sessions start (part 1: the fastest), WASM otherwise.
async function openBestModels(): Promise<{ models: VisionModels; backend: string }> {
  const threads = crossOriginIsolated ? Math.min(MAX_THREADS, navigator.hardwareConcurrency) : 1;
  const adapter = await navigator.gpu?.requestAdapter().catch(() => null);
  const gpu = adapter ? await openModels("webgpu", threads).catch(() => null) : null;
  const opened = gpu !== null ? { models: gpu, backend: "WebGPU" } : { models: await openModels("wasm", threads), backend: `WASM, ${threads} thread${threads === 1 ? "" : "s"}` };
  return opened;
}

// One reading in flight at a time: one that would overtake a slow one is dropped, and the Pi's ticks cover the gap.
async function sendReading(body: object): Promise<void> {
  if (!isSending) {
    isSending = true;
    try {
      const response = await fetch("/api/track/reading", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (response.ok) {
        reply({ type: "tracked", ...(await response.json()) });
      } else if (response.status === 401) {
        reply({ type: "signed-out" });
      } else if (response.status === 409) {
        reply({ type: "refused" });
      }
    } catch {
      // Offline for a moment: the next check tries again.
    } finally {
      isSending = false;
    }
  }
}

async function runCheck(): Promise<void> {
  const started = performance.now();
  const picture = frames?.grab() ?? null;
  if (picture !== null && models !== null && pacer !== null) {
    try {
      const reading = await readFrame(picture, models);
      const person = findBestConfidence(reading.people);
      const ms = performance.now() - started;
      void sendReading({ person, phone: findBestConfidence(reading.phones), sign: readSign(reading.hands), elapsed_ms: Math.min(ms, READING_MS_MAX) });
      pacer.record(started, ms, person >= PERSON_MIN);
      pace = pacer.pace(performance.now());
      reply({ type: "check", ms, boxes: makeBoxes(reading, picture.width, picture.height), pace });
    } catch (error) {
      reply({ type: "failed", message: String(error) });
    }
  }
}

async function start(request: Extract<TrackerRequest, { type: "start" }>): Promise<void> {
  try {
    const loadStarted = performance.now();
    const opened = await openBestModels();
    models = opened.models;
    frames = new FrameKeeper(request.frames);
    pacer = new CheckPacer(performance.now());
    pacer.setLowBattery(request.lowBattery);
    reply({ type: "ready", backend: opened.backend, loadMs: performance.now() - loadStarted });
    startLoop(runCheck, () => pace.intervalMs);
  } catch (error) {
    reply({ type: "failed", message: String(error) });
  }
}

function handleRequest(event: MessageEvent<TrackerRequest>): void {
  const request = event.data;
  if (request.type === "start") {
    void start(request);
  } else {
    pacer?.setLowBattery(request.low);
  }
}

// ORT's threads start this same script as their own workers, named em-pthread; their messages are ORT's.
if (!self.name.startsWith("em-pthread")) {
  self.onmessage = handleRequest;
}
