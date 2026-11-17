import { useState } from "react";
import { showToast } from "@/components/ui/toaster";
import { request } from "@/lib/http";
import type { FocusStatus } from "@/lib/types";

// A snapshot built just before the switch flipped can still arrive after the reply, so the reply wins for a moment.
const SWITCH_HOLD_S = 2.5;

export interface MacTracking {
  tracking: boolean;
  flipTracking: (enabled: boolean) => Promise<void>;
}

// The one copy of the Mac tracking pick, for the Mac card's switch and ⌘K. It flips right away; a failed POST drops
// the hold, so it goes back to what the Pi says, and a toast says so.
export function useMacTracking(focus: FocusStatus | undefined, now: number): MacTracking {
  const [held, setHeld] = useState<{ enabled: boolean; until: number } | null>(null);
  const tracking = held != null && now < held.until ? held.enabled : (focus?.mac_tracking ?? true);
  const flipTracking = async (enabled: boolean) => {
    setHeld({ enabled, until: Infinity });
    const reply = await request("POST", "/api/mac/tracking", { enabled });
    setHeld(reply.ok ? { enabled, until: Date.now() / 1000 + SWITCH_HOLD_S } : null);
    if (!reply.ok) {
      showToast(enabled ? "Couldn't resume Mac tracking" : "Couldn't pause Mac tracking");
    }
  };
  return { tracking, flipTracking };
}
