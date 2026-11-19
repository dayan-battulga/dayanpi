import { findLampColor } from "@/hooks/useTabIcon";
import type { FocusState } from "@/lib/types";

const D_STYLE = { display: "inline-block", width: "0.55em", height: "0.73em", marginRight: "0.06em", verticalAlign: "baseline", overflow: "visible" } as const;

// "dayanpi" with the tab icon's d: the round part is a lamp in your state's color (gray signed out, null), the stem
// runs through its right side. The lamp eases to a new color (dashboard.css .wordmark-lamp). Screen readers read
// "dayanpi". className is the place's own type: the top bar's .wordmark, or the desk sign's corner.
export function Wordmark({ state, className }: { state: FocusState | null; className?: string }) {
  return (
    <span className={className} role="img" aria-label="dayanpi">
      <svg viewBox="0 0 55 73" aria-hidden="true" style={D_STYLE}>
        <circle className="wordmark-lamp" cx="26" cy="47" r="26" fill={findLampColor(state)} />
        <rect x="41" y="0" width="14" height="73" rx="7" fill="currentColor" />
      </svg>
      ayanpi
    </span>
  );
}
