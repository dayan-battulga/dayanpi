import { useEffect, useRef } from "react";
import { TOAST_S, showToast } from "@/components/ui/toaster";
import type { FocusStatus } from "@/lib/types";

const GESTURE_COPY: Record<string, string> = {
  peace: "✌️ Peace sign: reading your to-dos",
};

// A toast for each hand sign, so it's clear it fired even with the speaker off. Every snapshot repeats the last sign
// with a growing age, so a new one is an age that went down (or a first one that's still fresh).
export function useGestureToast(gesture: FocusStatus["gesture"]): void {
  const lastAge = useRef(Infinity);
  useEffect(() => {
    const age = gesture?.age_s ?? Infinity;
    if (gesture != null && age < lastAge.current && age < TOAST_S) {
      showToast(GESTURE_COPY[gesture.name] ?? gesture.name);
    }
    lastAge.current = age;
  }, [gesture]);
}
