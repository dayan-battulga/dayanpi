import { useRef, useState } from "react";
import { showToast } from "@/components/ui/toaster";
import { request } from "@/lib/http";
import type { FocusStatus, Room, Seat, Sharing } from "@/lib/types";

// A snapshot built just before a switch flipped can still arrive after the reply, so the reply wins for a moment.
const SWITCH_HOLD_S = 2.5;

export const DEFAULT_SHARING: Sharing = { focus: true, todos: true, history: true, apps: false, sites: false, video: false, nudges: true };

interface Held {
  sharing: Sharing;
  seat: Seat | null; // the reply's, once it's in
  at: number;
  until: number;
}

export interface SharingSwitches {
  sharing: Sharing;
  seat: Seat | null; // your seat as the room gets it: the reply's while held, else the stream's
  seatAt: number; // when that seat came in, for its timer
  flipSwitch: (key: keyof Sharing, on: boolean) => Promise<void>;
}

// Your sharing switches (Settings → Sharing, and the room's Show/Hide my video): a flip shows at once, the Pi's reply
// carries your seat as the room now gets it, and only the newest flip's answer counts.
export function useSharing(focus: FocusStatus | undefined, room: Room | null | undefined, username: string | undefined, now: number, receivedAt: number): SharingSwitches {
  const [held, setHeld] = useState<Held | null>(null);
  const latest = useRef(0);
  const holding = held != null && now < held.until;
  const sharing = holding ? held.sharing : (focus?.sharing ?? DEFAULT_SHARING);
  const streamed = room?.seats.find((entry) => entry.username === username) ?? null;
  const seat = holding && held.seat != null ? held.seat : streamed;

  const flipSwitch = async (key: keyof Sharing, on: boolean) => {
    const asked = ++latest.current;
    setHeld({ sharing: { ...sharing, [key]: on }, seat: null, at: now, until: Infinity });
    const reply = await request<{ sharing: Sharing; seat: Seat }>("POST", "/api/sharing", { [key]: on });
    const answer = reply.body;
    if (asked === latest.current) {
      const at = Date.now() / 1000;
      setHeld(answer != null ? { sharing: answer.sharing, seat: answer.seat, at, until: at + SWITCH_HOLD_S } : null);
    }
    if (answer == null) {
      showToast("Couldn't change what the room sees");
    }
  };
  return { sharing, seat, seatAt: holding && held.seat != null ? held.at : receivedAt, flipSwitch };
}
