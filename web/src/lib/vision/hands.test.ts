import { expect, it } from "vitest";
import type { RunModel } from "@/lib/vision/detector";
import { buildAnchors, decodeHand, decodePalms, findHandCrop, findPhonesInHand, scanHands } from "@/lib/vision/hands";
import fixture from "@/lib/vision/python-fixture.json";
import { near } from "@/test/near";

const ROWS = 2016;

function readPalmOutputs(): { rows: Float32Array; logits: Float32Array } {
  const rows = new Float32Array(ROWS * 18);
  const logits = new Float32Array(ROWS).fill(-10);
  for (const special of fixture.palms.specials) {
    rows.set(special.row, special.index * 18);
    logits[special.index] = special.logit;
  }
  return { rows, logits };
}

const palmLetterbox = {
  picture: { width: 1, height: 1, data: new Uint8ClampedArray(3) },
  scale: fixture.palms.letterbox.scale,
  padLeft: fixture.palms.letterbox.pad_left,
  padTop: fixture.palms.letterbox.pad_top,
};

it("builds the palm model's 2016 anchors in the Pi's order", () => {
  const anchors = buildAnchors();
  expect(anchors.length / 2).toBe(fixture.palms.anchor_count);
  for (const [index, [x, y]] of Object.entries(fixture.palms.anchor_samples)) {
    expect([anchors[Number(index) * 2], anchors[Number(index) * 2 + 1]], index).toEqual([Math.fround(x), Math.fround(y)]);
  }
});

it("decodes made-up palm rows to the same palms as the Pi: sigmoid cutoff, NMS, then the two best", () => {
  const { rows, logits } = readPalmOutputs();
  expect(decodePalms(rows, logits, palmLetterbox)).toEqual(near(fixture.palms.palms));
});

it("turns each palm into the same hand crop as the Pi", () => {
  for (const { points, warp } of fixture.hands.crops) {
    expect(findHandCrop({ confidence: 1, box: { x1: 0, y1: 0, x2: 0, y2: 0 }, points })).toEqual(near(warp, 9));
  }
});

it("maps the hand model's joints back onto the frame, and drops a hand under 0.8", () => {
  const joints = Float32Array.from(fixture.hands.joints);
  for (const { confidence, hand } of fixture.hands.decoded) {
    expect(decodeHand(joints, confidence, fixture.hands.warp)).toEqual(near(hand));
  }
});

it("only keeps the phones in or near a hand", () => {
  const hands = fixture.phones_in_hand.hands.map((joints) => ({ confidence: 0.9, joints }));
  expect(findPhonesInHand(fixture.phones_in_hand.phones, hands)).toEqual(fixture.phones_in_hand.held);
});

it("runs the hand model once per palm, on a 224x224 crop", async () => {
  const shown: number[][] = [];
  const { rows, logits } = readPalmOutputs();
  const palm: RunModel = async (_, dims) => {
    shown.push(dims);
    return [rows, logits];
  };
  const hand: RunModel = async (_, dims) => {
    shown.push(dims);
    return [Float32Array.from(fixture.hands.joints), Float32Array.of(0.93)];
  };
  const found = await scanHands({ width: 640, height: 480, data: new Uint8ClampedArray(640 * 480 * 3) }, { palm, hand });
  expect(shown).toEqual([
    [1, 192, 192, 3],
    [1, 224, 224, 3],
    [1, 224, 224, 3],
  ]);
  expect(found).toHaveLength(2);
});
