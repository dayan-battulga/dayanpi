import { useEffect, useState, useSyncExternalStore } from "react";
import { CameraTracker, type CameraMode, type CameraView } from "@/components/track/cameraTracker";

export interface Camera extends CameraView {
  turnOn: () => void; // a click: asks Chrome for the camera
  turnOff: () => void;
}

// The browser's camera, kept by the frame so it runs while you move between pages (components/track/cameraTracker.ts).
// mode is findCameraMode of the stream's focus; it does nothing for a desk whose checks and picture are both the Pi's.
export function useCamera(mode: CameraMode): Camera {
  const [tracker] = useState(() => new CameraTracker());
  const view = useSyncExternalStore(tracker.subscribe, tracker.getView);
  useEffect(() => {
    tracker.attach();
    return tracker.detach;
  }, [tracker]);
  useEffect(() => {
    tracker.setMode(mode);
  }, [tracker, mode]);
  const camera = { ...view, turnOn: tracker.turnOn, turnOff: tracker.turnOff };
  return camera;
}
