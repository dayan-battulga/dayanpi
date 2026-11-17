import { formatClock } from "@/lib/format";

// The camera test's numbers (/track/test): how long each check takes and how far apart checks start, shared by
// the page and its check worker.

export const CHECK_INTERVAL_MS = 1000; // the Pi's CHECK_INTERVAL_S
// A check that starts this long after the one before it ran late.
export const LATE_GAP_MS = 1250;
// The first checks compile shaders and warm caches, so they don't count.
export const WARMUP_CHECKS = 3;
export const CHECKS_PER_BACKEND = 60;

export type Backend = "webgpu" | "wasm-threads" | "wasm";
export type Loop = "page" | "worker";
// visible: the tab in front. hidden: another tab, or minimized (Chrome can't tell them apart). pop-out: hidden,
// with the Pop out window open.
export type Place = "visible" | "hidden" | "pop-out";

export interface BackendChoice {
  backend: Backend;
  label: string;
  threads: number;
}

export interface CheckRecord {
  at: number; // when it started, ms since the epoch
  ms: number;
  fresh: boolean; // false: no new camera frame since the last check, so nothing was scanned
  person: number;
  phone: number;
  sign: string | null; // a hand sign that fired on this check
  handsFailed: boolean;
}

export interface StartRequest {
  type: "start";
  backend: Backend;
  threads: number;
  loop: Loop;
  frames: ReadableStream<VideoFrame>;
}

export type WorkerRequest = StartRequest | { type: "tick" };
export type WorkerReply = { type: "ready"; loadMs: number } | ({ type: "check" } & CheckRecord) | { type: "failed"; message: string };

export interface SpeedSummary {
  checks: number;
  medianMs: number;
  slowestMs: number;
  late: number;
  noFrame: number;
  personShare: number;
  handFailures: number;
}

export interface GapRecord {
  loop: Loop;
  place: Place;
  at: number;
  fresh: boolean;
}

export interface PlaceSegment {
  loop: Loop;
  place: Place;
  startedAt: number;
  endedAt: number;
  checks: number;
  medianGapMs: number;
  longestGapMs: number;
  late: number;
  noFrame: number;
}

export interface SpeedResult {
  choice: BackendChoice;
  records: CheckRecord[];
  loadMs: number | null;
  memoryBytes: number | null;
  problem: string | null;
}

export interface TestReport {
  device: string[];
  speed: SpeedResult[];
  background: { choice: BackendChoice; segments: PlaceSegment[] } | null;
}

// Once every intervalMs counted from each check's start, never two at once, like the Pi's LoopThread: a slow
// check pushes the next one back. Returns the stop.
export function startLoop(runCheck: () => Promise<void>, intervalMs: number): () => void {
  let stopped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const step = async () => {
    const started = performance.now();
    await runCheck();
    if (!stopped) {
      timer = setTimeout(step, Math.max(0, intervalMs - (performance.now() - started)));
    }
  };
  void step();
  const stop = () => {
    stopped = true;
    clearTimeout(timer);
  };
  return stop;
}

export function findMedian(values: number[]): number {
  const sorted = [...values].sort((first, second) => first - second);
  const middle = Math.floor(sorted.length / 2);
  const median = sorted.length === 0 ? 0 : sorted.length % 2 === 1 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
  return median;
}

// The checks after the warm-up. Time only counts checks that scanned a frame.
export function summarizeChecks(records: CheckRecord[]): SpeedSummary {
  const counted = records.slice(WARMUP_CHECKS);
  const scanned = counted.filter((record) => record.fresh);
  const times = scanned.map((record) => record.ms);
  const gaps = counted.slice(1).map((record, index) => record.at - counted[index].at);
  const summary = {
    checks: counted.length,
    medianMs: findMedian(times),
    slowestMs: Math.max(0, ...times),
    late: gaps.filter((gap) => gap > LATE_GAP_MS).length,
    noFrame: counted.length - scanned.length,
    personShare: scanned.length === 0 ? 0 : scanned.filter((record) => record.person >= 0.5).length / scanned.length,
    handFailures: counted.filter((record) => record.handsFailed).length,
  };
  return summary;
}

function summarizeRun(loop: Loop, run: GapRecord[], gaps: number[]): PlaceSegment {
  const segment = {
    loop,
    place: run[0].place,
    startedAt: run[0].at,
    endedAt: run[run.length - 1].at,
    checks: run.length,
    medianGapMs: findMedian(gaps),
    longestGapMs: Math.max(0, ...gaps),
    late: gaps.filter((gap) => gap > LATE_GAP_MS).length,
    noFrame: run.filter((record) => !record.fresh).length,
  };
  return segment;
}

// Each loop's checks in runs of the same place, all in time order. A check's gap is from the check before it in
// the same loop, wherever that one was.
export function splitSegments(records: GapRecord[]): PlaceSegment[] {
  const segments: PlaceSegment[] = [];
  for (const loop of ["page", "worker"] as const) {
    const mine = records.filter((record) => record.loop === loop);
    let first = 0;
    for (let index = 1; index <= mine.length; index++) {
      if (index === mine.length || mine[index].place !== mine[first].place) {
        const gaps = mine.slice(Math.max(first, 1), index).map((record, offset) => record.at - mine[Math.max(first, 1) + offset - 1].at);
        segments.push(summarizeRun(loop, mine.slice(first, index), gaps));
        first = index;
      }
    }
  }
  segments.sort((one, other) => one.startedAt - other.startedAt);
  return segments;
}

const PLACE_NAMES: Record<Place, string> = { visible: "tab in front", hidden: "other tab or minimized", "pop-out": "popped out, page hidden" };
const LOOP_NAMES: Record<Loop, string> = { page: "Page timer", worker: "Worker timer" };

const formatMs = (ms: number) => `${Math.round(ms)} ms`;
const formatSeconds = (ms: number) => `${(ms / 1000).toFixed(2)} s`;

export function describeSpeed(result: SpeedResult): string {
  const summary = summarizeChecks(result.records);
  // The very first check usually runs before the camera's first frame lands.
  const first = result.records.find((record) => record.fresh);
  const parts = [
    `median ${formatMs(summary.medianMs)}`,
    `slowest ${formatMs(summary.slowestMs)}`,
    `late ${summary.late} of ${summary.checks}`,
    `no frame ${summary.noFrame}`,
    `person seen ${Math.round(summary.personShare * 100)}%`,
    summary.handFailures > 0 ? `hand model failed ${summary.handFailures}` : null,
    first === undefined ? null : `first scan ${formatMs(first.ms)}`,
    result.loadMs === null ? null : `load ${formatSeconds(result.loadMs)}`,
    result.memoryBytes === null ? "memory n/a" : `memory ${Math.round(result.memoryBytes / 1e6)} MB`,
  ];
  const text = result.problem ?? parts.filter((part) => part !== null).join(" · ");
  return text;
}

export function describeSegment(segment: PlaceSegment): string {
  const text = [
    `${formatClock((segment.endedAt - segment.startedAt) / 1000)} ${PLACE_NAMES[segment.place]}`,
    `${segment.checks} checks`,
    `gap median ${formatSeconds(segment.medianGapMs)}, longest ${formatSeconds(segment.longestGapMs)}`,
    `late ${segment.late}`,
    `no frame ${segment.noFrame}`,
  ].join(" · ");
  return text;
}

export function describeLoop(loop: Loop): string {
  const name = LOOP_NAMES[loop];
  return name;
}

// What the Copy button copies: plain text, for a message.
export function formatReport(report: TestReport): string {
  const lines = ["dayanpi camera test", ...report.device, "", `Speed (${CHECKS_PER_BACKEND} checks each after ${WARMUP_CHECKS} warm-up, tab in front):`];
  for (const result of report.speed) {
    lines.push(`  ${result.choice.label}: ${describeSpeed(result)}`);
  }
  if (report.background !== null) {
    lines.push("", `Background (${report.background.choice.label}), in order:`);
    for (const segment of report.background.segments) {
      lines.push(`  ${describeLoop(segment.loop)}: ${describeSegment(segment)}`);
    }
  }
  const text = lines.join("\n");
  return text;
}
