import { riseDelay } from "@/components/shared/rise";
import { Switch } from "@/components/ui/switch";
import type { MacTracking } from "@/hooks/useMacTracking";
import type { FocusStatus } from "@/lib/types";

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
  macTracking: MacTracking; // the frame's, so ⌘K's command and this switch flip the same thing
  readOnly?: boolean; // a member: the switch is the owner's
}

// What's in front on the Mac, at the top for anyone to see, with the switch that pauses the tracking.
export function MacCard({ focus, macTracking, readOnly = false }: MacCardProps) {
  const { tracking, flipTracking } = macTracking;
  const front = describeFront(focus, tracking);

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
