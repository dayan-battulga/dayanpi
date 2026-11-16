import { useEffect, useState, type SyntheticEvent } from "react";
import { useOverlayBoxes } from "@/hooks/useOverlayBoxes";
import { isOverlayFresh } from "@/lib/boxes";
import type { FeedState } from "@/lib/feeds";
import type { Overlay } from "@/lib/types";

const FEED_RETRY_MS = 2000;
// Swapping the src for a blank image is what actually closes the MJPEG connection.
const BLANK_IMAGE = "data:image/gif;base64,R0lGODlhAQABAAAAACw=";

interface FeedProps {
  name: string;
  src: string;
  label: string;
  alt: string;
  overlay: Overlay | null | undefined;
  cameraOk: boolean;
  hidden: boolean;
  wanted: boolean;
  onState: (name: string, state: FeedState) => void;
}

// One camera feed with its boxes. It streams only while wanted (peeking) and not hidden.
export function Feed({ name, src, label, alt, overlay, cameraOk, hidden, wanted, onState }: FeedProps) {
  const open = wanted && !hidden;
  const [state, setState] = useState<FeedState>("off");
  const [stamp, setStamp] = useState(0);
  const [aspect, setAspect] = useState<string | undefined>(undefined);
  const boxes = useOverlayBoxes(overlay, cameraOk);
  const fresh = isOverlayFresh(overlay, cameraOk);
  const frameWidth = overlay?.frame_width;
  const frameHeight = overlay?.frame_height;

  useEffect(() => {
    setState(open ? "connecting" : "off");
    setStamp(Date.now());
  }, [open]);

  useEffect(() => onState(name, state), [name, state, onState]);

  useEffect(() => {
    const timer = state === "retrying" ? window.setTimeout(() => setStamp(Date.now()), FEED_RETRY_MS) : undefined;
    return () => window.clearTimeout(timer);
  }, [state, stamp]);

  // The feed is drawn with object-fit: cover, so the frame must take the camera's shape or the
  // boxes would sit over a cropped picture. The overlay says it every second; the picture's own
  // size covers the focus tracker being off.
  useEffect(() => {
    if (fresh && frameWidth != null && frameHeight != null) {
      setAspect(`${frameWidth} / ${frameHeight}`);
    }
  }, [fresh, frameWidth, frameHeight]);

  const handleLoad = (event: SyntheticEvent<HTMLImageElement>) => {
    const image = event.currentTarget;
    if (state !== "off") {
      setState("live");
      if (image.naturalWidth > 0) {
        setAspect(`${image.naturalWidth} / ${image.naturalHeight}`);
      }
    }
  };
  const handleError = () => {
    if (state !== "off") {
      setState("retrying");
    }
  };

  return (
    <div className={state === "live" ? "feed-frame is-live" : "feed-frame"} hidden={hidden} style={{ aspectRatio: aspect }}>
      <img alt={alt} width="640" height="480" src={open ? `${src}?t=${stamp}` : BLANK_IMAGE} onLoad={handleLoad} onError={handleError} />
      <div className="overlay" aria-hidden="true">
        {boxes.map((box) => (
          <div
            key={box.renderKey}
            className={["box", `is-${box.kind}`, box.placed.labelInside && "label-inside", box.leaving && "is-leaving"].filter(Boolean).join(" ")}
            style={{ left: box.placed.left, top: box.placed.top, width: box.placed.width, height: box.placed.height }}
          >
            <span className="box-label">{box.placed.text}</span>
          </div>
        ))}
      </div>
      <div className="scan" aria-hidden="true"></div>
      <span className="feed-label label">{label}</span>
    </div>
  );
}
