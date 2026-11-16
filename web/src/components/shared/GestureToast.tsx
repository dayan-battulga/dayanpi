import type { FocusStatus } from "@/lib/types";

export const TOAST_S = 4;

const GESTURE_COPY: Record<string, string> = {
  peace: "✌️ Peace sign: reading your to-dos",
  next_page: "Right hand up: next sign page",
  previous_page: "Left hand up: previous sign page",
  toggle_block: "Both hands up: block toggled",
};

interface GestureToastProps {
  gesture: FocusStatus["gesture"];
  now: number;
  receivedAt: number;
}

// The last gesture or hand sign, for a few seconds, so it's clear it fired even with the speaker off.
// The live region stays mounted so screen readers announce each new one.
export function GestureToast({ gesture, now, receivedAt }: GestureToastProps) {
  const age = gesture == null ? Infinity : gesture.age_s + (now - receivedAt);
  const text = gesture != null && age < TOAST_S ? (GESTURE_COPY[gesture.name] ?? gesture.name) : "";
  return (
    <div role="status" aria-live="polite" className="pointer-events-none fixed inset-x-0 bottom-6 z-50 flex justify-center px-4">
      {text && (
        <span className="animate-[fade-in_0.3s_ease-out] rounded-full border bg-card px-4 py-2 text-sm font-medium text-card-foreground shadow-lg">
          {text}
        </span>
      )}
    </div>
  );
}
