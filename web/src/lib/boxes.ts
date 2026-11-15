import type { Overlay, OverlayBox } from "@/lib/types";

export const OVERLAY_STALE_S = 3; // older boxes would trail behind the live video
export const LABEL_INSIDE_BELOW = 0.08; // a box this close to the top keeps its label inside
export const BOX_FADE_MS = 400;

export interface RankedBox {
  key: string;
  box: OverlayBox;
}

export interface PlacedBox {
  left: string;
  top: string;
  width: string;
  height: string;
  labelInside: boolean;
  text: string;
}

export function isOverlayFresh(overlay: Overlay | null | undefined, cameraOk: boolean): boolean {
  const fresh = overlay != null && cameraOk && overlay.age_s <= OVERLAY_STALE_S;
  return fresh;
}

// Keyed by kind and rank, so the strongest person box glides to its new spot each second
// instead of blinking out and back in.
export function rankBoxes(boxes: OverlayBox[]): RankedBox[] {
  const ranks: Record<string, number> = {};
  const ranked = boxes.map((box) => {
    ranks[box.kind] = (ranks[box.kind] ?? 0) + 1;
    return { key: `${box.kind}-${ranks[box.kind]}`, box };
  });
  return ranked;
}

export function placeBox(box: OverlayBox): PlacedBox {
  const placed = {
    left: `${box.x * 100}%`,
    top: `${box.y * 100}%`,
    width: `${box.width * 100}%`,
    height: `${box.height * 100}%`,
    labelInside: box.y < LABEL_INSIDE_BELOW,
    text: `${box.label} ${box.confidence.toFixed(2)}`,
  };
  return placed;
}
