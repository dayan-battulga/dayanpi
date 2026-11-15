import type { Level, Snapshot, Throttle } from "@/lib/types";

export const TEMP_ELEVATED_C = 70;
export const TEMP_CRITICAL_C = 80;
export const GAUGE_MIN_C = 20;
export const GAUGE_MAX_C = 85;
export const LOAD_ELEVATED_PCT = 70;
export const LOAD_CRITICAL_PCT = 90;

export interface Described {
  text: string;
  level: Level;
}

export interface PowerReport extends Described {
  live: boolean;
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

export function readLoadLevel(percent: number): Level {
  const level = readLevel(percent, LOAD_ELEVATED_PCT, LOAD_CRITICAL_PCT);
  return level;
}

export function describePower(throttle: Throttle): PowerReport {
  const live = [
    throttle.is_undervoltage && "undervoltage",
    throttle.is_frequency_capped && "freq capped",
    throttle.is_throttled && "throttled",
  ].filter(Boolean);
  const sticky = [throttle.has_undervoltage_occured && "undervoltage", throttle.has_throttling_occured && "throttling"].filter(Boolean);
  const power: PowerReport = { text: "all clear", level: "nominal", live: live.length > 0 };
  if (live.length > 0) {
    power.text = `now: ${live.join(", ")}`;
    power.level = "critical";
  } else if (sticky.length > 0) {
    power.text = `since boot: ${sticky.join(", ")}`;
    power.level = "elevated";
  }
  return power;
}

export function describePi(stats: Snapshot, power: PowerReport): Described {
  const cpu = stats.rates == null ? 0 : stats.rates.cpu_percent;
  const summary: Described = { text: "Running smooth", level: "nominal" };
  if (power.live) {
    summary.text = "Power problem";
    summary.level = "critical";
  } else if (stats.temperature_celsius >= TEMP_CRITICAL_C) {
    summary.text = "Running hot";
    summary.level = "critical";
  } else if (stats.temperature_celsius >= TEMP_ELEVATED_C) {
    summary.text = "Running warm";
    summary.level = "elevated";
  } else if (cpu >= LOAD_CRITICAL_PCT) {
    summary.text = "Working hard";
    summary.level = "elevated";
  }
  return summary;
}
