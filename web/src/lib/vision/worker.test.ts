import { expect, it } from "vitest";
import type { RunModel } from "@/lib/vision/detector";
import fixture from "@/lib/vision/python-fixture.json";
import { readFrame } from "@/lib/vision/worker";
import { near } from "@/test/near";

const blank = (width: number, height: number) => ({ width, height, data: new Uint8ClampedArray(width * height * 3) });
const yolo: RunModel = async () => [Float32Array.from(fixture.objects.output)];

it("drops the phone a mouse outscores in the same place before the tracker sees it, like the Pi's read_frame", async () => {
  const reading = await readFrame(blank(640, 480), { objects: yolo, hands: null });
  expect(reading.phones.map((phone) => phone.confidence)).toEqual(near([0.6, 0.3]));
});
