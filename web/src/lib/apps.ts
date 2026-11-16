import type { AppUsage } from "@/lib/types";

export type TimeUnit = "minutes" | "hours";

export interface AppRow {
  app: string;
  label: string;
  // Chart values are in the axis unit; a null series is not drawn and not in the tooltip.
  youtube: number | null;
  sites: number | null;
  solid: number | null;
  // The total's label sits on the last piece that has width: a browser with no other-sites time carries it on the YouTube piece.
  sitesEndSeconds: number | null;
  youtubeEndSeconds: number | null;
  youtubeSeconds: number;
  sitesSeconds: number;
  totalSeconds: number;
  isBrowser: boolean;
}

const HOURS_ABOVE_S = 7200;
const LABEL_MAX_CHARS = 13;

export function chooseTimeUnit(apps: AppUsage[]): TimeUnit {
  const longest = Math.max(0, ...apps.map((entry) => entry.total_seconds));
  const unit = longest > HOURS_ABOVE_S ? "hours" : "minutes";
  return unit;
}

export function convertSeconds(seconds: number, unit: TimeUnit): number {
  const value = seconds / (unit === "hours" ? 3600 : 60);
  return value;
}

export function formatAxisTick(value: number, unit: TimeUnit): string {
  const text = `${Math.round(value * 10) / 10}${unit === "hours" ? "h" : "m"}`;
  return text;
}

export function shortenAppName(name: string, maxChars = LABEL_MAX_CHARS): string {
  const text = name.length > maxChars ? `${name.slice(0, maxChars - 1).trimEnd()}…` : name;
  return text;
}

// Keeps the API's order: longest first, "Other apps" last.
export function buildAppRows(apps: AppUsage[], unit: TimeUnit): AppRow[] {
  const rows = apps.map((entry) => {
    const isBrowser = entry.youtube_seconds != null;
    const youtubeSeconds = entry.youtube_seconds ?? 0;
    const sitesSeconds = entry.other_sites_seconds ?? 0;
    const row: AppRow = {
      app: entry.app,
      label: shortenAppName(entry.app),
      youtube: isBrowser ? convertSeconds(youtubeSeconds, unit) : null,
      sites: isBrowser ? convertSeconds(sitesSeconds, unit) : null,
      solid: isBrowser ? null : convertSeconds(entry.total_seconds, unit),
      sitesEndSeconds: isBrowser && sitesSeconds > 0 ? entry.total_seconds : null,
      youtubeEndSeconds: isBrowser && sitesSeconds === 0 ? entry.total_seconds : null,
      youtubeSeconds,
      sitesSeconds,
      totalSeconds: entry.total_seconds,
      isBrowser,
    };
    return row;
  });
  return rows;
}
