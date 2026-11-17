import { useEffect, useState } from "react";
import { request } from "@/lib/http";
import type { TheirDesk } from "@/lib/types";

const REFRESH_S = 30; // the numbers off their logs; the state and timer come live from the room stream

export interface TheirDeskReply {
  desk: TheirDesk | null; // null while it loads
  missing: boolean; // nobody by that name
}

// Someone's desk from /api/people/<username>: asked again when what they share changes (so a piece fades in or out
// right away) and every REFRESH_S.
export function useTheirDesk(username: string | null, shares: string, now: number): TheirDeskReply {
  const [reply, setReply] = useState<TheirDeskReply & { username: string | null }>({ desk: null, missing: false, username: null });
  const refresh = Math.floor(now / REFRESH_S);
  useEffect(() => {
    let current = true;
    if (username != null) {
      void request<TheirDesk>("GET", `/api/people/${encodeURIComponent(username)}`).then((answer) => {
        if (current && answer.status !== 0) {
          setReply({ desk: answer.body, missing: answer.status === 404, username });
        }
      });
    }
    return () => {
      current = false;
    };
  }, [username, shares, refresh]);
  // Someone else's reply never shows under a new name while theirs loads.
  const shown = reply.username === username ? reply : { desk: null, missing: false };
  return { desk: shown.desk, missing: shown.missing };
}
