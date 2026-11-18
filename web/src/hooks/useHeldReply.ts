import { useRef, useState } from "react";
import { toast } from "sonner";

// A snapshot built just before a change can still arrive after the reply, so the reply wins for a moment.
const REPLY_HOLD_S = 2.5;

export interface HeldReply<T> {
  shown: T; // the stream's, except while a change is held
  heldAt: number | null; // when the held value came in, while one is held
  send: (guess: T | null, ask: () => Promise<T | null>, failure: string) => Promise<T | null>;
}

// What a page shows over the stream while it changes something on the Pi: the guess right away (if there is one), then
// the Pi's reply for REPLY_HOLD_S. A failed change goes back to the stream's and says `failure` in a toast. Only the
// newest request's answer counts, so an older reply can't undo a newer guess.
export function useHeldReply<T>(streamed: T, now: number): HeldReply<T> {
  const [held, setHeld] = useState<{ value: T; at: number; until: number } | null>(null);
  const newest = useRef(0);
  const holding = held != null && now < held.until;

  const send = async (guess: T | null, ask: () => Promise<T | null>, failure: string) => {
    const ticket = ++newest.current;
    if (guess != null) {
      setHeld({ value: guess, at: now, until: Infinity });
    }
    const replied = await ask();
    if (ticket === newest.current) {
      const at = Date.now() / 1000;
      setHeld(replied == null ? null : { value: replied, at, until: at + REPLY_HOLD_S });
    }
    if (replied == null) {
      toast(failure);
    }
    return replied;
  };
  return { shown: holding ? held.value : streamed, heldAt: holding ? held.at : null, send };
}
