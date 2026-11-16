import { expect, it } from "vitest";
import { LIMBS, buildSkeleton } from "@/lib/pose";
import type { PosePoint } from "@/lib/types";

const LEFT_WRIST = 9;
const LEFT_ELBOW = 7;

function makePose(confidence = 0.9): PosePoint[] {
  const points = Array.from({ length: 17 }, (_, index): PosePoint => [index / 20, 0.5, confidence]);
  return points;
}

it("puts every clear point in frame pixels and draws every limb", () => {
  const skeleton = buildSkeleton(makePose(), 640, 480);
  expect(skeleton.dots).toHaveLength(17);
  expect(skeleton.lines).toHaveLength(LIMBS.length);
  expect(skeleton.dots[10]).toEqual({ key: "10", x: 320, y: 240 });
  expect(skeleton.lines.find((line) => line.key === "7-9")).toEqual({ key: "7-9", x1: 224, y1: 240, x2: 288, y2: 240 });
});

it("skips a point the model isn't sure about, and every limb that ends there", () => {
  const points = makePose();
  points[LEFT_WRIST] = [0.45, 0.5, 0.49];
  const skeleton = buildSkeleton(points, 768, 432);
  expect(skeleton.dots.map((dot) => dot.key)).not.toContain(String(LEFT_WRIST));
  expect(skeleton.lines.map((line) => line.key)).not.toContain(`${LEFT_ELBOW}-${LEFT_WRIST}`);
  expect(skeleton.lines).toHaveLength(LIMBS.length - 1);
});

it("draws nothing when no point is clear", () => {
  expect(buildSkeleton(makePose(0.2), 640, 480)).toEqual({ lines: [], dots: [] });
});
