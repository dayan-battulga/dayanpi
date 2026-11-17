import { AnimatePresence, m, useReducedMotionConfig } from "motion/react";
import { SPRINGS } from "@/lib/motion";
import type { FocusStatus } from "@/lib/types";

const SHOW_S = 6; // the least it stays, and all it stays with the voice off

interface PeacePillProps {
  spoken: FocusStatus["spoken"];
  receivedAt: number;
  now: number;
}

// What the peace sign is saying, in a frosted pill under the top bar: it rises in when the sign fires, stays while the
// voice says it, then fades. Every snapshot repeats the last message, so its `at` names it.
export function PeacePill({ spoken, receivedAt, now }: PeacePillProps) {
  const reduced = useReducedMotionConfig();
  const age = spoken == null ? Infinity : spoken.age_s + (now - receivedAt);
  const shown = spoken != null && (spoken.speaking || age < SHOW_S) ? spoken : null;
  // With reduced motion it only fades, and the bars stand still (dashboard.css).
  const hidden = reduced ? { opacity: 0 } : { opacity: 0, y: 10, filter: "blur(4px)" };
  return (
    <div className="peace" role="status">
      <AnimatePresence>
        {shown && (
          <m.div key={shown.at} className="peace-pill" initial={hidden} animate={{ opacity: 1, y: 0, filter: "blur(0px)", transition: { ...SPRINGS.enter, duration: 0.7 } }} exit={{ opacity: 0, transition: SPRINGS.exit }}>
            <span className="peace-bars" aria-hidden="true">
              <span />
              <span />
              <span />
              <span />
            </span>
            <p className="peace-text">{shown.text}</p>
          </m.div>
        )}
      </AnimatePresence>
    </div>
  );
}
