import { useEffect, useRef, useState } from "react";
import { Digits } from "@/components/focus/Digits";
import { Timeline } from "@/components/focus/Timeline";
import { riseDelay } from "@/components/shared/rise";
import { TickText } from "@/components/shared/TickText";
import { useReplayOnChange } from "@/hooks/useReplayOnChange";
import { formatClock, formatDate, formatDuration } from "@/lib/format";
import { replayAnimation } from "@/lib/motion";
import { STATE_COPY, describeCaption, describePhoneFree } from "@/lib/timeline";
import type { FocusStatus, Segment } from "@/lib/types";

interface FocusCardProps {
  focus: FocusStatus | undefined;
  segments: Segment[];
  known: Segment[];
  loaded: boolean;
  now: number;
  midnight: number;
  receivedAt: number;
}

export function FocusCard({ focus, segments, known, loaded, now, midnight, receivedAt }: FocusCardProps) {
  const copy = STATE_COPY[focus?.state ?? "unknown"] ?? STATE_COPY.unknown;
  const labelRef = useReplayOnChange<HTMLHeadingElement>(copy.label, "swap");
  const ripple = useRef<HTMLSpanElement>(null);
  const lastPickups = useRef<number | null>(null);
  const [blockBusy, setBlockBusy] = useState(false);
  const pickups = focus?.today.pickups;

  useEffect(() => {
    if (pickups != null && lastPickups.current != null && pickups > lastPickups.current) {
      replayAnimation(ripple.current, "rip");
    }
    lastPickups.current = pickups ?? null;
  }, [pickups]);

  // A disabled button fires no clicks, so these can't overlap; blockBusy keeps a snapshot from re-enabling it mid-request.
  const toggleBlock = async () => {
    setBlockBusy(true);
    try {
      await fetch("/api/focus/block", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "toggle" }),
      });
    } catch {
      // The next snapshot shows the real state either way.
    } finally {
      setBlockBusy(false);
    }
  };

  const blockActive = focus?.block.active ?? false;
  return (
    <section id="focus-card" className="card focus rise" style={riseDelay(1)} data-state={focus?.state ?? "unknown"} aria-label="Focus">
      <div className="focus-top">
        <div className="focus-chips">
          <span className="state-chip label">
            <span className="state-dot" aria-hidden="true"></span>
            <span id="focus-state" aria-live="polite">
              {focus == null ? "Starting" : copy.chip}
            </span>
          </span>
          <span id="focus-block-chip" className="label plain-chip" hidden={!blockActive}>
            Block on
          </span>
        </div>
        <span id="focus-date" className="mono muted small">
          {formatDate(now)}
        </span>
      </div>

      <div className="focus-headline">
        <h1 id="focus-label" ref={labelRef}>
          {copy.label}
        </h1>
        <p className="focus-timer mono" aria-label="Time in this state">
          {focus != null ? <Digits text={formatClock(focus.seconds_in_state + Math.max(0, now - receivedAt))} /> : <span id="focus-timer" />}
        </p>
      </div>

      <div className="focus-actions">
        <p id="focus-caption" className="muted">
          {focus == null ? "Waiting for the first snapshot" : describeCaption(focus)}
        </p>
        <div className="focus-buttons">
          <button
            type="button"
            id="focus-block"
            className={`button ${blockActive ? "button-ghost" : "button-primary"}`}
            disabled={focus == null || !focus.enabled || blockBusy}
            onClick={toggleBlock}
          >
            {blockActive ? "End block" : "Start block"}
          </button>
        </div>
      </div>

      <Timeline known={known} loaded={loaded} now={now} midnight={midnight} />

      <dl className="focus-stats">
        <div>
          <dt className="label">Focus</dt>
          <TickText as="dd" id="focus-working" className="mono" value={focus == null ? "--" : formatDuration(focus.today.working_seconds)} />
        </div>
        <div>
          <dt className="label">Phone</dt>
          <TickText as="dd" id="focus-phone" className="mono" value={focus == null ? "--" : formatDuration(focus.today.phone_seconds)} />
        </div>
        <div>
          <dt className="label">Pickups</dt>
          <dd className="mono">
            <span className="pickups">
              <span id="focus-ripple" className="ripple" ref={ripple} aria-hidden="true"></span>
              <TickText id="focus-pickups" value={pickups ?? "--"} />
            </span>
          </dd>
        </div>
        <div>
          <dt className="label">Phone-free</dt>
          <TickText as="dd" id="focus-free" className="mono" value={focus == null ? "--" : describePhoneFree(focus, segments, now)} />
        </div>
        <div>
          <dt className="label">Best streak</dt>
          <TickText as="dd" id="focus-best" className="mono" value={focus == null ? "--" : formatDuration(focus.today.longest_streak_seconds)} />
        </div>
      </dl>
    </section>
  );
}
