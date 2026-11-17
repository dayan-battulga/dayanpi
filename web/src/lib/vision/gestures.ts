import type { Hand } from "@/lib/vision/hands";

// dayanpi/vision/gestures.py for the browser: hand shapes into hand signs. They're holds, not flicks: one check
// a second is too slow to catch a flick.

export const PEACE = "peace";
export const HOLD_SECONDS: Record<string, number> = { [PEACE]: 1.0 };

const WRIST_JOINT = 0;
// Each finger's tip and middle joint. The thumb isn't read: peace ignores it.
const FINGER_JOINTS = { index: [8, 6], middle: [12, 10], ring: [16, 14], pinky: [20, 18] } as const;
const INDEX_KNUCKLE = 5;
const MIDDLE_KNUCKLE = 9;
// "v": the index and middle tips are at least this many times as far apart as their knuckles.
const V_SPREAD = 1.8;
const ALLOWED_MISSES = 1;

export type HandPart = keyof typeof FINGER_JOINTS | "v";
export type HandShape = Record<HandPart, boolean>;

// One finger rule per sign: true = open, false = closed, a finger left out doesn't matter.
export const HAND_SIGNS: Record<string, Partial<HandShape>> = { [PEACE]: { index: true, middle: true, ring: false, pinky: false, v: true } };

// numpy's norm: the square root of the sum of squares, over the first `dimensions` numbers.
function measureDistance(first: number[], second: number[], dimensions: number): number {
  let sum = 0;
  for (let axis = 0; axis < dimensions; axis++) {
    sum += (first[axis] - second[axis]) ** 2;
  }
  const distance = Math.sqrt(sum);
  return distance;
}

// Each finger, open when its tip is farther from the wrist than its middle joint, plus "v". Distances, not
// directions, so a tilted hand reads the same; the V uses x and y only, since the depth is the noisiest number.
export function readHandShape(joints: number[][]): HandShape {
  const wrist = joints[WRIST_JOINT];
  const isOpen = (finger: keyof typeof FINGER_JOINTS) => {
    const [tip, middle] = FINGER_JOINTS[finger];
    return measureDistance(joints[tip], wrist, 3) > measureDistance(joints[middle], wrist, 3);
  };
  const tipGap = measureDistance(joints[FINGER_JOINTS.index[0]], joints[FINGER_JOINTS.middle[0]], 2);
  const knuckleGap = measureDistance(joints[INDEX_KNUCKLE], joints[MIDDLE_KNUCKLE], 2);
  const shape = {
    index: isOpen("index"),
    middle: isOpen("middle"),
    ring: isOpen("ring"),
    pinky: isOpen("pinky"),
    v: tipGap >= V_SPREAD * knuckleGap,
  };
  return shape;
}

// The first sign any hand makes, or null. A hand makes a sign when every part of its rule matches.
export function readSign(hands: Hand[]): string | null {
  let sign: string | null = null;
  for (const hand of hands) {
    const shape = readHandShape(hand.joints);
    sign ??= Object.keys(HAND_SIGNS).find((name) => Object.entries(HAND_SIGNS[name]).every(([part, wanted]) => shape[part as HandPart] === wanted)) ?? null;
  }
  return sign;
}

interface GestureHold {
  name: string;
  startedAt: number;
  hasFired: boolean;
  misses: number;
}

// Feed it the sign each check shows (readSign(), or null) and it says when one fires:
// - A hold starts on the first check that shows a sign, and fires on the first check that still shows it once
//   HOLD_SECONDS have passed. Each hold fires once.
// - A hold survives one check without it; a second miss in a row ends it, and whatever that check shows starts
//   the next one.
// - Once a sign fires, nothing else can until two checks in a row show no sign.
export class GestureTracker {
  private current: GestureHold | null = null;

  // now is the caller's clock in seconds.
  hold(gesture: string | null, now: number): string | null {
    const hold = this.current;
    let fired: string | null = null;
    if (hold === null) {
      this.startHold(gesture, now);
    } else if (gesture === hold.name) {
      hold.misses = 0;
      if (!hold.hasFired && now - hold.startedAt >= HOLD_SECONDS[hold.name]) {
        hold.hasFired = true;
        fired = hold.name;
      }
    } else {
      this.countMiss(hold, gesture, now);
    }
    return fired;
  }

  private startHold(gesture: string | null, now: number): void {
    this.current = gesture === null ? null : { name: gesture, startedAt: now, hasFired: false, misses: 0 };
  }

  private countMiss(hold: GestureHold, gesture: string | null, now: number): void {
    hold.misses = hold.hasFired && gesture !== null ? 0 : hold.misses + 1;
    if (hold.misses > ALLOWED_MISSES) {
      this.startHold(gesture, now);
    }
  }
}
