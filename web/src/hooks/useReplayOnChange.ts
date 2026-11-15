import { useEffect, useRef } from "react";
import { replayAnimation, type MotionName } from "@/lib/motion";

// Replays a motion on the element each time value changes, but not on the first render.
export function useReplayOnChange<T extends Element>(value: unknown, motion: MotionName) {
  const ref = useRef<T>(null);
  const previous = useRef(value);
  useEffect(() => {
    if (previous.current !== value) {
      previous.current = value;
      replayAnimation(ref.current, motion);
    }
  }, [value, motion]);
  return ref;
}
