import type { PosePoint } from "@/lib/types";

// Weaker points are guesses; the arm gestures use the same cutoff.
export const POSE_MIN_CONFIDENCE = 0.5;
// COCO's 17 points in order: nose, eyes, ears, shoulders, elbows, wrists, hips, knees, ankles
// (each pair left then right). The limbs are Ultralytics' skeleton, counted from 0.
export const LIMBS = [
  [15, 13], [13, 11], [16, 14], [14, 12], [11, 12],
  [5, 11], [6, 12], [5, 6], [5, 7], [6, 8], [7, 9], [8, 10],
  [1, 2], [0, 1], [0, 2], [1, 3], [2, 4], [3, 5], [4, 6],
] as const;

export interface SkeletonLine {
  key: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface SkeletonDot {
  key: string;
  x: number;
  y: number;
}

export interface Skeleton {
  lines: SkeletonLine[];
  dots: SkeletonDot[];
}

// The keypoints in frame pixels, for an SVG laid over the feed with the frame's own viewBox.
// A limb is drawn only when both of its ends are clear.
export function buildSkeleton(points: PosePoint[], width: number, height: number): Skeleton {
  const clear = points.map(([x, y, confidence]) => (confidence >= POSE_MIN_CONFIDENCE ? { x: x * width, y: y * height } : null));
  const lines = LIMBS.flatMap(([from, to]) => {
    const start = clear[from];
    const end = clear[to];
    const line = start && end ? [{ key: `${from}-${to}`, x1: start.x, y1: start.y, x2: end.x, y2: end.y }] : [];
    return line;
  });
  const dots = clear.flatMap((point, index) => (point ? [{ key: String(index), ...point }] : []));
  const skeleton = { lines, dots };
  return skeleton;
}
