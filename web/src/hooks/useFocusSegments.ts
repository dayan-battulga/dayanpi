import { useEffect, useState } from "react";
import type { Segment } from "@/lib/types";

const TIMELINE_REFRESH_MS = 60000;

export interface FocusSegments {
  segments: Segment[];
  loaded: boolean;
}

// The segments behind the timeline and the Today list: fetched on load, on every state change, and once a minute.
export function useFocusSegments(state: string | undefined): FocusSegments {
  const [result, setResult] = useState<FocusSegments>({ segments: [], loaded: false });
  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      try {
        const response = await fetch("/api/focus", { cache: "no-store" });
        const body = response.ok ? await response.json() : null;
        if (body != null && !cancelled) {
          setResult({ segments: body.segments ?? [], loaded: true });
        }
      } catch {
        // The next state change or the minute timer tries again.
      }
    };
    refresh();
    const timer = window.setInterval(refresh, TIMELINE_REFRESH_MS);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [state]);
  return result;
}
