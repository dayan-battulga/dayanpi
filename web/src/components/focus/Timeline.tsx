import { useRef } from "react";
import { describeStartHour, layoutTimeline } from "@/lib/timeline";
import type { Segment } from "@/lib/types";

const SEGMENT_STAGGER_MS = 60;

interface TimelineProps {
  known: Segment[];
  loaded: boolean;
  now: number;
  midnight: number;
}

// The pieces on screen when the segments first load grow in one by one; later ones just appear.
export function Timeline({ known, loaded, now, midnight }: TimelineProps) {
  const layout = layoutTimeline(known, now, midnight);
  const firstPieces = useRef<Set<string> | null>(null);
  if (loaded && firstPieces.current == null) {
    firstPieces.current = new Set(layout.pieces.map((piece) => `${piece.state}@${piece.start}`));
  }
  const start = describeStartHour(layout.startHour);
  return (
    <div className="timeline-wrap">
      <div id="focus-timeline" className="timeline" role="img" aria-label={`Today, ${start} to midnight`}>
        {loaded &&
          layout.pieces.map((piece, index) => {
            const key = `${piece.state}@${piece.start}`;
            const grows = firstPieces.current?.has(key) ?? false;
            const classes = ["segment", `is-${piece.state}`, piece.live && "is-live", index === 0 && "is-first", grows && "grow"];
            return (
              <div
                key={key}
                className={classes.filter(Boolean).join(" ")}
                title={piece.title}
                style={{
                  left: `${piece.left}%`,
                  // 1px under the next one: two edges on the same fractional pixel let the track through as a hairline.
                  width: `calc(${piece.width}% + 1px)`,
                  animationDelay: grows ? `${200 + index * SEGMENT_STAGGER_MS}ms` : undefined,
                }}
              />
            );
          })}
        {loaded && <div className="now-cursor glide" style={{ left: `${layout.cursorLeft}%` }} />}
      </div>
      <div className="timeline-ends" aria-hidden="true">
        <span>{start}</span>
        <span>midnight</span>
      </div>
    </div>
  );
}
