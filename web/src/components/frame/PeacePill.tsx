import { Play } from "lucide-react";
import { AnimatePresence, m, useReducedMotionConfig } from "motion/react";
import type { PeaceVoice } from "@/hooks/usePeaceVoice";
import { SPRINGS } from "@/lib/motion";
import type { Spoken } from "@/lib/types";

const SHOW_S = 6; // the least it stays, and all it stays with the voice off
const BLOCKED_S = 60; // a clip the browser wouldn't play waits for its button as long as the Pi keeps clips

interface PeacePillProps {
  spoken: Spoken | null | undefined;
  receivedAt: number;
  now: number;
  voice: PeaceVoice;
}

// What the peace sign is saying, in a frosted pill under the top bar: it rises in when the sign fires, stays while it's
// being said (the Pi's speaker, or this page's own audio going by its playing and ended events), then fades. Every
// snapshot repeats the last message, so its `at` names it. A clip the browser wouldn't play gets a play button.
export function PeacePill({ spoken, receivedAt, now, voice }: PeacePillProps) {
  const reduced = useReducedMotionConfig();
  const age = spoken == null ? Infinity : spoken.age_s + (now - receivedAt);
  const saying = spoken?.speaking === true || voice.playing;
  // A nudge plays the same way but shows as a toast (useNudgeToast), so only the peace sign's words get the pill.
  const shown = spoken != null && spoken.kind !== "nudge" && (saying || age < (voice.blocked ? BLOCKED_S : SHOW_S)) ? spoken : null;
  // With reduced motion it only fades, and the bars stand still (dashboard.css).
  const hidden = reduced ? { opacity: 0 } : { opacity: 0, y: 10, filter: "blur(4px)" };
  return (
    <div className="peace" role="status">
      <AnimatePresence>
        {shown && (
          <m.div key={shown.at} className="peace-pill" initial={hidden} animate={{ opacity: 1, y: 0, filter: "blur(0px)", transition: { ...SPRINGS.enter, duration: 0.7 } }} exit={{ opacity: 0, transition: SPRINGS.exit }}>
            {voice.blocked && !voice.playing ? (
              <button type="button" className="peace-play" aria-label="Play the message" onClick={voice.play}>
                <Play size={14} strokeWidth={1.8} aria-hidden="true" />
              </button>
            ) : (
              <span className="peace-bars" aria-hidden="true">
                <span />
                <span />
                <span />
                <span />
              </span>
            )}
            <p className="peace-text">{shown.text}</p>
          </m.div>
        )}
      </AnimatePresence>
    </div>
  );
}
