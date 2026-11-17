import { Navigate } from "react-router";
import { CameraCard } from "@/components/camera/CameraCard";
import { useFrame } from "@/components/frame/Frame";
import { PiSection } from "@/components/pi/PiSection";
import { readPiStats } from "@/lib/pi";

// The Pi, at /pi, for the owner: the cameras, then the Pi's own numbers. A member who types it in lands on the desk.
export function PiPage() {
  const { snapshot, user } = useFrame();
  const focus = snapshot?.focus;
  const owner = (
    <div className="live pi-page">
      <CameraCard focus={focus} />
      <PiSection stats={readPiStats(snapshot)} focus={focus} />
    </div>
  );
  // Nothing until /api/me says who you are, so a member never sees a flash of the owner's page.
  const page = user == null ? null : user.role === "owner" ? owner : <Navigate to="/me" replace />;
  return page;
}
