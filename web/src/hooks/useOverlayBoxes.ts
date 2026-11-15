import { useEffect, useMemo, useRef, useState } from "react";
import { BOX_FADE_MS, isOverlayFresh, placeBox, rankBoxes, type PlacedBox } from "@/lib/boxes";
import type { Overlay } from "@/lib/types";

export interface ShownBox {
  key: string;
  renderKey: string;
  kind: string;
  placed: PlacedBox;
  leaving: boolean;
}

// The boxes to draw over one feed: the live ones straight from the overlay, plus the ones that
// just disappeared, which stay for BOX_FADE_MS with is-leaving so they fade instead of blinking out.
export function useOverlayBoxes(overlay: Overlay | null | undefined, cameraOk: boolean): ShownBox[] {
  const fresh = isOverlayFresh(overlay, cameraOk);
  const live = useMemo<ShownBox[]>(
    () =>
      fresh && overlay != null
        ? rankBoxes(overlay.boxes).map(({ key, box }) => ({ key, renderKey: key, kind: box.kind, placed: placeBox(box), leaving: false }))
        : [],
    [fresh, overlay],
  );
  const [leaving, setLeaving] = useState<ShownBox[]>([]);
  const previous = useRef<ShownBox[]>([]);
  const goneCount = useRef(0);

  useEffect(() => {
    const liveKeys = new Set(live.map((box) => box.key));
    const gone = previous.current
      .filter((box) => !liveKeys.has(box.key))
      .map((box) => ({ ...box, leaving: true, renderKey: `${box.key}:gone:${(goneCount.current += 1)}` }));
    previous.current = live;
    if (gone.length > 0) {
      setLeaving((current) => [...current, ...gone]);
      window.setTimeout(() => setLeaving((current) => current.filter((box) => !gone.includes(box))), BOX_FADE_MS);
    }
  }, [live]);

  const liveKeys = new Set(live.map((box) => box.key));
  const shown = [...live, ...leaving.filter((box) => !liveKeys.has(box.key))];
  return shown;
}
