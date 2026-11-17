import { Navigate } from "react-router";
import { CameraCard } from "@/components/camera/CameraCard";
import { useFrame } from "@/components/frame/Frame";
import { PiSection } from "@/components/pi/PiSection";
import { readPiStats } from "@/lib/pi";

// The Pi, at /pi, for the owner: the camera and the Pi's own numbers. A member who types it in lands on the desk.
export function PiPage() {
  const { snapshot, user } = useFrame();
  const focus = snapshot?.focus;
  const stats = readPiStats(snapshot);
  const undervoltage = stats?.throttle.is_undervoltage ?? false;
  const owner = (
    <div className="live">
      {undervoltage && (
        <p id="power-alert" role="alert" className="pill pill-hot">
          Undervoltage
        </p>
      )}
      <div className="row">
        <CameraCard focus={focus} />
      </div>
      <PiSection stats={stats} focus={focus} />
    </div>
  );
  // Nothing until /api/me says who you are, so a member never sees a flash of the owner's page.
  const page = user == null ? null : user.role === "owner" ? owner : <Navigate to="/me" replace />;
  return page;
}
