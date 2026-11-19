import type { Hand } from "@/lib/vision/hands";
import { cropPicture, padPicture, resizePicture, roundHalfEven, type Picture } from "@/lib/vision/image";

// dayanpi/vision/detector.py for the browser: YOLO26 nano finds people in the whole frame, letterboxed into
// 640x480, and phones in a second, zoomed-in pass around the main person. Both passes find mice too, for the mouse
// veto (dropMousePhones). YuNet's faces aren't ported: the tracker only logs their turn and tilt on its sample lines,
// and nothing reads those back.

export const INPUT_WIDTH = 640;
export const INPUT_HEIGHT = 480;
export const PAD_VALUE = 114;

export const PERSON_CLASS_ID = 0;
export const PHONE_CLASS_ID = 67;
export const MOUSE_CLASS_ID = 64;
// In this order: people first, like the Pi's dict.
export const LABELS = new Map([
  [PERSON_CLASS_ID, "person"],
  [PHONE_CLASS_ID, "phone"],
  [MOUSE_CLASS_ID, "mouse"],
]);
export const BOX_VALUES = 4;
export const CLASSES = 80;

export const MIN_CONFIDENCE = 0.15;
export const NMS_IOU = 0.5;
// A phone isn't a phone when a mouse box that scored at least as high overlaps it this much (IoU), or holds its center.
export const MOUSE_VETO_IOU = 0.3;

export const ZOOM_PERSON_MIN = 0.5;
export const ZOOM_MARGIN_SIDES = 0.15;
export const ZOOM_MARGIN_TOP = 0.05;
export const ZOOM_MARGIN_BOTTOM = 0.1;

export interface Box {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
}

export interface Detection {
  label: string;
  confidence: number;
  box: Box;
}

// What the tracker reads from one check. handsFailed isn't on the Pi's: the test page counts it.
export interface FrameReading {
  people: Detection[];
  phones: Detection[];
  hands: Hand[];
  handsFailed: boolean;
  elapsedMs: number;
}

// The model input plus what it takes to map boxes back onto the original frame.
export interface Letterbox {
  picture: Picture;
  scale: number;
  padLeft: number;
  padTop: number;
}

// The phones are the model's, before dropMousePhones (readFrame drops the mouse ones).
export interface DeskScan {
  people: Detection[];
  phones: Detection[];
  mice: Detection[];
}

// One model run: the input tensor and its shape in, the outputs out in the model's own order.
export type RunModel = (input: Float32Array, dims: number[]) => Promise<Float32Array[]>;

export function findBestConfidence(detections: Detection[]): number {
  const best = detections.reduce((most, detection) => Math.max(most, detection.confidence), 0);
  return best;
}

export function fitToInput(picture: Picture): Letterbox {
  const scale = Math.min(INPUT_WIDTH / picture.width, INPUT_HEIGHT / picture.height);
  const width = roundHalfEven(picture.width * scale);
  const height = roundHalfEven(picture.height * scale);
  const resized = width === picture.width && height === picture.height ? picture : resizePicture(picture, width, height);
  // Same rounding as Ultralytics, so boxes line up with what the model was trained on.
  const padX = (INPUT_WIDTH - width) / 2;
  const padY = (INPUT_HEIGHT - height) / 2;
  const padding = {
    left: roundHalfEven(padX - 0.1),
    right: roundHalfEven(padX + 0.1),
    top: roundHalfEven(padY - 0.1),
    bottom: roundHalfEven(padY + 0.1),
  };
  const letterbox = { picture: padPicture(resized, padding, PAD_VALUE), scale, padLeft: padding.left, padTop: padding.top };
  return letterbox;
}

export function mapToFrame(centerX: number, centerY: number, boxWidth: number, boxHeight: number, letterbox: Letterbox): Box {
  const box = {
    x1: (centerX - boxWidth / 2 - letterbox.padLeft) / letterbox.scale,
    y1: (centerY - boxHeight / 2 - letterbox.padTop) / letterbox.scale,
    x2: (centerX + boxWidth / 2 - letterbox.padLeft) / letterbox.scale,
    y2: (centerY + boxHeight / 2 - letterbox.padTop) / letterbox.scale,
  };
  return box;
}

export function mapRowToFrame(row: number[], letterbox: Letterbox): Box {
  const box = mapToFrame(row[0], row[1], row[2], row[3], letterbox);
  return box;
}

// The model input: 0-1 floats, RGB, NCHW.
export function makeBlob(letterbox: Letterbox): Float32Array {
  const { width, height, data } = letterbox.picture;
  const plane = width * height;
  const blob = new Float32Array(plane * 3);
  for (let pixel = 0; pixel < plane; pixel++) {
    blob[pixel] = data[pixel * 3] / 255;
    blob[plane + pixel] = data[pixel * 3 + 1] / 255;
    blob[2 * plane + pixel] = data[pixel * 3 + 2] / 255;
  }
  return blob;
}

interface Rect {
  left: number;
  top: number;
  width: number;
  height: number;
}

// OpenCV's rectOverlap: IoU in doubles, then through float32 the way it returns it. Two empty boxes count as the same box.
function findOverlap(first: Rect, second: Rect): number {
  const firstArea = first.width * first.height;
  const secondArea = second.width * second.height;
  let overlap = 1;
  if (firstArea + secondArea > Number.EPSILON) {
    const width = Math.min(first.left + first.width, second.left + second.width) - Math.max(first.left, second.left);
    const height = Math.min(first.top + first.height, second.top + second.height) - Math.max(first.top, second.top);
    const shared = width > 0 && height > 0 ? width * height : 0;
    overlap = Math.fround(1 - Math.fround(1 - shared / (firstArea + secondArea - shared)));
  }
  return overlap;
}

// cv2.dnn.NMSBoxes over center-format rows: the kept indices, strongest first. The rows and scores are float32 on
// the Pi, and NMSBoxes wants a score above the cutoff, not at it.
export function pickBoxes(rows: number[][], scores: number[]): number[] {
  const rects = rows.map(([centerX, centerY, width, height]) => ({
    left: Math.fround(centerX - width / 2),
    top: Math.fround(centerY - height / 2),
    width,
    height,
  }));
  const cutoff = Math.fround(MIN_CONFIDENCE);
  const ranked = scores
    .map((score, index) => ({ score: Math.fround(score), index }))
    .filter((candidate) => candidate.score > cutoff)
    .sort((first, second) => second.score - first.score);
  const kept: number[] = [];
  for (const { index } of ranked) {
    if (kept.every((other) => findOverlap(rects[index], rects[other]) <= NMS_IOU)) {
      kept.push(index);
    }
  }
  return kept;
}

// output is the raw YOLO tensor, (1, 4 + 80, anchors) flattened. Each anchor counts only for its single best class
// out of all 80, which is what stops a mouse or a TV remote from counting as a phone.
export function decodeObjects(output: Float32Array, letterbox: Letterbox): Detection[] {
  const anchors = output.length / (BOX_VALUES + CLASSES);
  const bestClass = new Int32Array(anchors);
  const bestScore = new Float32Array(anchors);
  for (let anchor = 0; anchor < anchors; anchor++) {
    let best = 0;
    let score = output[BOX_VALUES * anchors + anchor];
    for (let classId = 1; classId < CLASSES; classId++) {
      const value = output[(BOX_VALUES + classId) * anchors + anchor];
      if (value > score) {
        best = classId;
        score = value;
      }
    }
    bestClass[anchor] = best;
    bestScore[anchor] = score;
  }

  const detections: Detection[] = [];
  for (const [classId, label] of LABELS) {
    const rows: number[][] = [];
    const scores: number[] = [];
    for (let anchor = 0; anchor < anchors; anchor++) {
      if (bestClass[anchor] === classId && bestScore[anchor] >= MIN_CONFIDENCE) {
        rows.push([0, 1, 2, 3].map((value) => output[value * anchors + anchor]));
        scores.push(bestScore[anchor]);
      }
    }
    for (const index of pickBoxes(rows, scores)) {
      detections.push({ label, confidence: scores[index], box: mapRowToFrame(rows[index], letterbox) });
    }
  }
  detections.sort((first, second) => second.confidence - first.confidence);
  return detections;
}

// Intersection over union, 0 for boxes that don't touch.
export function measureOverlap(first: Box, second: Box): number {
  const width = Math.min(first.x2, second.x2) - Math.max(first.x1, second.x1);
  const height = Math.min(first.y2, second.y2) - Math.max(first.y1, second.y1);
  const shared = width > 0 && height > 0 ? width * height : 0;
  const union = (first.x2 - first.x1) * (first.y2 - first.y1) + (second.x2 - second.x1) * (second.y2 - second.y1) - shared;
  const overlap = union > 0 ? shared / union : 0;
  return overlap;
}

// The mouse scored at least as high and sits on the phone: over MOUSE_VETO_IOU, or the phone's center inside it.
function isMouse(phone: Detection, mouse: Detection): boolean {
  const centerX = (phone.box.x1 + phone.box.x2) / 2;
  const centerY = (phone.box.y1 + phone.box.y2) / 2;
  const holdsCenter = mouse.box.x1 <= centerX && centerX <= mouse.box.x2 && mouse.box.y1 <= centerY && centerY <= mouse.box.y2;
  const vetoed = mouse.confidence >= phone.confidence && (holdsCenter || measureOverlap(phone.box, mouse.box) > MOUSE_VETO_IOU);
  return vetoed;
}

// The phones no mouse box outscores in the same place: a hand on a mouse is the commonest fake phone at a desk. Both
// lists have to come from the same camera's frame.
export function dropMousePhones(phones: Detection[], mice: Detection[]): Detection[] {
  const kept = phones.filter((phone) => !mice.some((mouse) => isMouse(phone, mouse)));
  return kept;
}

// The person's box plus some margin (hands and lap stick out of it), in whole pixels.
export function findZoomRegion(person: Box, frameWidth: number, frameHeight: number): Box {
  const width = person.x2 - person.x1;
  const height = person.y2 - person.y1;
  const region = {
    x1: Math.max(0, Math.trunc(person.x1 - ZOOM_MARGIN_SIDES * width)),
    y1: Math.max(0, Math.trunc(person.y1 - ZOOM_MARGIN_TOP * height)),
    x2: Math.min(frameWidth, Math.trunc(person.x2 + ZOOM_MARGIN_SIDES * width)),
    y2: Math.min(frameHeight, Math.trunc(person.y2 + ZOOM_MARGIN_BOTTOM * height)),
  };
  return region;
}

export function shiftBox(box: Box, offsetX: number, offsetY: number): Box {
  const shifted = { x1: box.x1 + offsetX, y1: box.y1 + offsetY, x2: box.x2 + offsetX, y2: box.y2 + offsetY };
  return shifted;
}

export async function detectObjects(picture: Picture, runObjects: RunModel): Promise<Detection[]> {
  const letterbox = fitToInput(picture);
  const [output] = await runObjects(makeBlob(letterbox), [1, 3, INPUT_HEIGHT, INPUT_WIDTH]);
  const detections = decodeObjects(output, letterbox);
  return detections;
}

// Everything the zoomed pass around the main person finds, moved back onto the frame; nothing without a clear person.
export async function zoomIn(picture: Picture, people: Detection[], runObjects: RunModel): Promise<Detection[]> {
  const main = people.reduce<Detection | null>((best, person) => (best === null || person.confidence > best.confidence ? person : best), null);
  let zoomed: Detection[] = [];
  if (main !== null && main.confidence >= ZOOM_PERSON_MIN) {
    const region = findZoomRegion(main.box, picture.width, picture.height);
    const crop = cropPicture(picture, region.x1, region.y1, region.x2, region.y2);
    zoomed = (await detectObjects(crop, runObjects)).map((found) => ({ ...found, box: shiftBox(found.box, region.x1, region.y1) }));
  }
  return zoomed;
}

// Phones only come from the zoomed pass, so no person means no zoomed pass; mice come from both.
export async function scanDesk(picture: Picture, runObjects: RunModel): Promise<DeskScan> {
  const found = await detectObjects(picture, runObjects);
  const people = found.filter((detection) => detection.label === "person");
  const zoomed = await zoomIn(picture, people, runObjects);
  const scan = {
    people,
    phones: zoomed.filter((detection) => detection.label === "phone"),
    mice: [...found, ...zoomed].filter((detection) => detection.label === "mouse"),
  };
  return scan;
}
