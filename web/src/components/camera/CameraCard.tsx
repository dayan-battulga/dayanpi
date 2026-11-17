import { EyeOff, Lock } from "lucide-react";
import { useState } from "react";
import { Feed } from "@/components/camera/Feed";
import { riseDelay } from "@/components/shared/rise";
import { readStored, writeStored } from "@/lib/storage";
import type { FocusStatus } from "@/lib/types";

const FEEDS = [
  { name: "front", src: "/video", caption: "Front", alt: "Live front camera feed", overlayKey: "overlay", hidden: "Hidden while you work", locked: "Only on your own devices" },
  { name: "side", src: "/video/side", caption: "Side", alt: "Live side camera feed", overlayKey: "side_overlay", hidden: "Hidden", locked: "Locked" },
] as const;
const PHONE_MIN = 0.5; // focus/tracker.py's: a weaker phone doesn't count
const HIDDEN_NOTE = "The readings keep updating while the picture is hidden.";
const LOCKED_NOTE = "This browser isn’t one of your Tailscale devices, so the cameras stay closed.";

// What the detector saw last, the best of both cameras: "person 0.94 · no phone".
function describeReadings(focus: FocusStatus | undefined): string {
  const check = focus?.camera_ok ? focus.last_check : null;
  let text = focus?.enabled === false ? "The detector is off." : "No frames from the cameras right now.";
  if (check != null) {
    const phone = check.phone >= PHONE_MIN ? `phone in hand ${check.phone.toFixed(2)}` : "no phone";
    text = `person ${check.person.toFixed(2)} · ${phone}`;
  }
  return text;
}

// /pi's cameras: every feed side by side, hidden behind a veil until Peek, which opens them all (Hide closes them).
// Off your own Tailscale devices they're locked, and /video never opens.
export function CameraCard({ focus }: { focus: FocusStatus | undefined }) {
  const [peeking, setPeeking] = useState(() => readStored("peek", "0") === "1");
  // The feeds wait for the first status, which says whether /video will answer this viewer at all.
  const open = (focus?.camera_access ?? "open") === "open";
  const shown = open && peeking;
  const feeds = focus?.side_camera ? FEEDS : FEEDS.slice(0, 1);
  const note = !open ? LOCKED_NOTE : peeking ? describeReadings(focus) : HIDDEN_NOTE;
  const togglePeek = () => {
    writeStored("peek", peeking ? "0" : "1");
    setPeeking(!peeking);
  };

  return (
    <section className="cameras rise" style={riseDelay(0)} data-state={focus?.state ?? "unknown"} aria-labelledby="cameras-title">
      <div className="cameras-head">
        <h1 id="cameras-title" className="page-title">
          Cameras
        </h1>
        {open && (
          <button type="button" className="peek-button" aria-pressed={peeking} onClick={togglePeek}>
            {peeking ? "Hide" : "Peek"}
          </button>
        )}
      </div>
      <div className="cam-tiles">
        {feeds.map((feed, index) => (
          <figure key={feed.name} className="cam">
            <div className="cam-tile" data-peeking={shown || undefined}>
              {open && focus != null && <Feed src={feed.src} alt={feed.alt} overlay={focus[feed.overlayKey]} cameraOk={focus.camera_ok} wanted={peeking} />}
              <div className="cam-veil">
                <div className="cam-veil-content">
                  {index === 0 && (open ? <EyeOff size={22} strokeWidth={1.8} aria-hidden="true" /> : <Lock size={22} strokeWidth={1.8} aria-hidden="true" />)}
                  <span className={index === 0 ? "cam-veil-title" : undefined}>{open ? feed.hidden : feed.locked}</span>
                </div>
              </div>
            </div>
            <figcaption className="cam-caption">{feed.caption}</figcaption>
          </figure>
        ))}
      </div>
      <p className="cam-note">{note}</p>
    </section>
  );
}
