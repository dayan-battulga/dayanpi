import { describe, expect, it } from "vitest";
import { isOverlayFresh, placeBox, rankBoxes } from "@/lib/boxes";
import type { Overlay, OverlayBox } from "@/lib/types";

const PERSON: OverlayBox = { kind: "person", label: "person", confidence: 0.923, x: 0.1, y: 0.2, width: 0.5, height: 0.6 };
const PHONE: OverlayBox = { kind: "phone", label: "phone", confidence: 0.55, x: 0.4, y: 0.05, width: 0.1, height: 0.12 };

function makeOverlay(ageSeconds: number): Overlay {
  const overlay = { at: 0, age_s: ageSeconds, frame_width: 768, frame_height: 432, boxes: [PERSON] };
  return overlay;
}

describe("isOverlayFresh", () => {
  it("drops boxes older than 3 s, and any box while the camera is out", () => {
    expect(isOverlayFresh(makeOverlay(3), true)).toBe(true);
    expect(isOverlayFresh(makeOverlay(3.1), true)).toBe(false);
    expect(isOverlayFresh(makeOverlay(0), false)).toBe(false);
    expect(isOverlayFresh(null, true)).toBe(false);
  });
});

it("keys boxes by kind and rank, so the same box keeps its key from one check to the next", () => {
  const ranked = rankBoxes([PERSON, PHONE, { ...PERSON, confidence: 0.6 }]);
  expect(ranked.map((entry) => entry.key)).toEqual(["person-1", "phone-1", "person-2"]);
});

it("places a box in percentages of the frame, with the label inside near the top edge", () => {
  expect(placeBox(PERSON)).toEqual({ left: "10%", top: "20%", width: "50%", height: "60%", labelInside: false, text: "person 0.92" });
  expect(placeBox(PHONE).labelInside).toBe(true);
});
