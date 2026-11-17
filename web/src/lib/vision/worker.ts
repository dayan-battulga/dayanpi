import { scanDesk, type FrameReading, type RunModel } from "@/lib/vision/detector";
import { findPhonesInHand, scanHands, type HandModels } from "@/lib/vision/hands";
import type { Picture } from "@/lib/vision/image";

// The per-frame part of dayanpi/focus/worker.py (read_frame and check_hands): one detector pass, then the hand
// models, after which only phones near a hand still count. One camera, so merge_readings has nothing to merge.

export interface VisionModels {
  objects: RunModel;
  hands: HandModels | null; // null: no hand models, so phones count anywhere
}

// A hand model that throws costs only this check's hands: the phones stay as they were, so it can't switch phone
// detection off.
async function checkHands(reading: FrameReading, picture: Picture, models: HandModels): Promise<FrameReading> {
  let checked = { ...reading, handsFailed: true };
  try {
    const found = await scanHands(picture, models);
    checked = { ...reading, hands: found, phones: findPhonesInHand(reading.phones, found) };
  } catch {
    // Counted through handsFailed.
  }
  return checked;
}

export async function readFrame(picture: Picture, models: VisionModels): Promise<FrameReading> {
  const started = performance.now();
  const scan = await scanDesk(picture, models.objects);
  const scanned = { ...scan, hands: [], handsFailed: false, elapsedMs: 0 };
  const reading = models.hands === null ? scanned : await checkHands(scanned, picture, models.hands);
  const timed = { ...reading, elapsedMs: performance.now() - started };
  return timed;
}
