import type { FrameReading } from "@/lib/vision/detector";
import type { Pace, PaceReason } from "@/lib/trackPace";
import type { FocusState } from "@/lib/types";

// The tracker at /track: what its page and its worker say to each other, and what the page shows from it.

export const BOX_MIN = 0.5; // the tracker's PERSON_MIN and PHONE_MIN: a box only for what counts

export interface TrackBox {
  kind: "person" | "phone";
  x: number; // fractions of the frame
  y: number;
  width: number;
  height: number;
}

// The Pi's answer to a reading, in its own clock.
export interface Tracked {
  state: FocusState;
  seconds_in_state: number;
  paused: boolean;
}

export type TrackerRequest = { type: "start"; frames: ReadableStream<VideoFrame>; lowBattery: boolean } | { type: "battery"; low: boolean };

export type TrackerReply =
  | { type: "ready"; backend: string; loadMs: number }
  | { type: "check"; ms: number; boxes: TrackBox[]; pace: Pace }
  | ({ type: "tracked" } & Tracked)
  | { type: "signed-out" }
  | { type: "refused" }
  | { type: "failed"; message: string };

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
