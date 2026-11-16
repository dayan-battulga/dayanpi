import { ArrowLeftRight, Eye, Lock } from "lucide-react";
import { useCallback, useState } from "react";
import { Feed } from "@/components/camera/Feed";
import { Readings } from "@/components/camera/Readings";
import { riseDelay } from "@/components/shared/rise";
import { describeFeeds, type FeedState } from "@/lib/feeds";
import { readStored, writeStored } from "@/lib/storage";
import type { FocusStatus } from "@/lib/types";

const FEEDS = [
  { name: "front", src: "/video", label: "Front", alt: "Live front camera feed", overlayKey: "overlay" },
  { name: "side", src: "/video/side", label: "Side", alt: "Live side camera feed", overlayKey: "side_overlay" },
] as const;

// When /video answers 404 for this viewer: the full feeds only open for the owner on their own Tailscale devices.
const LOCKED_VEILS = {
  tailscale_only: { title: "Tailscale only", text: "Open the dashboard on one of your own Tailscale devices to see the camera." },
  owner_only: { title: "The camera is private", text: "The readings next to it still update." },
};
const PEEK_VEIL = { title: "Hidden while you work", text: "The readings keep updating. Peek when you want the picture." };

// Hidden until Peek. With two cameras it shows one at a time, and the hidden one's stream stays closed.
export function CameraCard({ focus }: { focus: FocusStatus | undefined }) {
  const [peeking, setPeeking] = useState(() => readStored("peek", "0") === "1");
  const [view, setView] = useState(() => (readStored("camera", "front") === "side" ? "side" : "front"));
  const [feedStates, setFeedStates] = useState<Record<string, FeedState>>({});
  // A feed waits for the first status, which says whether /video will answer this viewer at all.
  const access = focus?.camera_access ?? "open";
  const veil = access === "open" ? PEEK_VEIL : LOCKED_VEILS[access];
  const sidePresent = access === "open" && focus?.side_camera === true;
  const onSide = sidePresent && view === "side";

  const reportState = useCallback((name: string, state: FeedState) => {
    setFeedStates((current) => (current[name] === state ? current : { ...current, [name]: state }));
  }, []);
  const togglePeek = () => {
    writeStored("peek", peeking ? "0" : "1");
    setPeeking(!peeking);
  };
  const flipCamera = () => {
    const next = view === "side" ? "front" : "side";
    writeStored("camera", next);
    setView(next);
  };

  const classes = ["card", "camera", "rise", peeking && access === "open" && "is-peeking", sidePresent && "has-side"];
  return (
    <section id="camera" className={classes.filter(Boolean).join(" ")} style={riseDelay(2)} data-state={focus?.state ?? "unknown"} aria-label="Camera">
      <div className="card-head">
        <div className="card-title">
          <h2 className="label">Camera</h2>
          <span id="camera-status" className="mono muted small">
            {describeFeeds(Object.values(feedStates))}
          </span>
        </div>
        <div className="head-buttons">
          <button
            type="button"
            id="camera-flip"
            className="button button-ghost button-small"
            hidden={!sidePresent}
            aria-label={onSide ? "Show the front camera" : "Show the side camera"}
            onClick={flipCamera}
          >
            <ArrowLeftRight size={16} strokeWidth={1.8} aria-hidden="true" />
            <span id="camera-flip-label">{onSide ? "Front" : "Side"}</span>
          </button>
          <button type="button" id="peek-toggle" className="button button-ghost button-small" hidden={access !== "open"} aria-pressed={peeking} onClick={togglePeek}>
            <Eye size={16} strokeWidth={1.8} aria-hidden="true" />
            <span id="peek-label">{peeking ? "Hide" : "Peek"}</span>
          </button>
        </div>
      </div>
      <div className="camera-body">
        <div className="feeds">
          {access === "open" ? (
            FEEDS.map((feed) => (
              <Feed
                key={feed.name}
                name={feed.name}
                src={feed.src}
                label={feed.label}
                alt={feed.alt}
                overlay={focus?.[feed.overlayKey]}
                cameraOk={focus?.camera_ok ?? false}
                hidden={feed.name === "side" ? !onSide : onSide}
                wanted={peeking && focus != null}
                onState={reportState}
              />
            ))
          ) : (
            <div className="feed-frame" aria-hidden="true"></div>
          )}
          <div className="veil">
            <span className="veil-icon" aria-hidden="true">
              <Lock size={20} strokeWidth={1.8} />
            </span>
            <span className="veil-title">{veil.title}</span>
            <span className="veil-text">{veil.text}</span>
          </div>
        </div>
        <Readings focus={focus} />
      </div>
    </section>
  );
}
