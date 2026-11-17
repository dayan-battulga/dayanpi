import { formatDuration } from "@/lib/format";
import { formatTodoTime } from "@/lib/room";
import { describeStartHour, layoutTimeline, mergeKnownSegments, readLocalMidnight } from "@/lib/timeline";
import type { Segment, TheirDesk, Todos } from "@/lib/types";

// Someone's day as a still bar (no shine: other people's changes never loop), with its ends under it and, in the peek,
// their focused time in the middle.
export function DayBar({ segments, now, middle }: { segments: Segment[]; now: number; middle?: string }) {
  const midnight = readLocalMidnight(now);
  const layout = layoutTimeline(mergeKnownSegments(segments, midnight), now, midnight);
  return (
    <>
      <div className="their-bar" aria-hidden="true">
        {layout.pieces.map((piece) => (
          <span key={`${piece.state}@${piece.start}`} className={`segment is-${piece.state}`} style={{ left: `${piece.left}%`, width: `calc(${piece.width}% + 1px)` }} />
        ))}
      </div>
      <div className="their-bar-ends">
        <span>{describeStartHour(layout.startHour)}</span>
        {middle != null && <span>{middle}</span>}
        <span>midnight</span>
      </div>
    </>
  );
}

// Their to-dos, open first, then the ones done today: the current one ringed and bold, done ones filled and struck.
export function TheirTodoList({ todos }: { todos: Todos }) {
  const rows = [...todos.open.map((item) => ({ item, kind: item.id === todos.current ? "current" : "open" })), ...todos.done.map((item) => ({ item, kind: "done" }))];
  return (
    <ul className="their-todos">
      {rows.map(({ item, kind }) => (
        <li key={item.id} className="their-todo" data-kind={kind}>
          <span className="their-todo-mark" aria-hidden="true" />
          <span className="their-todo-text">
            {item.text}
            {kind !== "open" && <span className="sr-only">{kind === "done" ? " (done)" : " (working on it)"}</span>}
          </span>
          <span className="their-todo-time">{formatTodoTime(item.seconds)}</span>
        </li>
      ))}
    </ul>
  );
}

// "1 of 4 done"
export function describeDone(todos: Todos): string {
  return `${todos.done.length} of ${todos.open.length + todos.done.length} done`;
}

// Their apps today: each bar its share of the longest, with a browser's YouTube part first in --hot when they share
// sites (the Pi only sends app_youtube then).
export function AppBars({ desk, limit }: { desk: TheirDesk; limit: number }) {
  const apps = (desk.apps ?? []).slice(0, limit);
  const longest = Math.max(1, ...apps.map((row) => row.total_seconds));
  return apps.map((row) => {
    const youtube = desk.app_youtube?.[row.app] ?? 0;
    return (
      <div key={row.app} className="their-app">
        <div className="their-app-head">
          <span>{row.app}</span>
          <span className="their-app-time">
            {formatDuration(row.total_seconds)}
            {youtube > 0 && ` · ${formatDuration(youtube)} YouTube`}
          </span>
        </div>
        <div className="their-app-track" aria-hidden="true">
          <span className="their-app-bar" style={{ width: `${(100 * row.total_seconds) / longest}%` }}>
            {youtube > 0 && <span className="their-app-youtube" style={{ flexGrow: youtube }} />}
            <span className="their-app-rest" style={{ flexGrow: row.total_seconds - youtube }} />
          </span>
        </div>
      </div>
    );
  });
}
