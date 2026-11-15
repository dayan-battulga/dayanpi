import { useRef } from "react";
import { layoutTimeline } from "@/lib/timeline";
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
  return (
    <div className="timeline-wrap">
      <div id="focus-timeline" className="timeline" role="img" aria-label="Today's timeline">
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
                  width: `${piece.width}%`,
                  animationDelay: grows ? `${200 + index * SEGMENT_STAGGER_MS}ms` : undefined,
                }}
              />
            );
          })}
        {loaded && <div className="now-cursor glide" style={{ left: `${layout.cursorLeft}%` }} />}
      </div>
      <div id="focus-hours" className="timeline-hours mono" aria-hidden="true">
        {layout.hours.map(({ hour, left }) => (
          <span key={hour} style={{ left: `${left}%` }}>
            {hour}
          </span>
        ))}
      </div>
    </div>
  );
}
