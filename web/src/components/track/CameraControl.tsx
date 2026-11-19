import { Camera as CameraIcon, CameraOff, type LucideIcon } from "lucide-react";
import type { CameraStep, CameraTrouble } from "@/components/track/cameraTracker";
import type { Camera } from "@/hooks/useCamera";

// What the tracker page used to say when the camera wouldn't start: the title on its own on your seat and the Desk's
// line, with the fix in Settings → Camera.
export const CAMERA_PROBLEMS: Record<CameraTrouble, { title: string; fix: string }> = {
  denied: { title: "Camera is blocked", fix: "Click the camera icon in the address bar, allow it, then reload." },
  missing: { title: "No camera found", fix: "Check it's plugged in and turned on, then try again." },
  busy: { title: "The camera is busy", fix: "Another app is using it (Zoom, FaceTime, Photo Booth…). Close it, then try again." },
  chrome: { title: "This needs Chrome", fix: "Open this page in Chrome. Other browsers can't hand the camera to the tracker." },
  failed: { title: "The tracker stopped", fix: "The models stopped running. Try again, or reload the page." },
};

const STATUS: Record<CameraStep, string | null> = { off: null, starting: "Starting…", on: "Camera on", elsewhere: "Camera on in another tab", problem: null };

type Place = "seat" | "line" | "settings";

interface Action {
  label: string;
  icon: LucideIcon;
  run: () => void;
}

function findAction(camera: Camera): Action | null {
  const actions: Record<CameraStep, Action | null> = {
    off: { label: "Turn on camera", icon: CameraIcon, run: camera.turnOn },
    starting: null,
    on: { label: "Turn off", icon: CameraOff, run: camera.turnOff },
    elsewhere: null,
    problem: camera.problem === "chrome" ? null : { label: "Try again", icon: CameraIcon, run: camera.turnOn },
  };
  return actions[camera.step];
}

// Turn on camera, Turn off or Try again, and a quiet word on where the camera's at: one control for your seat in the
// Room, the Desk's line and Settings → Camera, each styled in place (dashboard.css .camera-control[data-place]). On
// the seat it follows Show/Hide my video's look, with an icon that stands alone on a phone.
export function CameraControl({ camera, place }: { camera: Camera; place: Place }) {
  const action = findAction(camera);
  const problem = camera.problem === null ? null : CAMERA_PROBLEMS[camera.problem];
  const status = camera.step === "problem" ? (problem?.title ?? null) : (STATUS[camera.step] ?? (place === "settings" ? "Camera off" : null));
  const StatusIcon = camera.step === "problem" ? CameraOff : CameraIcon;
  const ActionIcon = action?.icon ?? CameraIcon;
  return (
    <span className="camera-control" data-place={place} data-step={camera.step}>
      {status !== null && (
        <span className="camera-status" role="status">
          {place === "seat" && <StatusIcon size={18} strokeWidth={1.8} aria-hidden="true" />}
          <span className="camera-label">{status}</span>
        </span>
      )}
      {action !== null && (
        <button type="button" className={place === "settings" ? "button button-line button-small camera-button" : "camera-button"} onClick={action.run}>
          {place === "seat" && <ActionIcon size={18} strokeWidth={1.8} aria-hidden="true" />}
          <span className="camera-label">{action.label}</span>
        </button>
      )}
    </span>
  );
}
