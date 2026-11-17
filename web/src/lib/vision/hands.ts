import { mapRowToFrame, pickBoxes, type Box, type Detection, type Letterbox, type RunModel } from "@/lib/vision/detector";
import { findRotation, invertAffine, padPicture, resizePicture, roundHalfEven, warpPicture, type Affine, type Picture } from "@/lib/vision/image";

// dayanpi/vision/hands.py for the browser: MediaPipe's palm model finds palms in the whole frame squeezed into
// 192x192, then its hand model finds the 21 joints in a 224x224 crop around each palm, turned so the fingers
// point up. Joint numbering is MediaPipe's: 0 is the wrist, then 4 per finger from the base out.

export const PALM_INPUT_SIZE = 192;
export const HAND_INPUT_SIZE = 224;
export const PALM_MIN_CONFIDENCE = 0.6;
export const HAND_MIN_CONFIDENCE = 0.8;
export const MAX_HANDS = 2;
export const PALM_WRIST = 0;
export const PALM_MIDDLE_BASE = 2;
// The hand crop: the turned palm's box, moved toward the fingers by 0.4 of its height and grown to a square 3
// times its longer side, so the fingertips fit.
export const HAND_CROP_SHIFT = -0.4;
export const HAND_CROP_SCALE = 3.0;
export const JOINTS = 21;
// A phone counts when its box touches a hand's box grown by this much of the hand's longer side.
export const NEAR_HAND_MARGIN = 0.25;
const PALM_ROW = 18;
const PALM_POINTS = 7;

export interface Palm {
  confidence: number;
  box: Box;
  points: number[][]; // 7 [x, y] in frame pixels
}

export interface Hand {
  confidence: number;
  joints: number[][]; // 21 [x, y, z]: frame pixels, z the depth from the wrist on the same scale
}

export interface HandModels {
  palm: RunModel;
  hand: RunModel;
}

export function findHandBox(hand: Hand): Box {
  const xs = hand.joints.map((joint) => joint[0]);
  const ys = hand.joints.map((joint) => joint[1]);
  const box = { x1: Math.min(...xs), y1: Math.min(...ys), x2: Math.max(...xs), y2: Math.max(...ys) };
  return box;
}

export function isNearHand(phone: Box, hand: Box): boolean {
  const margin = NEAR_HAND_MARGIN * Math.max(hand.x2 - hand.x1, hand.y2 - hand.y1);
  const near = phone.x1 <= hand.x2 + margin && phone.x2 >= hand.x1 - margin && phone.y1 <= hand.y2 + margin && phone.y2 >= hand.y1 - margin;
  return near;
}

// The phones whose box touches or nearly touches a hand's box, so a phone lying on the desk doesn't count.
export function findPhonesInHand(phones: Detection[], hands: Hand[]): Detection[] {
  const handBoxes = hands.map(findHandBox);
  const held = phones.filter((phone) => handBoxes.some((handBox) => isNearHand(phone.box, handBox)));
  return held;
}

// The palm model's 2016 anchor centers as 0-1 fractions of its input, [x, y] pairs: every cell of a 24x24 grid
// holds 2, then every cell of a 12x12 grid holds 6, in reading order.
export function buildAnchors(): Float32Array {
  const centers: number[] = [];
  for (const [cells, perCell] of [
    [24, 2],
    [12, 6],
  ]) {
    for (let row = 0; row < cells; row++) {
      for (let column = 0; column < cells; column++) {
        for (let copy = 0; copy < perCell; copy++) {
          centers.push((column + 0.5) / cells, (row + 0.5) / cells);
        }
      }
    }
  }
  const anchors = new Float32Array(centers);
  return anchors;
}

const ANCHORS = buildAnchors();

// Shrinks the frame into a size x size square, padded with black on the short side.
export function fitSquare(picture: Picture, size: number): Letterbox {
  const scale = size / Math.max(picture.height, picture.width);
  const resized = resizePicture(picture, roundHalfEven(picture.width * scale), roundHalfEven(picture.height * scale));
  const left = Math.floor((size - resized.width) / 2);
  const top = Math.floor((size - resized.height) / 2);
  const padding = { top, bottom: size - resized.height - top, left, right: size - resized.width - left };
  const letterbox = { picture: padPicture(resized, padding, 0), scale, padLeft: left, padTop: top };
  return letterbox;
}

// Both hand models take 0-1 floats, RGB, NHWC (not the NCHW the YOLO model takes).
export function makeHandBlob(picture: Picture): Float32Array {
  const blob = Float32Array.from(picture.data, (value) => value / 255);
  return blob;
}

// rows is the palm model's (1, 2016, 18) and logits its (1, 2016, 1), flattened. Each row is a box (center offset
// from its anchor, then width and height) and the 7 points as offsets from the anchor, all in input pixels.
export function decodePalms(rows: Float32Array, logits: Float32Array, letterbox: Letterbox, anchors: Float32Array = ANCHORS): Palm[] {
  const boxes: number[][] = [];
  const points: number[][][] = [];
  const scores: number[] = [];
  for (let index = 0; index < logits.length; index++) {
    const score = 1 / (1 + Math.exp(-logits[index]));
    if (score >= PALM_MIN_CONFIDENCE) {
      // float32 sums, like numpy's on the Pi.
      const anchorX = Math.fround(anchors[index * 2] * PALM_INPUT_SIZE);
      const anchorY = Math.fround(anchors[index * 2 + 1] * PALM_INPUT_SIZE);
      const row = rows.subarray(index * PALM_ROW, (index + 1) * PALM_ROW);
      boxes.push([Math.fround(row[0] + anchorX), Math.fround(row[1] + anchorY), row[2], row[3]]);
      points.push(Array.from({ length: PALM_POINTS }, (_, point) => [Math.fround(row[4 + point * 2] + anchorX), Math.fround(row[5 + point * 2] + anchorY)]));
      scores.push(score);
    }
  }
  const palms = pickBoxes(boxes, scores)
    .slice(0, MAX_HANDS)
    .map((index) => ({
      confidence: scores[index],
      box: mapRowToFrame(boxes[index], letterbox),
      points: points[index].map(([x, y]) => [(x - letterbox.padLeft) / letterbox.scale, (y - letterbox.padTop) / letterbox.scale]),
    }));
  return palms;
}

// The 2x3 warp from the frame into the hand model's input, fingers pointing up.
export function findHandCrop(palm: Palm): Affine {
  const [wristX, wristY] = palm.points[PALM_WRIST];
  const [middleX, middleY] = palm.points[PALM_MIDDLE_BASE];
  const angle = 90 - Math.atan2(wristY - middleY, middleX - wristX) * (180 / Math.PI);
  const turn = findRotation(0, 0, angle, 1);
  const turned = palm.points.map(([x, y]) => [x * turn[0][0] + y * turn[0][1], x * turn[1][0] + y * turn[1][1]]);
  const lowX = Math.min(...turned.map((point) => point[0]));
  const highX = Math.max(...turned.map((point) => point[0]));
  const lowY = Math.min(...turned.map((point) => point[1]));
  const highY = Math.max(...turned.map((point) => point[1]));
  const turnedX = (lowX + highX) / 2;
  const turnedY = (lowY + highY) / 2 + HAND_CROP_SHIFT * (highY - lowY);
  // Turned back: the inverse of a rotation is its transpose.
  const centerX = turnedX * turn[0][0] + turnedY * turn[1][0];
  const centerY = turnedX * turn[0][1] + turnedY * turn[1][1];
  const side = HAND_CROP_SCALE * Math.max(highX - lowX, highY - lowY);
  const warp = findRotation(centerX, centerY, angle, HAND_INPUT_SIZE / side);
  warp[0][2] += HAND_INPUT_SIZE / 2 - centerX;
  warp[1][2] += HAND_INPUT_SIZE / 2 - centerY;
  return warp;
}

// joints is the hand model's (1, 63): x, y, z in crop pixels, back through the inverse of the crop's warp.
export function decodeHand(joints: Float32Array, confidence: number, warp: Affine): Hand | null {
  let hand: Hand | null = null;
  if (confidence >= HAND_MIN_CONFIDENCE) {
    const [[a, b, c], [d, e, f]] = invertAffine(warp);
    const depthScale = Math.hypot(a, d);
    const frameJoints = Array.from({ length: JOINTS }, (_, joint) => {
      const [x, y, z] = joints.subarray(joint * 3, joint * 3 + 3);
      return [x * a + y * b + c, x * d + y * e + f, z * depthScale];
    });
    hand = { confidence, joints: frameJoints };
  }
  return hand;
}

export async function findPalms(picture: Picture, runPalm: RunModel): Promise<Palm[]> {
  const letterbox = fitSquare(picture, PALM_INPUT_SIZE);
  const [rows, logits] = await runPalm(makeHandBlob(letterbox.picture), [1, PALM_INPUT_SIZE, PALM_INPUT_SIZE, 3]);
  const palms = decodePalms(rows, logits, letterbox);
  return palms;
}

export async function readHand(picture: Picture, palm: Palm, runHand: RunModel): Promise<Hand | null> {
  const warp = findHandCrop(palm);
  const crop = warpPicture(picture, warp, HAND_INPUT_SIZE);
  const [joints, confidence] = await runHand(makeHandBlob(crop), [1, HAND_INPUT_SIZE, HAND_INPUT_SIZE, 3]);
  const hand = decodeHand(joints, confidence[0], warp);
  return hand;
}

export async function scanHands(picture: Picture, models: HandModels): Promise<Hand[]> {
  const found: Hand[] = [];
  for (const palm of await findPalms(picture, models.palm)) {
    const hand = await readHand(picture, palm, models.hand);
    if (hand !== null) {
      found.push(hand);
    }
  }
  return found;
}
