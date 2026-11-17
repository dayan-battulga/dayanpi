import type { MacTracking } from "@/hooks/useMacTracking";
import type { FocusStatus } from "@/lib/types";

interface MacWords {
  lead: string; // muted
  main: string; // ink, cut short with an ellipsis when it doesn't fit
  tail: string; // muted
  action: "Pause" | "Resume" | "";
}

// Desk's mac option: app, site, paused and off. A Mac that isn't reporting has nothing to pause.
function describeMac(focus: FocusStatus, tracking: boolean): MacWords {
  let words: MacWords = { lead: "The Mac isn't reporting", main: "", tail: "", action: "" };
  if (!tracking) {
    words = { lead: "Mac tracking paused", main: "", tail: "", action: "Resume" };
  } else if (focus.app && focus.site) {
    words = { lead: "On the Mac ·", main: focus.site, tail: `in ${focus.app}`, action: "Pause" };
  } else if (focus.app) {
    words = { lead: "On the Mac ·", main: focus.app, tail: "", action: "Pause" };
  }
  return words;
}

interface MacLineProps {
  focus: FocusStatus | undefined;
  macTracking: MacTracking; // the frame's, so ⌘K's command and this button flip the same thing
  readOnly: boolean; // a member: the button is the owner's
}

// What's in front on the Mac, at the right of the Desk's stats, with the owner's Pause/Resume.
export function MacLine({ focus, macTracking, readOnly }: MacLineProps) {
  const { tracking, flipTracking } = macTracking;
  const words = focus == null ? null : describeMac(focus, tracking);
  return (
    words != null && (
      <p id="mac-line" className="mac-line">
        <span className="mac-line-quiet">{words.lead}</span>
        {words.main && <span className="mac-line-main">{words.main}</span>}
        {words.tail && <span className="mac-line-quiet">{words.tail}</span>}
        {words.action && !readOnly && (
          <button type="button" className="mac-line-button" aria-label={`${words.action} Mac tracking`} onClick={() => void flipTracking(!tracking)}>
            {words.action}
          </button>
        )}
      </p>
    )
  );
}
