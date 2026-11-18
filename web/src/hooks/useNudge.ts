import { createElement, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { NudgeToast } from "@/components/room/NudgeButton";
import { TOAST_S } from "@/components/ui/toaster";
import { request } from "@/lib/http";
import type { Seat, Spoken } from "@/lib/types";

export interface Nudger {
  sending: string | null; // the username a nudge is on its way to
  sent: Record<string, { at: number; wait_s: number }>; // what this page sent, so the wait shows before the stream says so
  nudge: (seat: Seat) => Promise<void>;
}

// Sends a nudge and says how it went in a toast. The ripples come back on the stream, for everyone.
export function useNudge(): Nudger {
  const [sending, setSending] = useState<string | null>(null);
  const [sent, setSent] = useState<Nudger["sent"]>({});
  const nudge = async (seat: Seat) => {
    setSending(seat.username);
    const reply = await request<{ wait_s: number }>("POST", "/api/nudge", { username: seat.username });
    setSending(null);
    if (reply.body != null) {
      const answer = reply.body;
      setSent((before) => ({ ...before, [seat.username]: { at: Date.now() / 1000, wait_s: answer.wait_s } }));
    }
    const message = reply.ok ? `Nudged ${seat.name}` : reply.status === 429 ? `${seat.name} was nudged a few minutes ago` : `Couldn't nudge ${seat.name}`;
    toast(createElement(NudgeToast, { text: message, meta: reply.ok ? "just now" : null }));
  };
  return { sending, sent, nudge };
}

// Someone nudged you: the voice plays like the peace sign's (usePeaceVoice), and this puts the words in a toast. Every
// snapshot repeats the last message, so a new one is a new `at`.
export function useNudgeToast(spoken: Spoken | null | undefined): void {
  const shownAt = useRef<number | null>(null);
  useEffect(() => {
    if (spoken?.kind === "nudge" && spoken.at !== shownAt.current && spoken.age_s < TOAST_S) {
      shownAt.current = spoken.at;
      toast(createElement(NudgeToast, { text: spoken.text, meta: null }));
    }
  }, [spoken]);
}
