import { useState } from "react";
import { FormNote, buildErrorNote, type Note } from "@/components/shared/FormNote";
import { request } from "@/lib/http";
import type { FocusStatus } from "@/lib/types";

type Source = "pi" | "browser";

// A snapshot built just before the pick can still arrive after the reply, so the reply wins for a moment.
const PICK_HOLD_S = 2.5;

const SOURCES: { value: Source; label: string }[] = [
  { value: "pi", label: "This desk’s Pi cameras" },
  { value: "browser", label: "This browser’s camera" },
];

// Settings → Camera (Settings.dc.html): where your desk's checks come from. Only the owner's desk can have the Pi's
// cameras; everyone else's is a browser's, through /track. "Show my video in the room" is Sharing's Video switch, so this
// row only points there.
export function CameraSection({ focus, owner, now, onOpenSharing }: { focus: FocusStatus | undefined; owner: boolean; now: number; onOpenSharing: () => void }) {
  const [held, setHeld] = useState<{ source: Source; until: number } | null>(null);
  const [note, setNote] = useState<Note | null>(null);
  const saved = focus?.camera_source ?? (owner ? "pi" : "browser");
  const source = held !== null && now < held.until ? held.source : saved;

  const pickSource = async (picked: Source) => {
    setNote(null);
    setHeld({ source: picked, until: Infinity });
    const reply = await request("POST", "/api/track/source", { source: picked });
    setHeld(reply.ok ? { source: picked, until: Date.now() / 1000 + PICK_HOLD_S } : null);
    if (!reply.ok) {
      setNote(buildErrorNote(reply.detail));
    }
  };

  return (
    <section aria-labelledby="settings-camera">
      <h2 id="settings-camera" className="settings-title">
        Camera
      </h2>
      <fieldset className="setting-choices">
        <legend className="setting-legend">Track focus with</legend>
        {SOURCES.map((entry) => (
          <label key={entry.value} className="setting-choice" data-disabled={entry.value === "pi" && !owner ? "" : undefined}>
            <input
              type="radio"
              name="camera-source"
              value={entry.value}
              checked={source === entry.value}
              disabled={entry.value === "pi" && !owner}
              onChange={() => void pickSource(entry.value)}
            />
            {entry.label}
          </label>
        ))}
      </fieldset>
      <FormNote note={note} />
      <p className="settings-hint">
        {source === "browser" ? (
          <>
            {/* A full page load: the tracker needs its own headers. */}
            Open <a href="/track">the tracker</a> in Chrome on the computer with the camera, and keep its tab open.
          </>
        ) : (
          "The Pi's cameras watch your desk. Nothing on this computer needs to stay open."
        )}
        {!owner && " The Pi's cameras are only for the owner's desk."}
      </p>
      <div className="setting-row settings-video-row">
        Show my video in the room
        <button type="button" className="setting-link" onClick={onOpenSharing}>
          Set in Sharing
        </button>
      </div>
      <p className="settings-hint">Your seat never shows video while you’re away.</p>
    </section>
  );
}
