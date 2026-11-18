import { useEffect, useRef } from "react";
import { toast } from "sonner";
import { TOAST_S } from "@/components/ui/toaster";
import type { FocusStatus } from "@/lib/types";

// A toast for each hand sign, so it's clear it fired even with the speaker off. Every snapshot repeats the last sign
// with a growing age, so a new one is an age that went down (or a first one that's still fresh). The peace sign has
// its own pill instead (frame/PeacePill.tsx).
export function useGestureToast(gesture: FocusStatus["gesture"]): void {
  const lastAge = useRef(Infinity);
  useEffect(() => {
    const age = gesture?.age_s ?? Infinity;
    if (gesture != null && age < lastAge.current && age < TOAST_S && gesture.name !== "peace") {
      toast(gesture.name);
    }
    lastAge.current = age;
  }, [gesture]);
}
