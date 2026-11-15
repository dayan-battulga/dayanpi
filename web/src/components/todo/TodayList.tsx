import { formatTimeOfDay } from "@/lib/format";
import { buildTodayItems, describeLength } from "@/lib/timeline";
import type { Segment } from "@/lib/types";

const ROW_STAGGER_MS = 60;

// Today's last few state changes, newest first. The open one's length keeps ticking.
export function TodayList({ known, now }: { known: Segment[]; now: number }) {
  const items = buildTodayItems(known);
  // Keyed by the whole list, so a new change re-plays the rise on every row, like before.
  const signature = items.map((item) => item.key).join("|");
  return (
    <ol id="today-list" className="today-list">
      {items.length === 0 ? (
        <li className="today-empty muted">Nothing yet today.</li>
      ) : (
        items.map((item, index) => (
          <li key={`${signature}#${index}`} style={{ animationDelay: `${index * ROW_STAGGER_MS}ms` }}>
            <span className="today-time mono">{formatTimeOfDay(item.at)}</span>
            <span className={`today-dot is-${item.kind}`}></span>
            <span className="today-what">{item.title}</span>
            <span className="today-meta mono">{describeLength(item.segment, now)}</span>
          </li>
        ))
      )}
    </ol>
  );
}
