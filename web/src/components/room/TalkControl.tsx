import { Mic, MicOff } from "lucide-react";
import type { Talk } from "@/hooks/useTalk";
import { EVERYONE } from "@/lib/talk";

// RoomV2's moving sound bars, in the text's own color.
export function SoundBars() {
  return (
    <span className="talk-bars" aria-hidden="true">
      <span />
      <span />
      <span />
      <span />
      <span />
    </span>
  );
}

// "Talk to everyone" by the room's total (RoomV2.dc.html): one click turns your mic on for everyone and it glows; a
// second click, or Esc, turns it off. While you're talking to one person from their seat it says so, and stops that too.
// Without WebCodecs Opus (Chrome only, like the tracker) it's one quiet line instead.
export function TalkControl({ talk, targetName }: { talk: Talk; targetName: string | null }) {
  const on = talk.target != null;
  let label = "Talk to everyone";
  if (on) {
    label = talk.target === EVERYONE ? "Mic on · everyone" : `Mic on · ${targetName ?? talk.target} only`;
  }
  return (
    talk.supported !== null && (
      <div className="talk">
        {talk.supported ? (
          <>
            <button type="button" className="talk-button" data-on={on || undefined} aria-pressed={on} onClick={() => (on ? talk.stop() : talk.talkTo(EVERYONE))}>
              {on ? <Mic size={17} strokeWidth={1.9} aria-hidden="true" /> : <MicOff size={17} strokeWidth={1.9} aria-hidden="true" />}
              {on && <SoundBars />}
              {label}
            </button>
            <span className="talk-hint">{on ? "Click to stop · Esc works too" : "For one person, use their seat"}</span>
          </>
        ) : (
          <span className="talk-hint">Talking needs Chrome</span>
        )}
      </div>
    )
  );
}
