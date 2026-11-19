import { type ReactNode, useState } from "react";
import { FormNote, buildErrorNote, type Note } from "@/components/shared/FormNote";
import { CAMERA_PROBLEMS, CameraControl } from "@/components/track/CameraControl";
import type { Camera } from "@/hooks/useCamera";
import { request } from "@/lib/http";
import { describeLoad } from "@/lib/track";
import type { FocusStatus } from "@/lib/types";

type Source = "pi" | "browser";
type PiCamera = "front" | "side";
type Pick = "source" | "picture" | "pi_camera"; // POST /api/track/source's keys

// A snapshot built just before the pick can still arrive after the reply, so the reply wins for a moment.
const PICK_HOLD_S = 2.5;

const SOURCES: { value: Source; label: string }[] = [
  { value: "pi", label: "This desk’s Pi cameras" },
  { value: "browser", label: "This browser’s camera" },
];

const PICTURES: { value: Source; label: string }[] = [
  { value: "pi", label: "The Pi’s camera" },
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
  trailing?: Partial<Record<Source, ReactNode>>; // something at a row's end, outside its label
}

// One pick's radios. The Pi's are greyed out for a member.
function Choices({ legend, name, choices, picked, owner, onPick, trailing }: ChoicesProps) {
  return (
    <fieldset className="setting-choices">
      <legend className="setting-legend">{legend}</legend>
      {choices.map((entry) => (
        <div key={entry.value} className="setting-choice" data-disabled={entry.value === "pi" && !owner ? "" : undefined}>
          <label className="setting-choice-label">
            <input type="radio" name={name} value={entry.value} checked={picked === entry.value} disabled={entry.value === "pi" && !owner} onChange={() => onPick(entry.value)} />
            {entry.label}
          </label>
          {trailing?.[entry.value]}
        </div>
      ))}
    </fieldset>
  );
}

// Which Pi camera the owner's tile comes from. Side needs the side camera running; without it the tile is the front's.
function PiCameraPick({ picked, sideRunning, onPick }: { picked: PiCamera; sideRunning: boolean; onPick: (value: PiCamera) => void }) {
  return (
    <select className="setting-select" aria-label="Which Pi camera" value={picked} onChange={(event) => onPick(event.target.value as PiCamera)}>
      <option value="front">Front</option>
      <option value="side" disabled={!sideRunning}>
        Side
      </option>
    </select>
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
// comes from (until picked, the same place) and, for the Pi's, which camera (front until picked). Only the owner's desk can have the Pi's cameras; everyone else's is this
// browser's, turned on here, on the Desk or on your seat, with its load line here. "Show my video in the room" is
// Sharing's Video switch, so this row only points there.
export function CameraSection({ focus, owner, now, camera, onOpenSharing }: CameraSectionProps) {
  const [held, setHeld] = useState<{ pick: Pick; value: string; until: number } | null>(null);
  const [note, setNote] = useState<Note | null>(null);
  const showPick = <T extends string>(pick: Pick, saved: T): T => (held !== null && held.pick === pick && now < held.until ? (held.value as T) : saved);
  const source = showPick<Source>("source", focus?.camera_source ?? (owner ? "pi" : "browser"));
  const picture = showPick<Source>("picture", focus?.picture_source ?? source);
  const piCamera = showPick<PiCamera>("pi_camera", focus?.pi_camera ?? "front");
  const sideRunning = focus?.side_camera_running === true;

  const pick = async (key: Pick, value: string) => {
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
      {owner && (
        <Choices
          legend="Room picture from"
          name="picture-source"
          choices={PICTURES}
          picked={picture}
          owner={owner}
          onPick={(value) => void pick("picture", value)}
          trailing={{ pi: picture === "pi" && <PiCameraPick picked={piCamera} sideRunning={sideRunning} onPick={(value) => void pick("pi_camera", value)} /> }}
        />
      )}
      {owner && picture === "pi" && !sideRunning && (
        <p className="settings-hint">{piCamera === "side" ? "The side camera isn’t running, so your tile comes from the front one." : "The side camera isn’t running."}</p>
      )}
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
