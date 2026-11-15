import { useEffect, useState } from "react";
import type { Connection, Snapshot } from "@/lib/types";

export interface SnapshotStream {
  snapshot: Snapshot | null;
  connection: Connection;
  receivedAt: number;
}

// One stream for the whole page. It closes while the tab is hidden and reopens when it's back.
export function useSnapshot(): SnapshotStream {
  const [stream, setStream] = useState<SnapshotStream>({ snapshot: null, connection: "disconnected", receivedAt: 0 });
  useEffect(() => {
    let events: EventSource | null = null;
    const start = () => {
      if (events == null) {
        events = new EventSource("/api/stream");
        events.onmessage = (event) => setStream({ snapshot: JSON.parse(event.data), connection: "connected", receivedAt: Date.now() / 1000 });
        // The browser reconnects by itself; only the indicator needs updating.
        events.onerror = () => setStream((previous) => ({ ...previous, connection: "reconnecting" }));
      }
    };
    const stop = () => {
      events?.close();
      events = null;
    };
    const followVisibility = () => (document.hidden ? stop() : start());
    start();
    document.addEventListener("visibilitychange", followVisibility);
    return () => {
      document.removeEventListener("visibilitychange", followVisibility);
      stop();
    };
  }, []);
  return stream;
}
