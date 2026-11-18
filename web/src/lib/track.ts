import type { FrameReading } from "@/lib/vision/detector";
import type { Pace, PaceReason } from "@/lib/trackPace";
import type { FocusState, Spoken } from "@/lib/types";

// The tracker at /track: what its page and its worker say to each other, and what the page shows from it.

export const BOX_MIN = 0.5; // the tracker's PERSON_MIN and PHONE_MIN: a box only for what counts
// The seat's picture (study room step 7): the Pi's own size and quality (focus/pictures.py), about 7 KB a frame.
export const PICTURE_WIDTH = 320;
export const PICTURE_HEIGHT = 180;
export const PICTURE_QUALITY = 0.5;
const BASE64_CHUNK = 0x8000; // String.fromCharCode takes its bytes as arguments, so not all at once

export interface TrackBox {
  kind: "person" | "phone";
  x: number; // fractions of the frame
  y: number;
  width: number;
  height: number;
}

// The Pi's answer to a reading, in its own clock, with the peace sign's last message, so this page can play its clip.
export interface Tracked {
  state: FocusState;
  seconds_in_state: number;
  paused: boolean;
  spoken?: Spoken | null;
  send_picture?: boolean; // the Pi wants the seat's picture with the next reading: video shared, and at the desk
}

export type TrackerRequest = { type: "start"; frames: ReadableStream<VideoFrame>; lowBattery: boolean } | { type: "battery"; low: boolean };

export type TrackerReply =
  | { type: "ready"; backend: string; loadMs: number }
  | { type: "check"; ms: number; boxes: TrackBox[]; pace: Pace }
  | ({ type: "tracked" } & Tracked)
  | { type: "signed-out" }
  | { type: "refused" }
  | { type: "failed"; message: string };

// A JPEG's bytes as base64, for the reading's JSON (every write to the Pi is JSON).
export function encodeBase64(bytes: Uint8Array): string {
  let text = "";
  for (let start = 0; start < bytes.length; start += BASE64_CHUNK) {
    text += String.fromCharCode(...bytes.subarray(start, start + BASE64_CHUNK));
  }
  return btoa(text);
}

// The part of a width x height frame that fills the seat's 16:9 picture: its middle, cut to that shape.
export function findPictureCrop(width: number, height: number): { x: number; y: number; width: number; height: number } {
  const cropWidth = Math.min(width, Math.round((height * PICTURE_WIDTH) / PICTURE_HEIGHT));
  const cropHeight = Math.min(height, Math.round((width * PICTURE_HEIGHT) / PICTURE_WIDTH));
  const crop = { x: Math.floor((width - cropWidth) / 2), y: Math.floor((height - cropHeight) / 2), width: cropWidth, height: cropHeight };
  return crop;
}

export function makeBoxes(reading: FrameReading, width: number, height: number): TrackBox[] {
  const found = [...reading.people.map((person) => ({ kind: "person" as const, found: person })), ...reading.phones.map((phone) => ({ kind: "phone" as const, found: phone }))];
  const boxes = found
    .filter(({ found }) => found.confidence >= BOX_MIN)
    .map(({ kind, found: { box } }) => ({ kind, x: box.x1 / width, y: box.y1 / height, width: (box.x2 - box.x1) / width, height: (box.y2 - box.y1) / height }));
  return boxes;
}

const PACE_NOTES: Record<PaceReason, string | null> = {
  normal: null,
  idle: "Nobody's here, so it checks every 3 s",
  busy: "This laptop is busy, so it checks every 2 s",
  battery: "The battery's low, so it checks every 2 s",
};

// The load line under the preview: time per check and memory, and why it's checking less often.
export function describeLoad(ms: number | null, memoryBytes: number | null, backend: string | null, reason: PaceReason): string {
  const parts = [
    ms === null ? "Loading the models" : `${Math.round(ms)} ms a check`,
    memoryBytes === null ? null : `memory ${Math.round(memoryBytes / 1e6)} MB`,
    backend,
    PACE_NOTES[reason],
  ];
  const text = parts.filter((part) => part !== null).join(" · ");
  return text;
}
