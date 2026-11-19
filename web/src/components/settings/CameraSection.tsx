import { useState } from "react";
import { FormNote, buildErrorNote, type Note } from "@/components/shared/FormNote";
import { CAMERA_PROBLEMS, CameraControl } from "@/components/track/CameraControl";
import type { Camera } from "@/hooks/useCamera";
import { request } from "@/lib/http";
import { describeLoad } from "@/lib/track";
import type { FocusStatus } from "@/lib/types";

type Source = "pi" | "browser";
type Pick = "source" | "picture"; // POST /api/track/source's two keys

// A snapshot built just before the pick can still arrive after the reply, so the reply wins for a moment.
const PICK_HOLD_S = 2.5;

const SOURCES: { value: Source; label: string }[] = [
  { value: "pi", label: "This desk’s Pi cameras" },
  { value: "browser", label: "This browser’s camera" },
];

const PICTURES: { value: Source; label: string }[] = [
  { value: "pi", label: "The Pi’s front camera" },
  { value: "browser", label: "This browser’s camera" },
];

interface CameraSectionProps {
  focus: FocusStatus | undefined;
  owner: boolean;
  now: number;
  camera: Camera;
  onOpenSharing: () => void;
}

interface ChoicesProps {
  legend: string;
  name: string;
  choices: { value: Source; label: string }[];
  picked: Source;
  owner: boolean;
  onPick: (value: Source) => void;
}

// One pick's radios. The Pi's are greyed out for a member.
function Choices({ legend, name, choices, picked, owner, onPick }: ChoicesProps) {
  return (
    <fieldset className="setting-choices">
      <legend className="setting-legend">{legend}</legend>
      {choices.map((entry) => (
        <label key={entry.value} className="setting-choice" data-disabled={entry.value === "pi" && !owner ? "" : undefined}>
          <input type="radio" name={name} value={entry.value} checked={picked === entry.value} disabled={entry.value === "pi" && !owner} onChange={() => onPick(entry.value)} />
          {entry.label}
        </label>
      ))}
    </fieldset>
  );
}

function describeCamera(source: Source, picture: Source, owner: boolean): string {
  const tab = "Keep a dayanpi tab open in Chrome. It keeps going on every page and behind other windows, and stops when the last dayanpi tab closes.";
  const hints: Record<`${Source}-${Source}`, string> = {
    "browser-browser": `Your video stays on this computer: the Pi gets the numbers, and a picture once a second only while Video is on. ${tab}`,
    "browser-pi": `Your video stays on this computer: the Pi gets the numbers, and your seat’s picture comes from its front camera. ${tab}`,
    "pi-browser": `The Pi’s cameras watch your desk, and this browser sends only your seat’s picture, once a second while Video is on. ${tab}`,
    "pi-pi": "The Pi’s cameras watch your desk. Nothing on this computer needs to stay open.",
  };
  const hint = hints[`${source}-${picture}`] + (owner ? "" : " The Pi’s cameras are only for the owner’s desk.");
  return hint;
}

// Settings → Camera (Settings.dc.html): where your desk's checks come from, and for the owner where the seat's picture
// comes from (until picked, the same place). Only the owner's desk can have the Pi's cameras; everyone else's is this
// browser's, turned on here, on the Desk or on your seat, with its load line here. "Show my video in the room" is
// Sharing's Video switch, so this row only points there.
export function CameraSection({ focus, owner, now, camera, onOpenSharing }: CameraSectionProps) {
  const [held, setHeld] = useState<{ pick: Pick; value: Source; until: number } | null>(null);
  const [note, setNote] = useState<Note | null>(null);
  const showPick = (pick: Pick, saved: Source) => (held !== null && held.pick === pick && now < held.until ? held.value : saved);
  const source = showPick("source", focus?.camera_source ?? (owner ? "pi" : "browser"));
  const picture = showPick("picture", focus?.picture_source ?? source);

  const pick = async (key: Pick, value: Source) => {
    setNote(null);
    setHeld({ pick: key, value, until: Infinity });
    const reply = await request("POST", "/api/track/source", { [key]: value });
    setHeld(reply.ok ? { pick: key, value, until: Date.now() / 1000 + PICK_HOLD_S } : null);
    if (!reply.ok) {
      setNote(buildErrorNote(reply.detail));
    }
  };

  return (
    <section aria-labelledby="settings-camera">
      <h2 id="settings-camera" className="settings-title">
        Camera
      </h2>
      <Choices legend="Track focus with" name="camera-source" choices={SOURCES} picked={source} owner={owner} onPick={(value) => void pick("source", value)} />
      {owner && <Choices legend="Room picture from" name="picture-source" choices={PICTURES} picked={picture} owner={owner} onPick={(value) => void pick("picture", value)} />}
      <FormNote note={note} />
      {(source === "browser" || picture === "browser") && (
        <>
          <div className="setting-row camera-row">
            <CameraControl camera={camera} place="settings" />
          </div>
          {camera.step === "problem" && camera.problem !== null && <p className="settings-hint">{CAMERA_PROBLEMS[camera.problem].fix}</p>}
          {source === "browser" && (camera.step === "starting" || camera.step === "on") && (
            <p className="settings-hint camera-load">{describeLoad(camera.load.ms, camera.load.memory, camera.load.backend, camera.load.reason)}</p>
          )}
        </>
      )}
      <p className="settings-hint">{describeCamera(source, picture, owner)}</p>
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
