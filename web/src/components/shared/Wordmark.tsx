import { findLampColor } from "@/hooks/useTabIcon";
import type { FocusState, LampColor } from "@/lib/types";

const D_STYLE = { display: "inline-block", width: "0.55em", height: "0.73em", marginRight: "0.06em", verticalAlign: "baseline", overflow: "visible" } as const;

interface WordmarkProps {
  state: FocusState | null;
  lamp?: LampColor; // your lamp color, for focused
  className?: string;
}

// "dayanpi" with the tab icon's d: the round part is a lamp in your state's color (your lamp color while focused, gray
// signed out, null), the stem runs through its right side. The lamp eases to a new color (dashboard.css
// .wordmark-lamp). Screen readers read "dayanpi". className is the place's own type: the top bar's .wordmark, or the
// desk sign's corner.
export function Wordmark({ state, lamp = "teal", className }: WordmarkProps) {
  return (
    <span className={className} role="img" aria-label="dayanpi">
      <svg className="icon-palette" viewBox="0 0 55 73" aria-hidden="true" style={D_STYLE}>
        <circle className="wordmark-lamp" cx="26" cy="47" r="26" style={{ fill: findLampColor(state, lamp) }} />
        <rect x="41" y="0" width="14" height="73" rx="7" fill="currentColor" />
      </svg>
      ayanpi
    </span>
  );
}
