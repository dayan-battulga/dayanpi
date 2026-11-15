import type { FocusStatus } from "@/lib/types";

const READINGS = [
  { key: "person", label: "Person", className: "reading" },
  { key: "phone", label: "Phone in hand", className: "reading reading-phone" },
] as const;

function describeSpeed(focus: FocusStatus | undefined): string {
  let speed = "--";
  if (focus != null && focus.camera_ok && focus.last_check != null) {
    speed = `~${Math.round(focus.last_check.elapsed_ms)} ms each`;
  } else if (focus != null) {
    speed = focus.enabled ? "no frames" : "detector off";
  }
  return speed;
}

// "What the Pi sees": the detector's latest numbers, the best of both cameras.
export function Readings({ focus }: { focus: FocusStatus | undefined }) {
  const check = focus?.camera_ok ? focus.last_check : null;
  return (
    <div className="readings">
      <h3 className="label">What the Pi sees</h3>
      <div className="reading-rows">
        {READINGS.map(({ key, label, className }) => {
          const value = check == null ? null : check[key];
          return (
            <div key={key} className={className} data-key={key}>
              <div className="reading-line">
                <span>{label}</span>
                <span className="reading-value mono">{value == null ? "—" : value.toFixed(2)}</span>
              </div>
              <div className="reading-track">
                <div className="reading-fill" style={{ width: `${value == null ? 0 : Math.round(value * 100)}%` }}></div>
              </div>
            </div>
          );
        })}
      </div>
      <div className="readings-foot mono muted small">
        <span>1 check / s</span>
        <span id="check-ms">{describeSpeed(focus)}</span>
      </div>
    </div>
  );
}
