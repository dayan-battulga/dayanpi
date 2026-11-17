import { expect, it } from "vitest";
import { invertAffine, resizePicture, roundHalfEven, warpPicture } from "@/lib/vision/image";
import fixture from "@/lib/vision/python-fixture.json";
import { findLargestDifference, near } from "@/test/near";

const readPicture = (picture: { width: number; height: number; data: number[] }) => ({ ...picture, data: Uint8ClampedArray.from(picture.data) });

it("rounds halves to even like Python", () => {
  expect([0.5, 1.5, 2.5, -0.5, -1.5, 2.4, 2.6, 3].map(roundHalfEven)).toEqual([0, 2, 2, 0, -2, 2, 3, 3]);
});

it("resizes like cv2.resize, give or take OpenCV's fixed-point rounding", () => {
  const source = readPicture(fixture.resize.source);
  for (const expected of fixture.resize.results) {
    const resized = resizePicture(source, expected.width, expected.height);
    expect(findLargestDifference(resized.data, expected.data), `${expected.width}x${expected.height}`).toBeLessThanOrEqual(1);
  }
});

it("warps like cv2.warpAffine, black outside the picture", () => {
  const { source, warp, result } = fixture.warp;
  const warped = warpPicture(readPicture(source), warp, result.width);
  // cv2 made it 14 wide by 12 high; the hand crop is always square, so compare the rows both have.
  const rows = warped.data.subarray(0, result.width * result.height * 3);
  expect(findLargestDifference(rows, result.data)).toBeLessThanOrEqual(2);
});

it("inverts an affine matrix and back", () => {
  const warp = fixture.warp.warp;
  expect(invertAffine(invertAffine(warp))).toEqual(near(warp, 9));
});
