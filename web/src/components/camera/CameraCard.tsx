import { ArrowLeftRight, Eye, Lock, PersonStanding } from "lucide-react";
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

// Hidden until Peek. With two cameras it shows one at a time, and the hidden one's stream stays closed.
export function CameraCard({ focus }: { focus: FocusStatus | undefined }) {
  const [peeking, setPeeking] = useState(() => readStored("peek", "0") === "1");
  const [view, setView] = useState(() => (readStored("camera", "front") === "side" ? "side" : "front"));
  const [feedStates, setFeedStates] = useState<Record<string, FeedState>>({});
  const [showPose, setShowPose] = useState(() => readStored("pose", "0") === "1");
  const sidePresent = focus?.side_camera === true;
  const onSide = sidePresent && view === "side";
  // The front overlay only has a "pose" when the Pi has the pose model loaded.
  const poseModel = focus?.overlay != null && "pose" in focus.overlay;

  const reportState = useCallback((name: string, state: FeedState) => {
    setFeedStates((current) => (current[name] === state ? current : { ...current, [name]: state }));
  }, []);
  const togglePeek = () => {
    writeStored("peek", peeking ? "0" : "1");
    setPeeking(!peeking);
  };
  const togglePose = () => {
    writeStored("pose", showPose ? "0" : "1");
    setShowPose(!showPose);
  };
  const flipCamera = () => {
    const next = view === "side" ? "front" : "side";
    writeStored("camera", next);
    setView(next);
  };

  const classes = ["card", "camera", "rise", peeking && "is-peeking", sidePresent && "has-side"];
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
            id="pose-toggle"
            className="button button-ghost button-small"
            hidden={!poseModel || onSide}
            aria-pressed={showPose}
            onClick={togglePose}
          >
            <PersonStanding size={16} strokeWidth={1.8} aria-hidden="true" />
            <span>{showPose ? "Hide pose" : "Show pose"}</span>
          </button>
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
          <button type="button" id="peek-toggle" className="button button-ghost button-small" aria-pressed={peeking} onClick={togglePeek}>
            <Eye size={16} strokeWidth={1.8} aria-hidden="true" />
            <span id="peek-label">{peeking ? "Hide" : "Peek"}</span>
          </button>
        </div>
      </div>
      <div className="camera-body">
        <div className="feeds">
          {FEEDS.map((feed) => (
            <Feed
              key={feed.name}
              name={feed.name}
              src={feed.src}
              label={feed.label}
              alt={feed.alt}
              overlay={focus?.[feed.overlayKey]}
              cameraOk={focus?.camera_ok ?? false}
              hidden={feed.name === "side" ? !onSide : onSide}
              wanted={peeking}
              showPose={showPose && feed.name === "front"}
              onState={reportState}
            />
          ))}
          <div className="veil">
            <span className="veil-icon" aria-hidden="true">
              <Lock size={20} strokeWidth={1.8} />
            </span>
            <span className="veil-title">Hidden while you work</span>
            <span className="veil-text">The readings keep updating. Peek when you want the picture.</span>
          </div>
        </div>
        <Readings focus={focus} />
      </div>
    </section>
  );
}
