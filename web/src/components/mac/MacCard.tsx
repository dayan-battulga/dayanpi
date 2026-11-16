import { useState } from "react";
import { riseDelay } from "@/components/shared/rise";
import { Switch } from "@/components/ui/switch";
import { request } from "@/lib/http";
import type { FocusStatus } from "@/lib/types";

// A snapshot built just before the switch flipped can still arrive after the reply, so the reply wins for a moment.
const SWITCH_HOLD_S = 2.5;

async function sendMacTracking(enabled: boolean): Promise<boolean> {
  const reply = await request("POST", "/api/mac/tracking", { enabled });
  return reply.ok;
}

// The big line and the small one under it. In a browser the site is the big one, so it reads from across the room.
function describeFront(focus: FocusStatus | undefined, tracking: boolean): { main: string; detail: string } {
  let front = { main: "--", detail: "" };
  if (focus != null && !tracking) {
    front = { main: "Paused", detail: "Mac tracking is off" };
  } else if (focus != null && !focus.app) {
    front = { main: "Not reporting", detail: "The Mac is asleep, or its helper isn't running" };
  } else if (focus?.app && focus.site) {
    front = { main: focus.site, detail: `in ${focus.app}` };
  } else if (focus?.app) {
    front = { main: focus.app, detail: "" };
  }
  return front;
}

interface MacCardProps {
  focus: FocusStatus | undefined;
  now: number;
  readOnly?: boolean; // a member: the switch is the owner's
}

// What's in front on the Mac, at the top for anyone to see, with the switch that pauses the tracking.
export function MacCard({ focus, now, readOnly = false }: MacCardProps) {
  // The switch flips right away; a failed POST drops the hold and it goes back to what the Pi says.
  const [held, setHeld] = useState<{ enabled: boolean; until: number } | null>(null);
  const tracking = held != null && now < held.until ? held.enabled : (focus?.mac_tracking ?? true);
  const front = describeFront(focus, tracking);
  const flipTracking = async (enabled: boolean) => {
    setHeld({ enabled, until: Infinity });
    const saved = await sendMacTracking(enabled);
    setHeld(saved ? { enabled, until: Date.now() / 1000 + SWITCH_HOLD_S } : null);
  };

  return (
    <section id="mac-now" className="card rise mb-4 flex flex-wrap items-center justify-between gap-4 p-5" style={riseDelay(1)} aria-label="On the Mac">
      <div className="min-w-0">
        <h2 className="label">On the Mac</h2>
        <p id="mac" className="mt-1 truncate text-3xl font-semibold tracking-tight sm:text-4xl">
          {front.main}
        </p>
        {front.detail && <p className="mono muted small mt-0.5">{front.detail}</p>}
      </div>
      {focus != null && !readOnly && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Switch checked={tracking} onCheckedChange={flipTracking} aria-label="Mac tracking" />
          <span aria-hidden="true">Tracking</span>
        </div>
      )}
    </section>
  );
}
