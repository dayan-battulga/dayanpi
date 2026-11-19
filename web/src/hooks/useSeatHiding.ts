import { toast } from "sonner";
import { useHeldReply } from "@/hooks/useHeldReply";
import { request } from "@/lib/http";
import type { Seat } from "@/lib/types";

export interface SeatHiding {
  hidden: Record<string, boolean>; // by username: the stream's, or this page's change while it's on its way
  hide: (seat: Seat) => Promise<void>;
}

// An offline seat's ×: tidies it out of the room for everyone at once, with Undo in the toast. Nothing about their
// account changes, and the Pi brings the seat back by itself once they're here.
export function useSeatHiding(seats: Seat[], now: number): SeatHiding {
  const { shown, send } = useHeldReply(Object.fromEntries(seats.map((seat) => [seat.username, seat.hidden])), now);
  const flip = async (seat: Seat, hidden: boolean) => {
    const changed = { ...shown, [seat.username]: hidden };
    const ask = async () => ((await request("POST", hidden ? "/api/room/hide" : "/api/room/show", { username: seat.username })).ok ? changed : null);
    const replied = await send(changed, ask, hidden ? `Couldn’t hide ${seat.name}’s seat` : `Couldn’t bring back ${seat.name}’s seat`);
    return replied;
  };
  const hide = async (seat: Seat) => {
    if ((await flip(seat, true)) != null) {
      toast(`Hid ${seat.name}’s seat`, { action: { label: "Undo", onClick: () => void flip(seat, false) } });
    }
  };
  return { hidden: shown, hide };
}
