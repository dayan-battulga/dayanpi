import { useHeldReply } from "@/hooks/useHeldReply";
import { request } from "@/lib/http";
import type { FocusStatus } from "@/lib/types";

export interface MacTracking {
  tracking: boolean;
  flipTracking: (enabled: boolean) => Promise<void>;
}

// The one copy of the Mac tracking pick, for the Mac card's switch and ⌘K. It flips right away; a failed POST goes
// back to what the Pi says, and a toast says so.
export function useMacTracking(focus: FocusStatus | undefined, now: number): MacTracking {
  const { shown, send } = useHeldReply(focus?.mac_tracking ?? true, now);
  const flipTracking = async (enabled: boolean) => {
    const ask = async () => ((await request("POST", "/api/mac/tracking", { enabled })).ok ? enabled : null);
    await send(enabled, ask, enabled ? "Couldn't resume Mac tracking" : "Couldn't pause Mac tracking");
  };
  return { tracking: shown, flipTracking };
}
