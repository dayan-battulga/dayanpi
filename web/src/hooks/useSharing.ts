import { useHeldReply } from "@/hooks/useHeldReply";
import { request } from "@/lib/http";
import type { FocusStatus, Room, Seat, Sharing } from "@/lib/types";

export const DEFAULT_SHARING: Sharing = { focus: true, todos: true, history: true, apps: false, sites: false, video: false, nudges: true };

interface SharingReply {
  sharing: Sharing;
  seat: Seat | null; // the reply's, once it's in
}

export interface SharingSwitches {
  sharing: Sharing;
  seat: Seat | null; // your seat as the room gets it: the reply's while held, else the stream's
  seatAt: number; // when that seat came in, for its timer
  flipSwitch: (key: keyof Sharing, on: boolean) => Promise<void>;
}

// Your sharing switches (Settings → Sharing): a flip shows at once, the Pi's reply
// carries your seat as the room now gets it, and only the newest flip's answer counts.
export function useSharing(focus: FocusStatus | undefined, room: Room | null | undefined, username: string | undefined, now: number, receivedAt: number): SharingSwitches {
  const streamed = room?.seats.find((entry) => entry.username === username) ?? null;
  const { shown, heldAt, send } = useHeldReply<SharingReply>({ sharing: focus?.sharing ?? DEFAULT_SHARING, seat: streamed }, now);
  const replied = heldAt != null && shown.seat != null;

  const flipSwitch = async (key: keyof Sharing, on: boolean) => {
    const ask = async () => (await request<SharingReply>("POST", "/api/sharing", { [key]: on })).body;
    await send({ sharing: { ...shown.sharing, [key]: on }, seat: null }, ask, "Couldn't change what the room sees");
  };
  return { sharing: shown.sharing, seat: replied ? shown.seat : streamed, seatAt: replied ? heldAt : receivedAt, flipSwitch };
}
