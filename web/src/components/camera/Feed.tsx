import { useEffect, useState, type SyntheticEvent } from "react";
import { useOverlayBoxes } from "@/hooks/useOverlayBoxes";
import { isOverlayFresh } from "@/lib/boxes";
import type { Overlay } from "@/lib/types";

type FeedState = "off" | "connecting" | "live" | "retrying";

const FEED_RETRY_MS = 2000;
// Swapping the src for a blank image is what actually closes the MJPEG connection.
const BLANK_IMAGE = "data:image/gif;base64,R0lGODlhAQABAAAAACw=";

interface FeedProps {
  name: string;
  src: string;
  alt: string;
  overlay: Overlay | null | undefined;
  cameraOk: boolean;
  wanted: boolean; // peeking at this camera: only then does it stream
  hidden: boolean; // the other camera is the one showing
  onRatio: (name: string, ratio: number) => void; // the camera's shape, width over height, so the tile can take it
}

// One camera's picture with its boxes, filling the tile. The tile takes the camera's shape (onRatio), so the whole
// frame shows with no bars, and the boxes, fractions of the frame, sit on it.
export function Feed({ name, src, alt, overlay, cameraOk, wanted, hidden, onRatio }: FeedProps) {
  const [state, setState] = useState<FeedState>("off");
  const [stamp, setStamp] = useState(0);
  const boxes = useOverlayBoxes(overlay, cameraOk);
  const fresh = isOverlayFresh(overlay, cameraOk);
  const frameWidth = overlay?.frame_width;
  const frameHeight = overlay?.frame_height;

  useEffect(() => {
    setState(wanted ? "connecting" : "off");
    setStamp(Date.now());
  }, [wanted]);

  useEffect(() => {
    const timer = state === "retrying" ? window.setTimeout(() => setStamp(Date.now()), FEED_RETRY_MS) : undefined;
    return () => window.clearTimeout(timer);
  }, [state, stamp]);

  useEffect(() => {
    if (fresh && frameWidth != null && frameHeight != null && frameHeight > 0) {
      onRatio(name, frameWidth / frameHeight);
    }
  }, [fresh, frameWidth, frameHeight, name, onRatio]);

  const handleLoad = (event: SyntheticEvent<HTMLImageElement>) => {
    const image = event.currentTarget;
    if (state !== "off") {
      setState("live");
      if (image.naturalWidth > 0 && image.naturalHeight > 0) {
        onRatio(name, image.naturalWidth / image.naturalHeight);
      }
    }
  };
  const handleError = () => {
    if (state !== "off") {
      setState("retrying");
    }
  };

  return (
    <div className={state === "live" ? "cam-picture is-live" : "cam-picture"} hidden={hidden}>
      <img alt={alt} width="640" height="480" src={wanted ? `${src}?t=${stamp}` : BLANK_IMAGE} onLoad={handleLoad} onError={handleError} />
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
    </div>
  );
}
