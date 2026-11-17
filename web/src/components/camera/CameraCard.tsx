import { ArrowLeftRight, EyeOff, Lock } from "lucide-react";
import { useCallback, useState, type CSSProperties } from "react";
import { Feed } from "@/components/camera/Feed";
import { riseDelay } from "@/components/shared/rise";
import { readStored, writeStored } from "@/lib/storage";
import type { FocusStatus } from "@/lib/types";

const FEEDS = [
  { name: "front", src: "/video", caption: "Front", alt: "Live front camera feed", overlayKey: "overlay" },
  { name: "side", src: "/video/side", caption: "Side", alt: "Live side camera feed", overlayKey: "side_overlay" },
] as const;
const PHONE_MIN = 0.5; // focus/tracker.py's: a weaker phone doesn't count
const FALLBACK_RATIO = 640 / 480; // the webcam's, until the camera's overlay or picture says its own shape
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

// /pi's cameras: one tile, hidden behind a veil until Peek. With a side camera, the Front/Side button switches which
// one it shows (remembered), and only that one's stream opens. Off your own Tailscale devices it's locked, and
// /video never opens.
export function CameraCard({ focus }: { focus: FocusStatus | undefined }) {
  const [peeking, setPeeking] = useState(() => readStored("peek", "0") === "1");
  const [view, setView] = useState(() => (readStored("camera", "front") === "side" ? "side" : "front"));
  const [ratios, setRatios] = useState<Record<string, number>>({});
  const reportRatio = useCallback((name: string, ratio: number) => {
    setRatios((current) => (current[name] === ratio ? current : { ...current, [name]: ratio }));
  }, []);
  // The feeds wait for the first status, which says whether /video will answer this viewer at all.
  const open = (focus?.camera_access ?? "open") === "open";
  const canFlip = open && focus?.side_camera === true;
  const shown = canFlip && view === "side" ? FEEDS[1] : FEEDS[0];
  const note = !open ? LOCKED_NOTE : peeking ? describeReadings(focus) : HIDDEN_NOTE;
  const togglePeek = () => {
    writeStored("peek", peeking ? "0" : "1");
    setPeeking(!peeking);
  };
  const flipCamera = () => {
    const next = shown.name === "side" ? "front" : "side";
    writeStored("camera", next);
    setView(next);
  };

  return (
    <section className="cameras rise" style={riseDelay(0)} data-state={focus?.state ?? "unknown"} aria-labelledby="cameras-title">
      <div className="cameras-head">
        <h1 id="cameras-title" className="page-title">
          Cameras
        </h1>
        {open && (
          <div className="cameras-buttons">
            {canFlip && (
              <button type="button" className="peek-button" aria-label={shown.name === "side" ? "Show the front camera" : "Show the side camera"} onClick={flipCamera}>
                <ArrowLeftRight size={16} strokeWidth={1.8} aria-hidden="true" />
                {shown.name === "side" ? "Front" : "Side"}
              </button>
            )}
            <button type="button" className="peek-button" aria-pressed={peeking} onClick={togglePeek}>
              {peeking ? "Hide" : "Peek"}
            </button>
          </div>
        )}
      </div>
      <figure className="cam" style={{ "--ratio": ratios[shown.name] ?? FALLBACK_RATIO } as CSSProperties}>
        <div className="cam-tile" data-peeking={(open && peeking) || undefined}>
          {/* Both stay mounted: the one not showing swaps to a blank image, which is what closes its stream. */}
          {open &&
            focus != null &&
            FEEDS.slice(0, canFlip ? 2 : 1).map((feed) => (
              <Feed
                key={feed.name}
                name={feed.name}
                src={feed.src}
                alt={feed.alt}
                overlay={focus[feed.overlayKey]}
                cameraOk={focus.camera_ok}
                wanted={peeking && feed === shown}
                hidden={feed !== shown}
                onRatio={reportRatio}
              />
            ))}
          <div className="cam-veil">
            <div className="cam-veil-content">
              {open ? <EyeOff size={22} strokeWidth={1.8} aria-hidden="true" /> : <Lock size={22} strokeWidth={1.8} aria-hidden="true" />}
              <span className="cam-veil-title">{open ? "Hidden while you work" : "Only on your own devices"}</span>
            </div>
          </div>
        </div>
        <figcaption className="cam-caption">{shown.caption}</figcaption>
        <p className="cam-note">{note}</p>
      </figure>
    </section>
  );
}
