import { useReducedMotionConfig } from "motion/react";
import type { CSSProperties } from "react";

const COLORS = ["var(--work)", "var(--phone)", "var(--away)", "var(--ink-2)"];

// Desk's renderVals piece generator: 16 pieces across the list, each with its own size, speed and delay.
const PIECES: CSSProperties[] = Array.from({ length: 16 }, (_, index) => ({
  left: `${4 + ((index * 37) % 90)}%`,
  width: index % 3 === 0 ? 6 : 8,
  height: index % 2 === 0 ? 12 : 8,
  background: COLORS[index % 4],
  animationDuration: `${1.6 + (index % 5) * 0.25}s`,
  animationDelay: `${(index % 6) * 0.12}s`,
}));

// The list's last open to-do just got checked: one burst of confetti (none with reduced motion) and a quiet line.
export function AllDone() {
  const reduced = useReducedMotionConfig();
  return (
    <>
      {!reduced && (
        <div className="confetti" aria-hidden="true">
          {PIECES.map((style, index) => (
            <span key={index} style={style} />
          ))}
        </div>
      )}
      <p className="all-done">All done. Nice.</p>
    </>
  );
}
