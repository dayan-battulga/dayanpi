import { expect, it } from "vitest";
import { decodeObjects, findPhones, findZoomRegion, fitToInput, INPUT_HEIGHT, INPUT_WIDTH, pickBoxes, scanDesk, type RunModel } from "@/lib/vision/detector";
import { fitSquare, PALM_INPUT_SIZE } from "@/lib/vision/hands";
import fixture from "@/lib/vision/python-fixture.json";
import { near } from "@/test/near";

const blank = (width: number, height: number) => ({ width, height, data: new Uint8ClampedArray(width * height * 3) });
const readLetterbox = (letterbox: { scale: number; pad_left: number; pad_top: number }) => ({
  picture: blank(1, 1),
  scale: letterbox.scale,
  padLeft: letterbox.pad_left,
  padTop: letterbox.pad_top,
});

it("letterboxes every frame size into 640x480 and the palm's 192x192 like the Pi", () => {
  for (const expected of fixture.letterboxes) {
    const picture = blank(expected.width, expected.height);
    const full = fitToInput(picture);
    const square = fitSquare(picture, PALM_INPUT_SIZE);
    const size = `${expected.width}x${expected.height}`;
    expect({ scale: full.scale, pad_left: full.padLeft, pad_top: full.padTop }, size).toEqual(expected.input);
    expect({ scale: square.scale, pad_left: square.padLeft, pad_top: square.padTop }, size).toEqual(expected.palm);
    expect([full.picture.width, full.picture.height, square.picture.width, square.picture.height]).toEqual([INPUT_WIDTH, INPUT_HEIGHT, 192, 192]);
  }
});

it("pads with gray 114", () => {
  const { picture } = fitToInput(blank(768, 432));
  expect([picture.data[0], picture.data.at(-1)]).toEqual([114, 114]);
});

it("decodes made-up YOLO output to the same people and phones as the Pi", () => {
  const { output, letterbox, detections } = fixture.objects;
  expect(decodeObjects(Float32Array.from(output), readLetterbox(letterbox))).toEqual(near(detections));
});

it("keeps what cv2.dnn.NMSBoxes keeps", () => {
  // IoU 0.4925 stays, 0.5 exactly stays, a score at the cutoff goes, and two empty boxes are the same box.
  expect(pickBoxes([[110, 50, 200, 100], [178, 50, 200, 100]], [0.9, 0.8])).toEqual([0, 1]);
  expect(pickBoxes([[5, 5, 10, 10], [5, 2.5, 10, 5]], [0.9, 0.8])).toEqual([0, 1]);
  expect(pickBoxes([[5, 5, 10, 10], [52.5, 52.5, 5, 5]], [0.9, 0.15])).toEqual([0]);
  expect(pickBoxes([[0, 0, 0, 0], [0, 0, 0, 0]], [0.9, 0.8])).toEqual([0]);
});

it("zooms on the same region as the Pi", () => {
  for (const { person, width, height, region } of fixture.zooms) {
    expect(findZoomRegion(person, width, height)).toEqual(region);
  }
});

// A YOLO run that answers with the fixture's tensor and remembers the pictures it was shown.
function fakeYolo(): { run: RunModel; shown: number[][] } {
  const shown: number[][] = [];
  const run: RunModel = async (input, dims) => {
    shown.push(dims);
    expect(input.length).toBe(dims.reduce((product, size) => product * size, 1));
    return [Float32Array.from(fixture.objects.output)];
  };
  return { run, shown };
}

it("runs the zoomed pass around the main person and moves its phones back onto the frame", async () => {
  const yolo = fakeYolo();
  const scan = await scanDesk(blank(640, 480), yolo.run);
  expect(yolo.shown).toEqual([
    [1, 3, 480, 640],
    [1, 3, 480, 640],
  ]);
  expect(scan.people.map((person) => person.confidence)).toEqual(near([0.9, 0.7, 0.6, 0.6, 0.4]));
  // The full-frame pass's phones never count: these are the zoomed pass's, shifted by the region's corner.
  const region = findZoomRegion(scan.people[0].box, 640, 480);
  expect(scan.phones.map((phone) => phone.box.x1 - region.x1)).not.toEqual(scan.phones.map((phone) => phone.box.x1));
  expect(scan.phones.map((phone) => phone.confidence)).toEqual(near([0.6, 0.3]));
});

it("skips the zoomed pass without a person at 0.5 or more", async () => {
  const yolo = fakeYolo();
  const phones = await findPhones(blank(640, 480), [{ label: "person", confidence: 0.49, box: { x1: 0, y1: 0, x2: 10, y2: 10 } }], yolo.run);
  expect([phones, yolo.shown]).toEqual([[], []]);
});
