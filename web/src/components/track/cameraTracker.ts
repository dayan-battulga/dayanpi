import { request, sendToLogin } from "@/lib/http";
import { STORAGE_PREFIX, readStored, writeStored } from "@/lib/storage";
import type { TrackerReply } from "@/lib/track";
import { LOW_BATTERY, type PaceReason } from "@/lib/trackPace";
import type { Spoken } from "@/lib/types";

// The browser's camera, for every page inside the frame (hooks/useCamera keeps one per frame): Chrome is only asked on
// a click, then the tracker's worker (tracker.worker.ts) runs the models and sends the Pi each check's numbers, and the
// video never leaves this computer. It comes back by itself when this browser remembers it was on and Chrome still
// allows the camera, and only one dayanpi tab runs it (Web Locks): the others wait in line and the next one takes over
// when that tab closes.

export type CameraProblem = "chrome" | "denied" | "missing" | "busy";
export type CameraStep = "off" | "starting" | "on" | "elsewhere" | "problem";
export type CameraTrouble = CameraProblem | "failed";
export type CameraSource = "pi" | "browser" | undefined;

export interface CameraStart {
  stream: MediaStream | null;
  problem: CameraProblem | null;
}

export interface CameraSize {
  width: number;
  height: number;
}

export interface CameraLoad {
  ms: number | null;
  memory: number | null;
  backend: string | null;
  reason: PaceReason;
}

export interface CameraView {
  step: CameraStep;
  problem: CameraTrouble | null;
  preview: MediaStream | null; // the camera itself, for your own seat
  load: CameraLoad;
  spoken: Spoken | null; // from the Pi's answers to the readings, so a hidden tab, whose stream is closed, still plays a clip
}

// The camera test times the Pi's own 640x480 (a laptop that can't do it sends what it has, and the pipeline letterboxes
// it). This camera asks for 1280x720, for the seat's picture; the checks still look at 640x480 at most (workerKit's
// grab).
export const TEST_CAMERA: CameraSize = { width: 640, height: 480 };
export const TRACKER_CAMERA: CameraSize = { width: 1280, height: 720 };
const LOCK_NAME = "dayanpi-camera";
const REMEMBERED = "camera"; // "on" while this browser should bring the camera back
const MEMORY_EVERY_MS = 60_000;
const NO_LOAD: CameraLoad = { ms: null, memory: null, backend: null, reason: "normal" };
const OFF: CameraView = { step: "off", problem: null, preview: null, load: NO_LOAD, spoken: null };

function readCameraProblem(error: unknown): CameraProblem {
  const name = error instanceof DOMException ? error.name : "";
  const problem = name === "NotAllowedError" || name === "SecurityError" ? "denied" : name === "NotReadableError" || name === "AbortError" ? "busy" : "missing";
  return problem;
}

export async function openCamera(size: CameraSize = TEST_CAMERA): Promise<CameraStart> {
  let start: CameraStart = { stream: null, problem: "chrome" };
  // The worker gets frames through this, and only Chrome has it.
  if (typeof MediaStreamTrackProcessor !== "undefined") {
    try {
      const constraints = { video: { width: { ideal: size.width }, height: { ideal: size.height } }, audio: false };
      start = { stream: await navigator.mediaDevices.getUserMedia(constraints), problem: null };
    } catch (error) {
      // No navigator.mediaDevices at all lands here too, as a missing camera.
      start = { stream: null, problem: readCameraProblem(error) };
    }
  }
  return start;
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

function isRemembered(): boolean {
  return readStored(REMEMBERED, null) === "on";
}

async function isCameraAllowed(): Promise<boolean> {
  let allowed = false;
  try {
    allowed = (await navigator.permissions.query({ name: "camera" as PermissionName })).state === "granted";
  } catch {
    // No permissions API, or one that doesn't know "camera": the button asks instead.
  }
  return allowed;
}

// Low and not plugged in. Chrome has a battery to ask; a desktop without one is never low.
function isLowBattery(battery: BatteryManager | null): boolean {
  const low = battery !== null && !battery.charging && battery.level < LOW_BATTERY;
  return low;
}

export class CameraTracker {
  private view: CameraView = OFF;
  private readonly listeners = new Set<() => void>();
  private source: CameraSource = undefined;
  // Bumped on every attach and detach, so an answer that comes back after the frame unmounted does nothing.
  private generation = 0;
  private attached = false;
  private claiming = false; // between asking for the lock and starting or giving up
  private waiting: AbortController | null = null; // our place in line while another tab has the camera
  private letGo: (() => void) | null = null; // ends the lock's callback, which lets the next tab in line have it
  private worker: Worker | null = null;
  private tracks: MediaStreamTrack[] = [];
  private battery: BatteryManager | null = null;
  private memoryTimer: number | undefined = undefined;

  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };

  getView = () => this.view;

  attach = () => {
    this.attached = true;
    this.generation += 1;
    window.addEventListener("storage", this.handleStorage);
    this.resume();
  };

  // Unmounting stops everything and lets go of the lock, but keeps it remembered: the next page load brings it back.
  detach = () => {
    this.attached = false;
    this.generation += 1;
    this.claiming = false;
    window.removeEventListener("storage", this.handleStorage);
    this.stopCamera();
    this.update(OFF);
  };

  // The desk's camera_source from the stream. Only a desk on the browser runs this camera.
  setSource = (source: CameraSource) => {
    this.source = source;
    if (source === "pi") {
      this.stopCamera();
      this.update(OFF);
    } else {
      this.resume();
    }
  };

  // The click: this is what asks Chrome for the camera.
  turnOn = () => {
    if (this.attached && !this.claiming && (this.view.step === "off" || this.view.step === "problem")) {
      this.claim(true);
    }
  };

  // Today's Pause: the camera and the models stop, the desk says paused, and this browser forgets it was on.
  turnOff = () => {
    // Before letting go of the lock, so the tab next in line sees it's off.
    writeStored(REMEMBERED, "off");
    this.stopCamera();
    this.update(OFF);
    void request("POST", "/api/track/pause", {});
  };

  private update(changes: Partial<CameraView>): void {
    this.view = { ...this.view, ...changes };
    this.listeners.forEach((listener) => listener());
  }

  private readonly handleStorage = (event: StorageEvent) => {
    if (event.key === STORAGE_PREFIX + REMEMBERED) {
      this.resume();
    }
  };

  // Without a click: only when this browser remembers the camera was on, and only for a desk on the browser.
  private resume(): void {
    if (this.attached && !this.claiming && this.source === "browser" && this.view.step === "off" && isRemembered()) {
      this.claim(false);
    }
  }

  private claim(clicked: boolean): void {
    const generation = this.generation;
    this.claiming = true;
    if (navigator.locks === undefined) {
      void this.runWithLock(true, clicked, generation);
    } else {
      void navigator.locks.request(LOCK_NAME, { ifAvailable: true }, (lock) => this.runWithLock(lock !== null, clicked, generation));
    }
  }

  // Another tab has the camera: wait in line, and when it lets go (closed, or turned off) take over if it's still on.
  private waitInLine(generation: number): void {
    const waiting = new AbortController();
    this.waiting = waiting;
    navigator.locks
      .request(LOCK_NAME, { signal: waiting.signal }, () => {
        this.waiting = null;
        return this.runWithLock(true, false, generation);
      })
      .catch(() => {
        // Left the line: the frame unmounted, or the desk went to the Pi's cameras.
      });
  }

  // The lock's callback: the lock is ours until the promise it returns settles, which is when the camera stops.
  private async runWithLock(held: boolean, clicked: boolean, generation: number): Promise<void> {
    const wanted = held && (clicked || (isRemembered() && (await isCameraAllowed())));
    const current = generation === this.generation && this.source === "browser";
    if (!held && current) {
      this.claiming = false;
      this.update({ ...OFF, step: "elsewhere" });
      this.waitInLine(generation);
    } else if (wanted && current) {
      const stopped = new Promise<void>((resolve) => {
        this.letGo = resolve;
      });
      const started = await this.startCamera(generation);
      this.settleClaim(generation);
      if (started) {
        await stopped;
      }
    } else {
      this.settleClaim(generation);
      // Remembered, but Chrome doesn't allow the camera anymore (or it was turned off in another tab): the button again.
      if (current) {
        this.update(OFF);
      }
    }
  }

  // A claim from before the frame last unmounted leaves the newer one alone.
  private settleClaim(generation: number): void {
    if (generation === this.generation) {
      this.claiming = false;
    }
  }

  private async startCamera(generation: number): Promise<boolean> {
    this.update({ ...OFF, step: "starting" });
    const battery = (await navigator.getBattery?.().catch(() => null)) ?? null;
    const opened = await openCamera(TRACKER_CAMERA);
    const current = generation === this.generation && this.source === "browser";
    if (!current || opened.stream === null) {
      opened.stream?.getTracks().forEach((track) => track.stop());
      if (current) {
        this.update({ ...OFF, step: "problem", problem: opened.problem ?? "missing" });
      }
    } else {
      writeStored(REMEMBERED, "on");
      const [track] = opened.stream.getVideoTracks();
      const copy = track.clone();
      const frames = new (MediaStreamTrackProcessor as NonNullable<typeof MediaStreamTrackProcessor>)({ track: copy }).readable;
      // The models and ONNX Runtime only load here, in the worker, never for someone whose camera is off.
      const worker = new Worker(new URL("./tracker.worker.ts", import.meta.url), { type: "module", name: "tracker" });
      worker.onmessage = (event: MessageEvent<TrackerReply>) => this.handleReply(event.data);
      worker.onerror = () => this.stopWith("failed");
      worker.postMessage({ type: "start", frames, lowBattery: isLowBattery(battery) }, [frames]);
      if (battery !== null) {
        // Assigned, not added: Chrome hands back the same battery every time.
        battery.onlevelchange = battery.onchargingchange = () => worker.postMessage({ type: "battery", low: isLowBattery(battery) });
      }
      this.worker = worker;
      this.tracks = [track, copy];
      this.battery = battery;
      this.update({ preview: opened.stream });
    }
    return current && opened.stream !== null;
  }

  private handleReply(reply: TrackerReply): void {
    if (reply.type === "ready") {
      this.update({ step: "on", load: { ...this.view.load, backend: reply.backend } });
      this.watchMemory();
    } else if (reply.type === "check") {
      this.update({ load: { ...this.view.load, ms: reply.ms, reason: reply.pace.reason } });
    } else if (reply.type === "tracked") {
      this.update({ spoken: reply.spoken ?? null });
    } else if (reply.type === "signed-out") {
      sendToLogin();
    } else {
      // A 409: the desk went to the Pi's cameras, which the stream will say too.
      this.stopWith(reply.type === "refused" ? null : "failed");
    }
  }

  private stopWith(problem: CameraTrouble | null): void {
    this.stopCamera();
    this.update(problem === null ? OFF : { ...OFF, step: "problem", problem });
  }

  // The page and its workers. Chrome answers at its next garbage collection, so it lags a little.
  private watchMemory(): void {
    const measure = () =>
      void measureMemory().then((bytes) => {
        if (bytes !== null && this.worker !== null) {
          this.update({ load: { ...this.view.load, memory: bytes } });
        }
      });
    measure();
    this.memoryTimer = window.setInterval(measure, MEMORY_EVERY_MS);
  }

  private stopCamera(): void {
    this.waiting?.abort();
    this.waiting = null;
    this.worker?.terminate();
    this.worker = null;
    this.tracks.forEach((track) => track.stop());
    this.tracks = [];
    if (this.battery !== null) {
      this.battery.onlevelchange = this.battery.onchargingchange = null;
    }
    this.battery = null;
    window.clearInterval(this.memoryTimer);
    this.letGo?.();
    this.letGo = null;
  }
}
