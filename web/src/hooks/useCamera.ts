import { useEffect, useState, useSyncExternalStore } from "react";
import { CameraTracker, type CameraSource, type CameraView } from "@/components/track/cameraTracker";

export interface Camera extends CameraView {
  turnOn: () => void; // a click: asks Chrome for the camera
  turnOff: () => void;
}

// The browser's camera, kept by the frame so it runs while you move between pages (components/track/cameraTracker.ts).
// source is the desk's camera_source from the stream; it does nothing for a desk on the Pi's cameras.
export function useCamera(source: CameraSource): Camera {
  const [tracker] = useState(() => new CameraTracker());
  const view = useSyncExternalStore(tracker.subscribe, tracker.getView);
  useEffect(() => {
    tracker.attach();
    return tracker.detach;
  }, [tracker]);
  useEffect(() => {
    tracker.setSource(source);
  }, [tracker, source]);
  const camera = { ...view, turnOn: tracker.turnOn, turnOff: tracker.turnOff };
  return camera;
}
