import { useState } from "react";
import { FormNote, buildErrorNote, type Note } from "@/components/shared/FormNote";
import { request } from "@/lib/http";
import type { FocusStatus } from "@/lib/types";

type Output = "pi" | "computer";

// A snapshot built just before a change can still arrive after the reply, so the reply wins for a moment.
const PICK_HOLD_S = 2.5;

const OUTPUTS: { value: Output; label: string }[] = [
  { value: "pi", label: "The Pi’s speaker" },
  { value: "computer", label: "This computer" },
];

interface Held {
  bedtime?: string;
  output?: Output;
  until: number;
}

// Settings → Voice and bedtime (Settings.dc.html): your own bedtime for the peace sign's "time until bed", where it
// speaks, and Test the voice, which says a short line there (it pops up in the pill like a real message). Only the
// owner's desk can have the Pi's speaker, which is in their room; This computer plays on your own page, which the
// browser only allows after a click on it.
export function VoiceSection({ focus, owner, now }: { focus: FocusStatus | undefined; owner: boolean; now: number }) {
  const [held, setHeld] = useState<Held | null>(null);
  const [note, setNote] = useState<Note | null>(null);
  const holding = held !== null && now < held.until;
  const bedtime = (holding ? held.bedtime : undefined) ?? focus?.bedtime ?? "00:00";
  const output = (holding ? held.output : undefined) ?? focus?.voice_output ?? (owner ? "pi" : "computer");
  const voiceOn = focus?.voice?.enabled ?? false;

  const saveVoice = async (change: { bedtime?: string; output?: Output }) => {
    setNote(null);
    setHeld({ ...change, until: Infinity });
    const reply = await request("POST", "/api/voice", change);
    setHeld(reply.ok ? { ...change, until: Date.now() / 1000 + PICK_HOLD_S } : null);
    if (!reply.ok) {
      setNote(buildErrorNote(reply.detail));
    }
  };
  const testVoice = async () => {
    setNote(null);
    const reply = await request("POST", "/api/voice/test", {});
    if (!reply.ok) {
      // One test every 10 s per desk: say how long is left instead of the Pi's "one test every 10 s".
      setNote(reply.retryAfterS != null ? { text: `Wait ${reply.retryAfterS} s, then test it again.`, error: true } : buildErrorNote(reply.detail));
    }
  };

  return (
    <section aria-labelledby="settings-voice">
      <h2 id="settings-voice" className="settings-title">
        Voice and bedtime
      </h2>
      <label htmlFor="settings-bedtime" className="bedtime-label">
        Bedtime
      </label>
      <input
        id="settings-bedtime"
        className="bedtime-input"
        type="time"
        required
        value={bedtime}
        onChange={(event) => event.target.value !== "" && void saveVoice({ bedtime: event.target.value })}
      />
      <fieldset className="setting-choices">
        <legend className="setting-legend">The peace sign speaks through</legend>
        {OUTPUTS.map((entry) => (
          <label key={entry.value} className="setting-choice" data-disabled={entry.value === "pi" && !owner ? "" : undefined}>
            <input
              type="radio"
              name="voice-output"
              value={entry.value}
              checked={output === entry.value}
              disabled={entry.value === "pi" && !owner}
              onChange={() => void saveVoice({ output: entry.value })}
            />
            {entry.label}
          </label>
        ))}
      </fieldset>
      <button type="button" className="button button-line settings-action" onClick={() => void testVoice()}>
        Test the voice
      </button>
      <FormNote note={note} />
      {!voiceOn && <p className="settings-hint">The Pi's voice is off, so the peace sign shows its words and says nothing.</p>}
      {!owner && voiceOn && <p className="settings-hint">The Pi's speaker is in the owner's room, so yours plays on this computer.</p>}
    </section>
  );
}
