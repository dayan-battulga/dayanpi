import { useEffect, useState } from "react";
import { request } from "@/lib/http";
import type { Connection, Snapshot } from "@/lib/types";

export interface SnapshotStream {
  snapshot: Snapshot | null;
  connection: Connection;
  receivedAt: number;
}

export const STREAM_RETRY_MS = 5000;

// One stream for the whole page. It closes while the tab is hidden and reopens when it's back.
export function useSnapshot(): SnapshotStream {
  const [stream, setStream] = useState<SnapshotStream>({ snapshot: null, connection: "disconnected", receivedAt: 0 });
  useEffect(() => {
    let events: EventSource | null = null;
    let retry: number | undefined;
    const start = () => {
      if (events == null) {
        const source = new EventSource("/api/stream");
        events = source;
        source.onmessage = (event) => setStream({ snapshot: JSON.parse(event.data), connection: "connected", receivedAt: Date.now() / 1000 });
        // The browser retries a dropped connection by itself, but gives up for good on any answer that
        // isn't a 200 (Tailscale's 502 while the Pi restarts, the 503 stream cap), so that one is reopened
        // here. An EventSource can't see a 401, so /api/me asks: the request helper sends you to /login.
        source.onerror = () => {
          setStream((previous) => ({ ...previous, connection: "reconnecting" }));
          request("GET", "/api/me");
          if (source.readyState === EventSource.CLOSED) {
            stop();
            retry = window.setTimeout(start, STREAM_RETRY_MS);
          }
        };
      }
    };
    const stop = () => {
      window.clearTimeout(retry);
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
