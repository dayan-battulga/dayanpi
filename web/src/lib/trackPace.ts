// How often the browser's camera checks, so a laptop running it for hours stays cool: once a second while someone's there, every
// 3 s once nobody's been seen for 10 s, and every 2 s when the laptop struggles or is on a low battery. The tracker's
// rules cope with gaps that size: they count seconds, and a gap only counts up to 5 s (the Pi's MAX_STEP_S).

export const NORMAL_INTERVAL_MS = 1000;
export const IDLE_INTERVAL_MS = 3000;
export const BUSY_INTERVAL_MS = 2000;
export const IDLE_AFTER_MS = 10_000; // the Pi's AWAY_AFTER_S: the desk says away by then anyway
// A check is a bad one when it takes this long, or starts this much later than it was due.
export const SLOW_CHECK_MS = 600;
export const LATE_BY_MS = 250;
// Busy: at least half the checks were bad over a whole minute. Back to normal after a minute with fewer.
export const BUSY_WINDOW_MS = 60_000;
export const BUSY_SHARE = 0.5;
export const LOW_BATTERY = 0.2;

export type PaceReason = "normal" | "idle" | "busy" | "battery";

export interface Pace {
  intervalMs: number;
  reason: PaceReason;
}

const INTERVALS: Record<PaceReason, number> = { normal: NORMAL_INTERVAL_MS, idle: IDLE_INTERVAL_MS, busy: BUSY_INTERVAL_MS, battery: BUSY_INTERVAL_MS };

export class CheckPacer {
  private lastSeenAt: number;
  private lastStartAt: number | null = null;
  private dueGapMs = NORMAL_INTERVAL_MS;
  private windowStart: number;
  private checks = 0;
  private bad = 0;
  private busy = false;
  private lowBattery = false;

  constructor(now: number) {
    this.lastSeenAt = now;
    this.windowStart = now;
  }

  // After every check: when it started, how long it took, and whether it saw someone.
  record(startedAt: number, ms: number, sawPerson: boolean): void {
    const late = this.lastStartAt !== null && startedAt - this.lastStartAt > this.dueGapMs + LATE_BY_MS;
    this.lastStartAt = startedAt;
    this.lastSeenAt = sawPerson ? startedAt : this.lastSeenAt;
    this.checks += 1;
    this.bad += late || ms > SLOW_CHECK_MS ? 1 : 0;
    if (startedAt - this.windowStart >= BUSY_WINDOW_MS) {
      this.busy = this.bad / this.checks >= BUSY_SHARE;
      this.windowStart = startedAt;
      this.checks = 0;
      this.bad = 0;
    }
  }

  // Low and not plugged in. The page reads the battery, since a worker can't.
  setLowBattery(low: boolean): void {
    this.lowBattery = low;
  }

  // The wait before the next check, counted from this one's start.
  pace(now: number): Pace {
    const reason: PaceReason = now - this.lastSeenAt >= IDLE_AFTER_MS ? "idle" : this.lowBattery ? "battery" : this.busy ? "busy" : "normal";
    this.dueGapMs = INTERVALS[reason];
    const pace = { intervalMs: INTERVALS[reason], reason };
    return pace;
  }
}
