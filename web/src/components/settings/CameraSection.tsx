import { useState } from "react";
import { FormNote, buildErrorNote, type Note } from "@/components/shared/FormNote";
import { CAMERA_PROBLEMS, CameraControl } from "@/components/track/CameraControl";
import type { Camera } from "@/hooks/useCamera";
import { request } from "@/lib/http";
import { describeLoad } from "@/lib/track";
import type { FocusStatus } from "@/lib/types";

type Source = "pi" | "browser";

// A snapshot built just before the pick can still arrive after the reply, so the reply wins for a moment.
const PICK_HOLD_S = 2.5;

const SOURCES: { value: Source; label: string }[] = [
  { value: "pi", label: "This desk’s Pi cameras" },
  { value: "browser", label: "This browser’s camera" },
];

interface CameraSectionProps {
  focus: FocusStatus | undefined;
  owner: boolean;
  now: number;
  camera: Camera;
  onOpenSharing: () => void;
}

// Settings → Camera (Settings.dc.html): where your desk's checks come from. Only the owner's desk can have the Pi's
// cameras; everyone else's is this browser's, turned on here, on the Desk or on your seat, with its load line here.
// "Show my video in the room" is Sharing's Video switch, so this row only points there.
export function CameraSection({ focus, owner, now, camera, onOpenSharing }: CameraSectionProps) {
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
      {source === "browser" && (
        <>
          <div className="setting-row camera-row">
            <CameraControl camera={camera} place="settings" />
          </div>
          {camera.step === "problem" && camera.problem !== null && <p className="settings-hint">{CAMERA_PROBLEMS[camera.problem].fix}</p>}
          {(camera.step === "starting" || camera.step === "on") && (
            <p className="settings-hint camera-load">{describeLoad(camera.load.ms, camera.load.memory, camera.load.backend, camera.load.reason)}</p>
          )}
        </>
      )}
      <p className="settings-hint">
        {source === "browser"
          ? "Your video stays on this computer: the Pi gets the numbers, and a picture once a second only while Video is on. Keep a dayanpi tab open in Chrome. It keeps going on every page and behind other windows, and stops when the last dayanpi tab closes."
          : "The Pi's cameras watch your desk. Nothing on this computer needs to stay open."}
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
