import { expect, it } from "vitest";
import { encodeBase64, findPictureCrop } from "@/lib/track";

it("writes a picture's bytes as base64 the Pi can read, even past one chunk", () => {
  const bytes = Uint8Array.from({ length: 70_000 }, (_, index) => (index * 7) % 256);
  const decoded = Uint8Array.from(atob(encodeBase64(bytes)), (character) => character.charCodeAt(0));
  expect(decoded).toEqual(bytes);
  expect(encodeBase64(new Uint8Array([0xff, 0xd8, 0xff]))).toBe("/9j/");
});

it("cuts the middle 16:9 out of any frame for the seat's picture", () => {
  expect(findPictureCrop(640, 480)).toEqual({ x: 0, y: 60, width: 640, height: 360 }); // a 4:3 webcam loses top and bottom
  expect(findPictureCrop(1280, 720)).toEqual({ x: 0, y: 0, width: 1280, height: 720 }); // already 16:9
  expect(findPictureCrop(480, 640)).toEqual({ x: 0, y: 185, width: 480, height: 270 }); // a phone held upright
});
