import { formatCompactMinutes } from "@/lib/calendar";
import { formatDuration } from "@/lib/format";

// The mockups' two rings, both drawn in a 36-unit box: RoomV2's seat chip (the Desk's stats line too) and DayPopup's goal box.
const RINGS = {
  small: { size: 18, radius: 14, stroke: 5 },
  large: { size: 34, radius: 15, stroke: 3.5 },
};

// "2h 40m of 4h"
export function formatGoalProgress(seconds: number, goalMinutes: number): string {
  const progress = `${formatDuration(seconds)} of ${formatCompactMinutes(goalMinutes)}`;
  return progress;
}

// Today's focus toward your goal, filling clockwise from the top. Decoration only: the words next to it say the same.
export function GoalRing({ seconds, goalMinutes, size }: { seconds: number; goalMinutes: number; size: keyof typeof RINGS }) {
  const ring = RINGS[size];
  const around = 2 * Math.PI * ring.radius;
  const share = Math.min(1, Math.max(0, seconds / (goalMinutes * 60)));
  return (
    <svg className="goal-ring" width={ring.size} height={ring.size} viewBox="0 0 36 36" aria-hidden="true">
      <circle className="goal-ring-track" cx="18" cy="18" r={ring.radius} fill="none" strokeWidth={ring.stroke} />
      {share > 0 && (
        <circle
          className="goal-ring-fill"
          cx="18"
          cy="18"
          r={ring.radius}
          fill="none"
          strokeWidth={ring.stroke}
          strokeLinecap="round"
          strokeDasharray={`${(share * around).toFixed(1)} ${around.toFixed(1)}`}
        />
      )}
    </svg>
  );
}
