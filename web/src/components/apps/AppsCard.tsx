import { useEffect, useState } from "react";
import { riseDelay } from "@/components/shared/rise";
import { formatDuration } from "@/lib/format";
import { fetchJson } from "@/lib/http";
import { readStored, writeStored } from "@/lib/storage";
import type { AppsRange, AppsReply, AppUsage } from "@/lib/types";

const REFRESH_S = 60;
const STORAGE_KEY = "apps-range";
const RANGES: { range: AppsRange; label: string; empty: string }[] = [
  { range: "today", label: "Today", empty: "Nothing from the Mac yet today" },
  { range: "week", label: "Week", empty: "Nothing from the Mac yet this week" },
];

function readSavedRange(): AppsRange {
  const saved = readStored(STORAGE_KEY, "today");
  const range = saved === "week" ? "week" : "today";
  return range;
}

function toPercent(part: number, whole: number): string {
  const percent = `${whole > 0 ? (part / whole) * 100 : 0}%`;
  return percent;
}

// One row per app in the API's order (longest first, "Other apps" last). Each bar is its share of the longest one,
// and a browser's YouTube time comes first in it.
function AppRows({ apps }: { apps: AppUsage[] }) {
  const longest = Math.max(...apps.map((entry) => entry.total_seconds));
  return (
    <ul className="app-list">
      {apps.map((entry) => {
        const youtube = entry.youtube_seconds ?? 0;
        return (
          <li key={entry.app}>
            <div className="app-line">
              <span className="app-name">{entry.app}</span>
              <span className="app-time">
                {formatDuration(entry.total_seconds)}
                {youtube > 0 && <span className="app-youtube"> · {formatDuration(youtube)} YouTube</span>}
              </span>
            </div>
            <div className="app-track" aria-hidden="true">
              <span className="app-bar" style={{ width: toPercent(entry.total_seconds, longest) }}>
                {youtube > 0 && <span className="app-bar-youtube" style={{ width: toPercent(youtube, entry.total_seconds) }} />}
              </span>
            </div>
          </li>
        );
      })}
    </ul>
  );
}

export function AppsCard({ now }: { now: number }) {
  const [range, setRange] = useState<AppsRange>(readSavedRange);
  const [loaded, setLoaded] = useState<{ range: AppsRange; apps: AppUsage[] } | null>(null);
  const refresh = Math.floor(now / REFRESH_S);

  useEffect(() => {
    let current = true;
    fetchJson<AppsReply>(`/api/apps?range=${range}`).then((reply) => {
      if (current) {
        setLoaded({ range, apps: reply?.apps ?? [] });
      }
    });
    return () => {
      current = false;
    };
  }, [range, refresh]);

  const pickRange = (next: AppsRange) => {
    setRange(next);
    writeStored(STORAGE_KEY, next);
  };
  const empty = RANGES.find((entry) => entry.range === loaded?.range)?.empty;

  // The old range stays up until the new one comes in, then its rows mount fresh and their bars grow in.
  return (
    <section id="apps" className="rise" style={riseDelay(2)} aria-labelledby="apps-title">
      <div className="apps-head">
        <h2 id="apps-title" className="section-title">
          Apps
        </h2>
        <div className="apps-range" role="group" aria-label="Time range">
          {RANGES.map((entry) => (
            <button key={entry.range} type="button" aria-pressed={range === entry.range} onClick={() => pickRange(entry.range)}>
              {entry.label}
            </button>
          ))}
        </div>
      </div>
      {loaded != null && loaded.apps.length > 0 && <AppRows key={loaded.range} apps={loaded.apps} />}
      {loaded != null && loaded.apps.length === 0 && <p className="apps-empty">{empty}</p>}
    </section>
  );
}
