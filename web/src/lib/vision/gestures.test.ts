import { expect, it } from "vitest";
import { GestureTracker, readHandShape, readSign } from "@/lib/vision/gestures";
import fixture from "@/lib/vision/python-fixture.json";

const toHand = (joints: number[][]) => ({ confidence: 0.9, joints });

it("reads the same hand shapes and signs as the Pi, drawn and random", () => {
  for (const [index, { joints, shape, sign }] of fixture.shapes.cases.entries()) {
    expect(readHandShape(joints), `hand ${index}`).toEqual(shape);
    expect(readSign([toHand(joints)]), `hand ${index}`).toBe(sign);
  }
  // The drawn ones: a peace sign, the same two fingers side by side, a fist, an open hand, one finger, peace sideways.
  expect(fixture.shapes.cases.slice(0, 6).map((hand) => hand.sign)).toEqual(["peace", null, null, null, null, "peace"]);
});

it("finds a sign on any hand, and none without hands", () => {
  const [peace, , fist] = fixture.shapes.cases.map((hand) => toHand(hand.joints));
  expect([readSign([fist, peace]), readSign([])]).toEqual([fixture.shapes.fist_then_peace_sign, fixture.shapes.no_hands_sign]);
});

it("holds, fires and waits for the hands to come down like the Pi", () => {
  for (const [index, { steps, fired }] of fixture.holds.entries()) {
    const tracker = new GestureTracker();
    expect(
      steps.map((step) => tracker.hold(step.gesture, step.now)),
      `sequence ${index}`,
    ).toEqual(fired);
  }
});
