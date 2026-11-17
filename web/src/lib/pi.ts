import type { Level, PiStats, Snapshot } from "@/lib/types";

export const TEMP_ELEVATED_C = 70;
export const TEMP_CRITICAL_C = 80; // the Pi 5 starts throttling near here

export interface UptimeParts {
  first: number;
  firstUnit: string;
  second: number;
  secondUnit: string;
}

export function readLevel(value: number, elevatedAt: number, criticalAt: number): Level {
  let level: Level = "nominal";
  if (value >= criticalAt) {
    level = "critical";
  } else if (value >= elevatedAt) {
    level = "elevated";
  }
  return level;
}

// "6d 4h", or "4h 12m" under a day: two numbers, so each can roll on its own.
export function readUptime(seconds: number): UptimeParts {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const parts = days > 0 ? { first: days, firstUnit: "d", second: hours, secondUnit: "h" } : { first: hours, firstUnit: "h", second: minutes, secondUnit: "m" };
  return parts;
}

// A member's snapshot has no Pi numbers, only "focus".
export function readPiStats(snapshot: Snapshot | null): PiStats | null {
  const stats = snapshot?.throttle != null ? (snapshot as PiStats) : null;
  return stats;
}
