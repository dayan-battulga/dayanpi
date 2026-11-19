import { useHeldReply } from "@/hooks/useHeldReply";
import { request } from "@/lib/http";
import type { FocusStatus, LampColor, Room, Seat, Sharing } from "@/lib/types";

export const DEFAULT_SHARING: Sharing = { focus: true, todos: true, history: true, apps: false, sites: false, video: false, nudges: true, lamp: "teal" };

interface SharingReply {
  sharing: Sharing;
  seat: Seat | null; // the reply's, once it's in
}

export type SharingSwitch = Exclude<keyof Sharing, "lamp">;

export interface SharingSwitches {
  sharing: Sharing;
  seat: Seat | null; // your seat as the room gets it: the reply's while held, else the stream's
  seatAt: number; // when that seat came in, for its timer
  flipSwitch: (key: SharingSwitch, on: boolean) => Promise<void>;
  pickLamp: (lamp: LampColor) => Promise<void>;
}

// Your sharing switches and lamp color (Settings → Sharing): a change shows at once, the Pi's reply
// carries your seat as the room now gets it, and only the newest change's answer counts.
export function useSharing(focus: FocusStatus | undefined, room: Room | null | undefined, username: string | undefined, now: number, receivedAt: number): SharingSwitches {
  const streamed = room?.seats.find((entry) => entry.username === username) ?? null;
  const { shown, heldAt, send } = useHeldReply<SharingReply>({ sharing: focus?.sharing ?? DEFAULT_SHARING, seat: streamed }, now);
  const replied = heldAt != null && shown.seat != null;

  const change = async (changes: Partial<Sharing>) => {
    const ask = async () => (await request<SharingReply>("POST", "/api/sharing", changes)).body;
    await send({ sharing: { ...shown.sharing, ...changes }, seat: null }, ask, "Couldn't change what the room sees");
  };
  const flipSwitch = (key: SharingSwitch, on: boolean) => change({ [key]: on });
  const pickLamp = (lamp: LampColor) => change({ lamp });
  return { sharing: shown.sharing, seat: replied ? shown.seat : streamed, seatAt: replied ? heldAt : receivedAt, flipSwitch, pickLamp };
}
