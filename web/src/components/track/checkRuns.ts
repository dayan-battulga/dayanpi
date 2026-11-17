import { CHECK_INTERVAL_MS, CHECKS_PER_BACKEND, startLoop, WARMUP_CHECKS, type BackendChoice, type CheckRecord, type Loop, type SpeedResult, type WorkerReply } from "@/lib/trackTest";

// The camera test's browser side: the camera, the backends this browser has, and one check worker per run.

export type CameraProblem = "chrome" | "denied" | "missing" | "busy";

export interface CameraStart {
  stream: MediaStream | null;
  problem: CameraProblem | null;
}

export interface BackendChoices {
  choices: BackendChoice[];
  gpu: string;
}

export interface CheckWorker {
  stop: () => void;
}

// A worker that hasn't answered in this long has hung, most likely while loading a model.
const STALL_MS = 120_000;

// The Pi's webcam is 640x480; a laptop that can't do it sends what it has, and the pipeline letterboxes it.
const CAMERA = { video: { width: { ideal: 640 }, height: { ideal: 480 } }, audio: false };

function readCameraProblem(error: unknown): CameraProblem {
  const name = error instanceof DOMException ? error.name : "";
  const problem = name === "NotAllowedError" || name === "SecurityError" ? "denied" : name === "NotReadableError" || name === "AbortError" ? "busy" : "missing";
  return problem;
}

export async function openCamera(): Promise<CameraStart> {
  let start: CameraStart = { stream: null, problem: "chrome" };
  // The worker gets frames through this, and only Chrome has it.
  if (typeof MediaStreamTrackProcessor !== "undefined") {
    try {
      start = { stream: await navigator.mediaDevices.getUserMedia(CAMERA), problem: null };
    } catch (error) {
      // No navigator.mediaDevices at all lands here too, as a missing camera.
      start = { stream: null, problem: readCameraProblem(error) };
    }
  }
  return start;
}

// Threads need a cross-origin isolated page; ORT's own default is half the cores, at most 4.
export async function findBackends(): Promise<BackendChoices> {
  const threads = crossOriginIsolated ? Math.min(4, Math.ceil(navigator.hardwareConcurrency / 2)) : 1;
  const adapter = await navigator.gpu?.requestAdapter().catch(() => null);
  const choices: BackendChoice[] = [];
  if (adapter) {
    choices.push({ backend: "webgpu", label: "WebGPU", threads });
  }
  if (threads > 1) {
    choices.push({ backend: "wasm-threads", label: `WASM, ${threads} threads`, threads });
  }
  choices.push({ backend: "wasm", label: "WASM, 1 thread", threads: 1 });
  const found = { choices, gpu: adapter ? `${adapter.info.vendor} ${adapter.info.architecture}`.trim() || "yes" : "none" };
  return found;
}

export async function describeDevice(track: MediaStreamTrack, gpu: string): Promise<string[]> {
  const settings = track.getSettings();
  const battery = await navigator.getBattery?.().catch(() => null);
  const power = battery == null ? "unknown" : battery.charging ? "plugged in" : "on battery";
  const lines = [
    navigator.userAgent,
    `${navigator.hardwareConcurrency} cores · ${navigator.deviceMemory ?? "?"} GB RAM · isolated: ${crossOriginIsolated ? "yes" : "no"} · power: ${power}`,
    `camera ${settings.width}x${settings.height} at ${Math.round(settings.frameRate ?? 0)} fps · GPU: ${gpu}`,
  ];
  return lines;
}

// The page, the workers and their wasm, not the GPU. Chrome answers at its next garbage collection, within ~20 s.
export async function measureMemory(): Promise<number | null> {
  let bytes: number | null = null;
  try {
    bytes = (await performance.measureUserAgentSpecificMemory?.())?.bytes ?? null;
  } catch {
    // Not isolated, or not Chrome.
  }
  return bytes;
}

// One backend's checks on its own copy of the camera. "worker" runs the loop on the worker's timer, "page" on this
// page's, asking the worker for each check.
export function startCheckWorker(track: MediaStreamTrack, choice: BackendChoice, loop: Loop, onReply: (reply: WorkerReply) => void): CheckWorker {
  const worker = new Worker(new URL("./check.worker.ts", import.meta.url), { type: "module", name: `check-${choice.backend}-${loop}` });
  const copy = track.clone();
  const frames = new (MediaStreamTrackProcessor as NonNullable<typeof MediaStreamTrackProcessor>)({ track: copy }).readable;
  let answer: (() => void) | null = null;
  let stopLoop = () => {};
  const askForCheck = () =>
    new Promise<void>((resolve) => {
      answer = resolve;
      worker.postMessage({ type: "tick" });
    });
  worker.onmessage = (event: MessageEvent<WorkerReply>) => {
    const reply = event.data;
    if (reply.type === "ready" && loop === "page") {
      stopLoop = startLoop(askForCheck, () => CHECK_INTERVAL_MS);
    }
    if (reply.type !== "ready") {
      answer?.();
      answer = null;
    }
    onReply(reply);
  };
  worker.onerror = (event) => onReply({ type: "failed", message: event.message || "the check worker didn't start" });
  worker.postMessage({ type: "start", backend: choice.backend, threads: choice.threads, loop, frames }, [frames]);
  const stop = () => {
    stopLoop();
    worker.terminate();
    copy.stop();
  };
  return { stop };
}

// The warm-up and CHECKS_PER_BACKEND checks on the worker's own timer, with the tab in front.
export function runSpeedTest(track: MediaStreamTrack, choice: BackendChoice, onCheck: (record: CheckRecord, count: number) => void): Promise<SpeedResult> {
  const finished = new Promise<SpeedResult>((resolve) => {
    const records: CheckRecord[] = [];
    let loadMs: number | null = null;
    let memory: Promise<number | null> = Promise.resolve(null);
    let stall: ReturnType<typeof setTimeout> | undefined;
    const finish = async (problem: string | null) => {
      clearTimeout(stall);
      run.stop();
      resolve({ choice, records, loadMs, memoryBytes: await memory, problem });
    };
    const watch = () => {
      clearTimeout(stall);
      stall = setTimeout(() => void finish("stopped answering for 2 minutes"), STALL_MS);
    };
    const run = startCheckWorker(track, choice, "worker", (reply) => {
      watch();
      if (reply.type === "ready") {
        loadMs = reply.loadMs;
      } else if (reply.type === "check") {
        records.push(reply);
        onCheck(reply, records.length);
        memory = records.length === WARMUP_CHECKS ? measureMemory() : memory;
        if (records.length === WARMUP_CHECKS + CHECKS_PER_BACKEND) {
          void finish(null);
        }
      } else {
        void finish(`failed: ${reply.message}`);
      }
    });
    watch();
  });
  return finished;
}
