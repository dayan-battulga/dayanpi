import type { CSSProperties } from "react";

// The cards rise in one after another; --d is each one's place in the queue (see .rise).
export function riseDelay(order: number): CSSProperties {
  const style = { "--d": order } as CSSProperties;
  return style;
}
