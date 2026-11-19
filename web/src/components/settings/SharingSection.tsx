import { AnimatePresence, m } from "motion/react";
import { SeatPicture } from "@/components/room/SeatPicture";
import { Switch } from "@/components/ui/switch";
import { type SharingSwitch, useSharing } from "@/hooks/useSharing";
import { formatClock } from "@/lib/format";
import { SPRINGS } from "@/lib/motion";
import { listSharedPieces, readInitial } from "@/lib/room";
import type { FocusStatus, LampColor, Room } from "@/lib/types";

// History isn't in the mockup; it sits after the to-dos like the rest. Status is always on, so it's a plain row.
const SWITCHES: { key: SharingSwitch; label: string }[] = [
  { key: "focus", label: "Focus time" },
  { key: "todos", label: "To-do list" },
  { key: "history", label: "History" },
  { key: "apps", label: "Apps" },
  { key: "sites", label: "Sites" },
  { key: "video", label: "Video" },
  { key: "nudges", label: "Nudges" }, // whether others may nudge you; the button doesn't show for anyone while it's off
];

// Your lamp's color while focused; on the phone and away look the same for everyone. Each swatch gets its shade from
// dashboard.css's [data-lamp] rules.
const LAMPS: { value: LampColor; label: string }[] = [
  { value: "teal", label: "Teal" },
  { value: "green", label: "Green" },
  { value: "sky", label: "Sky" },
  { value: "yellow", label: "Yellow" },
  { value: "pink", label: "Pink" },
  { value: "white", label: "White" },
];

const PIECE_IN = { opacity: 1, transition: SPRINGS.enter };
const PIECE_OUT = { opacity: 0, transition: SPRINGS.exit };

interface SharingSectionProps {
  focus: FocusStatus | undefined;
  room: Room | null | undefined;
  username: string;
  now: number;
  receivedAt: number;
}

export function SharingSection({ focus, room, username, now, receivedAt }: SharingSectionProps) {
  const { sharing, seat, seatAt, flipSwitch, pickLamp } = useSharing(focus, room, username, now, receivedAt);

  return (
    <section aria-labelledby="settings-sharing">
      <h2 id="settings-sharing" className="settings-title">
        Share with the room
      </h2>
      <p className="settings-lead">Your own desk always shows you everything.</p>
      <div className="share-body">
        <ul className="share-switches">
          <li className="setting-row">
            Status
            <span className="setting-meta">Always on</span>
          </li>
          <li className="setting-row">
            <span id="lamp-color">Lamp color</span>
            <div className="lamp-swatches" role="radiogroup" aria-labelledby="lamp-color">
              {LAMPS.map((lamp) => (
                <label key={lamp.value} className="lamp-swatch" data-lamp={lamp.value} title={lamp.label}>
                  <input
                    type="radio"
                    className="sr-only"
                    name="lamp-color"
                    value={lamp.value}
                    aria-label={lamp.label}
                    checked={sharing.lamp === lamp.value}
                    onChange={() => void pickLamp(lamp.value)}
                  />
                </label>
              ))}
            </div>
          </li>
          {SWITCHES.map((entry) => (
            <li key={entry.key} className="setting-row">
              {entry.label}
              <Switch label={entry.label} checked={sharing[entry.key]} onCheckedChange={(on) => void flipSwitch(entry.key, on)} />
            </li>
          ))}
        </ul>
        <div className="share-preview">
          <p className="share-preview-label">What the room sees</p>
          {seat != null && (
            <>
              <div className="share-tile" data-state={seat.state} data-lamp={sharing.lamp} aria-label={`Your seat: ${seat.name}`}>
                <span className="share-initial" aria-hidden="true">
                  {readInitial(seat.name)}
                </span>
                {seat.picture != null && <SeatPicture username={seat.username} at={seat.picture.at} mirrored />}
                <div className="share-tile-foot">
                  <span className="share-name">{seat.name}</span>
                  <span className="share-timer">{seat.seconds_in_state == null ? "offline" : formatClock(seat.seconds_in_state + Math.max(0, now - seatAt))}</span>
                </div>
              </div>
              <ul className="share-pieces" aria-label="What else the room sees">
                <AnimatePresence initial={false}>
                  {listSharedPieces(seat).map((piece) => (
                    <m.li key={piece.key} className="share-piece" initial={{ opacity: 0 }} animate={PIECE_IN} exit={PIECE_OUT}>
                      {piece.text}
                    </m.li>
                  ))}
                </AnimatePresence>
              </ul>
            </>
          )}
        </div>
      </div>
    </section>
  );
}
