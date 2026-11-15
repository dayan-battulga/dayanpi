import { useEffect, useRef, useState } from "react";
import { riseDelay } from "@/components/shared/rise";
import { replayAnimation } from "@/lib/motion";
import type { FocusStatus } from "@/lib/types";

const SIGN_PAGES: Record<string, string> = { now: "Now", today: "Today", summary: "Day done" };
const SIGN_PAGE_ORDER = ["now", "today", "summary"];
const FLIP_HOLD_S = 2.5; // the flipped page shows right away; the next snapshots confirm it

interface SignCardProps {
  sign: FocusStatus["sign"];
  now: number;
}

// The LED sign preview, smaller and lower on the page since the to-do list took its old spot.
export function SignCard({ sign, now }: SignCardProps) {
  const mode = sign?.mode ?? "off";
  const version = sign?.version ?? null;
  const [src, setSrc] = useState<string | null>(null);
  const [pictureShown, setPictureShown] = useState(false);
  const [loads, setLoads] = useState(0);
  const [busy, setBusy] = useState(false);
  const [flipped, setFlipped] = useState<{ page: string; until: number } | null>(null);
  const loading = useRef(false);
  const lastVersion = useRef<number | null>(null);
  const image = useRef<HTMLImageElement>(null);
  const lastPage = useRef<string | null>(null);
  const page = flipped != null && now < flipped.until ? flipped.page : (sign?.page ?? null);
  const pageIndex = page == null ? -1 : SIGN_PAGE_ORDER.indexOf(page);

  // A new src cancels the one still loading, so asking every second on a slow connection would never finish one.
  useEffect(() => {
    if (mode !== "off" && version !== lastVersion.current && !loading.current) {
      lastVersion.current = version;
      loading.current = true;
      setSrc(`/api/sign.png?v=${version}`);
    }
  }, [mode, version, loads]);

  useEffect(() => {
    if (page !== lastPage.current && lastPage.current != null && pictureShown) {
      replayAnimation(image.current, "slide");
    }
    lastPage.current = page;
  }, [page, pictureShown]);

  const flipPage = async () => {
    setBusy(true);
    try {
      const response = await fetch("/api/sign/page", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ step: 1 }),
      });
      const body = response.ok ? await response.json() : null;
      if (body != null) {
        setFlipped({ page: body.page, until: Date.now() / 1000 + FLIP_HOLD_S });
      }
    } catch {
      // The next snapshot shows the real page either way.
    } finally {
      setBusy(false);
    }
  };
  const handleLoad = () => {
    loading.current = false;
    setPictureShown(true);
    setLoads((count) => count + 1);
  };
  const handleError = () => {
    loading.current = false;
    lastVersion.current = null; // the next snapshot tries again, even if the picture hasn't changed
    setLoads((count) => count + 1);
  };

  const showPicture = mode !== "off" && pictureShown;
  return (
    <section className="card sign rise" style={riseDelay(4)} aria-label="LED sign">
      <div className="card-head">
        <div className="card-title">
          <h2 className="label">LED sign</h2>
          <span id="sign-page" className="mono muted small">
            {page == null ? "" : (SIGN_PAGES[page] ?? "")}
          </span>
        </div>
        <div className="sign-controls">
          <div
            id="sign-dots"
            className="sign-dots"
            role="img"
            aria-label={pageIndex >= 0 ? `Sign page ${pageIndex + 1} of 3: ${SIGN_PAGES[page as string]}` : "Sign page"}
          >
            {SIGN_PAGE_ORDER.map((name, index) => (
              <span key={name} className={index === pageIndex ? "sign-dot is-on" : "sign-dot"}></span>
            ))}
          </div>
          <button type="button" id="sign-flip" className="button button-ghost button-small" disabled={mode === "off" || busy} onClick={flipPage}>
            Flip sign page
          </button>
        </div>
      </div>
      <div className="led">
        {src != null && (
          <img
            id="sign-image"
            ref={image}
            alt="What the LED sign is showing"
            width="768"
            height="192"
            src={src}
            hidden={!showPicture}
            onLoad={handleLoad}
            onError={handleError}
          />
        )}
        <p id="sign-empty" className="led-empty mono" hidden={showPicture}>
          {mode === "off" ? "The sign is off" : "Waiting for the sign…"}
        </p>
      </div>
    </section>
  );
}
